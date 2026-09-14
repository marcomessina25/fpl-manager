from pathlib import Path
import pytest

from fpl_manager.decision_log import record_gameweek_decision
from fpl_manager.evaluation import (
    compute_counterfactual_lineups,
    compute_decision_confidence,
    evaluate_gameweek_decision,
)
from fpl_manager.models import Position
from fpl_manager.storage import SnapshotStore, utc_timestamp


def test_compute_decision_confidence() -> None:
    # High confidence scenario: starters far clear of bench, clear captaincy, high p_start
    high_conf = compute_decision_confidence(
        starter_xps=[7.5, 6.0, 5.8, 5.5, 5.2, 5.0, 4.8, 4.5, 4.2, 4.0, 3.8],
        bench_xps=[1.5, 1.2, 1.0, 0.5],
        captain_xp=7.5,
        vice_captain_xp=5.5,
        starter_p_starts=[0.95] * 11,
    )
    assert high_conf["confidence_score"] >= 75.0
    assert high_conf["confidence_label"] == "HIGH"
    assert high_conf["lineup_certainty_margin"] > 2.0
    assert high_conf["captaincy_certainty_margin"] >= 2.0
    assert high_conf["rotation_risk_index"] <= 0.10

    # Low confidence scenario: bench player has higher xP than starter, captaincy toss-up, heavy rotation risk
    low_conf = compute_decision_confidence(
        starter_xps=[4.0, 3.5, 3.2, 3.0, 2.8, 2.7, 2.5, 2.4, 2.2, 2.1, 1.8],
        bench_xps=[3.5, 3.0, 2.8, 1.0],  # bench player 3.5 > starter 1.8
        captain_xp=4.0,
        vice_captain_xp=3.9,
        starter_p_starts=[0.60] * 11,
    )
    assert low_conf["confidence_score"] < 50.0
    assert low_conf["confidence_label"] in ("LOW", "SPECULATIVE")
    assert low_conf["lineup_certainty_margin"] < 0.0
    assert low_conf["rotation_risk_index"] >= 0.35


def test_compute_counterfactual_lineups() -> None:
    decision = {
        "squad_player_ids": list(range(1, 16)),
        "starting_player_ids": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
        "bench_player_ids": [12, 13, 14, 15],
        "captain_id": 10,
        "transfer_hits": 1,
    }
    model_rec = {
        "starters": [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}, {"id": 6}, {"id": 7}, {"id": 8}, {"id": 9}, {"id": 12}, {"id": 13}],
        "captain": {"id": 2},
    }

    # Players 1 (GKP), 2-6 (DEF), 7-11 (MID), 12-14 (FWD), 15 (GKP)
    players_meta = {}
    for pid in range(1, 16):
        pos = Position.GOALKEEPER if pid in (1, 15) else (Position.DEFENDER if pid <= 6 else (Position.MIDFIELDER if pid <= 11 else Position.FORWARD))
        players_meta[pid] = {"name": f"P{pid}", "position": pos}

    actual_scores = {pid: 2.0 for pid in range(1, 16)}
    # Benched player 12 (FWD) scores a hat-trick (17 pts)
    actual_scores[12] = 17.0
    actual_scores[10] = 6.0
    actual_scores[2] = 8.0

    cf = compute_counterfactual_lineups(decision, model_rec, actual_scores, players_meta)

    assert "human_actual_total" in cf
    assert "model_actual_total" in cf
    assert "hybrid_actual_total" in cf
    assert "hindsight_optimal" in cf

    # Hindsight optimal must include player 12 and be >= human and model
    hindsight = cf["hindsight_optimal"]
    assert "[HINDSIGHT ONLY]" in hindsight["disclaimer"]
    assert 12 in hindsight["starting_player_ids"]
    assert hindsight["total_points"] >= cf["human_actual_total"]
    assert hindsight["total_points"] >= cf["model_actual_total"]
    assert hindsight["hindsight_gap_points"] > 0.0


def test_evaluate_gameweek_decision_includes_v09_closed_loop(tmp_path: Path) -> None:
    db_path = tmp_path / "fpl.sqlite3"
    store = SnapshotStore(db_path)
    store.initialize()

    bootstrap = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Chelsea", "short_name": "CHE"},
            {"id": 3, "name": "Liverpool", "short_name": "LIV"},
            {"id": 4, "name": "Man City", "short_name": "MCI"},
            {"id": 5, "name": "Tottenham", "short_name": "TOT"},
        ],
        "elements": [],
    }

    for p_id in range(1, 16):
        pos_id = 1 if p_id <= 2 else (2 if p_id <= 7 else (3 if p_id <= 12 else 4))
        bootstrap["elements"].append({
            "id": p_id,
            "web_name": f"Player_{p_id}",
            "team": ((p_id - 1) % 5) + 1,
            "element_type": pos_id,
            "now_cost": 50,
            "status": "a",
            "total_points": 30,
        })

    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
    ]
    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    squad_ids = list(range(1, 16))
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]
    bench = [2, 6, 7, 15]

    record_gameweek_decision(
        gameweek=1,
        squad_player_ids=squad_ids,
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=13,
        vice_captain_id=8,
        database_path=db_path,
        overwrite=True,
    )

    actual_scores = {pid: 5.0 for pid in squad_ids}
    actual_scores[13] = 10.0

    eval_res = evaluate_gameweek_decision(1, actual_scores=actual_scores, database_path=db_path)
    assert eval_res["decision_logged"] is True
    assert "decision_confidence" in eval_res
    assert eval_res["decision_confidence"]["confidence_score"] > 0.0
    assert "counterfactuals" in eval_res
    assert eval_res["counterfactuals"]["hindsight_optimal"]["total_points"] is not None
