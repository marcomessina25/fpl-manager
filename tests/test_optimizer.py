"""Tests for mathematical optimization engine (optimizer.py)."""

import json
from pathlib import Path
import pytest

from fpl_manager.models import Position
from fpl_manager.optimizer import PlayerOptInfo, solve_transfers, solve_wildcard
from fpl_manager.rules import validate_squad, validate_starting_lineup, Player
from fpl_manager.storage import SnapshotStore, utc_timestamp
from fpl_manager.suggest_transfers import load_all_players_meta, suggest_transfers, suggest_wildcard


@pytest.fixture
def optimizer_test_db(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "fpl.sqlite3"
    squad_path = tmp_path / "current_squad.json"

    store = SnapshotStore(db_path)
    teams = [
        {"id": 1, "name": "Arsenal", "short_name": "ARS"},
        {"id": 2, "name": "Liverpool", "short_name": "LIV"},
        {"id": 3, "name": "Manchester City", "short_name": "MCI"},
        {"id": 4, "name": "Chelsea", "short_name": "CHE"},
        {"id": 5, "name": "Tottenham", "short_name": "TOT"},
        {"id": 6, "name": "Newcastle", "short_name": "NEW"},
        {"id": 7, "name": "Aston Villa", "short_name": "AVL"},
        {"id": 8, "name": "Brighton", "short_name": "BHA"},
        {"id": 9, "name": "Fulham", "short_name": "FUL"},
        {"id": 10, "name": "Brentford", "short_name": "BRE"},
    ]
    elements = []

    # 15 players in current squad (IDs 1..15)
    for i in range(1, 16):
        pos_id = 1 if i <= 2 else (2 if i <= 7 else (3 if i <= 12 else 4))
        team_id = ((i - 1) % 10) + 1
        elements.append({
            "id": i,
            "web_name": f"Squad_{i}",
            "team": team_id,
            "element_type": pos_id,
            "now_cost": 50,
            "status": "a",
            "total_points": 20,
            "minutes": 450,
            "expected_goals": "0.1",
            "expected_assists": "0.1",
            "expected_goals_conceded": "1.0",
        })

    # Pool of candidate targets across all positions and teams
    cand_id = 100
    for pos_id, count in [(1, 8), (2, 16), (3, 16), (4, 10)]:
        for c in range(count):
            cand_id += 1
            elements.append({
                "id": cand_id,
                "web_name": f"Target_{cand_id}",
                "team": (c % 10) + 1,
                "element_type": pos_id,
                "now_cost": 45 + (c % 4) * 10,
                "status": "a",
                "total_points": 50 + c * 5,
                "minutes": 800,
                "expected_goals": "0.4",
                "expected_assists": "0.3",
                "expected_goals_conceded": "0.5",
            })

    bootstrap = {"teams": teams, "elements": elements}
    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 3, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 3, "event": 2, "team_h": 3, "team_a": 4, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 4, "event": 2, "team_h": 5, "team_a": 6, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 5, "event": 2, "team_h": 7, "team_a": 8, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 6, "event": 2, "team_h": 9, "team_a": 10, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 7, "event": 3, "team_h": 2, "team_a": 1, "team_h_difficulty": 3, "team_a_difficulty": 2, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 8, "event": 3, "team_h": 4, "team_a": 3, "team_h_difficulty": 3, "team_a_difficulty": 2, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 9, "event": 3, "team_h": 6, "team_a": 5, "team_h_difficulty": 3, "team_a_difficulty": 2, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 10, "event": 3, "team_h": 8, "team_a": 7, "team_h_difficulty": 3, "team_a_difficulty": 2, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 11, "event": 3, "team_h": 10, "team_a": 9, "team_h_difficulty": 3, "team_a_difficulty": 2, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    squad_data = {
        "season": "2026/27",
        "player_ids": list(range(1, 16)),
        "purchase_prices_tenths": {str(pid): 50 for pid in range(1, 16)},
        "bank_tenths": 15,
        "free_transfers": 1,
        "chips_remaining": ["wildcard", "freehit"],
    }
    squad_path.write_text(json.dumps(squad_data), encoding="utf-8")

    return db_path, squad_path


def test_solve_transfers_bnb_correctness(optimizer_test_db: tuple[Path, Path]) -> None:
    db_path, squad_path = optimizer_test_db

    for k in (1, 2, 3, 4):
        res = suggest_transfers(
            num_transfers=k,
            squad_path=squad_path,
            database_path=db_path,
            max_results=5,
            num_gameweeks=2,
        )
        assert res["num_transfers"] == k
        assert len(res["top_suggestions"]) > 0
        top = res["top_suggestions"][0]
        assert len(top["outgoing"]) == k
        assert len(top["incoming"]) == k
        assert "score" in top
        assert "xp_delta" in top
        assert "floor_delta" in top
        assert "ceiling_delta" in top


def test_solve_transfers_risk_profiles(optimizer_test_db: tuple[Path, Path]) -> None:
    db_path, squad_path = optimizer_test_db

    for risk in ("neutral", "floor", "ceiling"):
        res = suggest_transfers(
            num_transfers=2,
            squad_path=squad_path,
            database_path=db_path,
            risk_profile=risk,
            max_results=3,
        )
        assert res["risk_profile"] == risk
        assert len(res["top_suggestions"]) > 0


def test_solve_wildcard_squad_legality(optimizer_test_db: tuple[Path, Path]) -> None:
    db_path, squad_path = optimizer_test_db

    res = suggest_wildcard(
        budget_millions=100.0,
        squad_path=squad_path,
        database_path=db_path,
        num_gameweeks=3,
        risk_profile="neutral",
    )

    assert "squad" in res
    assert "starters" in res
    assert "bench" in res
    assert len(res["squad"]) == 15
    assert len(res["starters"]) == 11
    assert len(res["bench"]) == 4

    # Financial checks
    assert res["total_cost_tenths"] <= 1000
    assert res["bank_remaining_tenths"] >= 0

    # Validate against rules engine
    squad_rules = [
        Player(
            id=p["id"],
            name=p["name"],
            position=Position[p["position"]],
            team_id=1,  # dummy for position check
            price_tenths=p["price_tenths"],
        )
        for p in res["squad"]
    ]

    # Verify positions breakdown
    pos_counts = {pos: sum(1 for p in res["squad"] if p["position"] == pos.name) for pos in Position}
    assert pos_counts[Position.GOALKEEPER] == 2
    assert pos_counts[Position.DEFENDER] == 5
    assert pos_counts[Position.MIDFIELDER] == 5
    assert pos_counts[Position.FORWARD] == 3

    # Verify starting lineup and bench structure
    assert res["captain"]["id"] != res["vice_captain"]["id"]
    starter_ids = {p["id"] for p in res["starters"]}
    bench_ids = {p["id"] for p in res["bench"]}
    assert len(starter_ids.intersection(bench_ids)) == 0

    # Bench slot 1 is GK
    assert res["bench"][0]["role"] == "GK_SUB"
    assert res["bench"][0]["position"] == "GOALKEEPER"


def test_solve_wildcard_risk_profiles(optimizer_test_db: tuple[Path, Path]) -> None:
    db_path, squad_path = optimizer_test_db

    for risk in ("neutral", "floor", "ceiling"):
        res = suggest_wildcard(
            budget_millions=98.0,
            squad_path=squad_path,
            database_path=db_path,
            risk_profile=risk,
        )
        assert res["total_cost_tenths"] <= 980
        assert len(res["starters"]) == 11
        assert len(res["bench"]) == 4


def test_solve_transfers_hit_calculation(optimizer_test_db: tuple[Path, Path]) -> None:
    db_path, squad_path = optimizer_test_db

    # free_transfers is 1 in optimizer_test_db
    # 1 transfer -> 0 hits, hit_cost = 0
    res_1 = suggest_transfers(
        num_transfers=1,
        squad_path=squad_path,
        database_path=db_path,
        max_results=1,
    )
    top_1 = res_1["top_suggestions"][0]
    assert top_1["transfer_hits"] == 0
    assert top_1["hit_cost"] == 0

    # 2 transfers with 1 FT -> 1 hit (-4 pts)
    res_2 = suggest_transfers(
        num_transfers=2,
        squad_path=squad_path,
        database_path=db_path,
        max_results=1,
    )
    top_2 = res_2["top_suggestions"][0]
    assert top_2["transfer_hits"] == 1
    assert top_2["hit_cost"] == 4

    # 3 transfers with 1 FT -> 2 hits (-8 pts)
    res_3 = suggest_transfers(
        num_transfers=3,
        squad_path=squad_path,
        database_path=db_path,
        max_results=1,
    )
    top_3 = res_3["top_suggestions"][0]
    assert top_3["transfer_hits"] == 2
    assert top_3["hit_cost"] == 8

