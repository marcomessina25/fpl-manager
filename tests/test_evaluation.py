"""Tests for model backtesting, accuracy evaluation, and regret analysis."""

import json
from pathlib import Path
import pytest

from fpl_manager.cli import _parse_scores_argument, format_evaluation_concise
from fpl_manager.decision_log import record_actual_gameweek_score, record_gameweek_decision
from fpl_manager.evaluation import (
    compare_human_vs_model,
    evaluate_bench_decision,
    evaluate_captaincy_decision,
    evaluate_gameweek_decision,
    evaluate_predictions,
    evaluate_season_decisions,
    mean_absolute_error,
    root_mean_squared_error,
    spearman_rank_correlation,
    uncertainty_calibration,
)
from fpl_manager.storage import SnapshotStore, utc_timestamp


def test_spearman_rank_correlation() -> None:
    # Perfect positive correlation
    assert spearman_rank_correlation([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == 1.0

    # Perfect negative correlation
    assert spearman_rank_correlation([1, 2, 3, 4, 5], [50, 40, 30, 20, 10]) == -1.0

    # Ties in ranks
    corr = spearman_rank_correlation([1, 2, 2, 4], [2, 3, 3, 5])
    assert corr == 1.0

    # Edge cases
    assert spearman_rank_correlation([1], [2]) == 0.0
    assert spearman_rank_correlation([5, 5, 5], [5, 5, 5]) == 0.0


def test_mae_and_rmse() -> None:
    pred = [5.0, 4.0, 3.0]
    act = [7.0, 4.0, 1.0]

    # MAE = (|5-7| + |4-4| + |3-1|) / 3 = (2 + 0 + 2) / 3 = 1.333
    assert mean_absolute_error(pred, act) == 1.333

    # RMSE = sqrt((4 + 0 + 4) / 3) = sqrt(2.6667) = 1.633
    assert root_mean_squared_error(pred, act) == 1.633

    assert mean_absolute_error([], []) == 0.0
    assert root_mean_squared_error([], []) == 0.0


def test_uncertainty_calibration() -> None:
    preds = [
        {"player_id": 1, "expected_points": 5.0, "xp_floor": 3.0, "xp_ceiling": 8.0},
        {"player_id": 2, "expected_points": 4.0, "xp_floor": 2.0, "xp_ceiling": 6.0},
        {"player_id": 3, "expected_points": 6.0, "xp_floor": 4.0, "xp_ceiling": 9.0},
        {"player_id": 4, "expected_points": 3.0, "xp_floor": 1.0, "xp_ceiling": 5.0},
    ]
    actuals = {
        1: 5.0,  # inside
        2: 1.0,  # below floor
        3: 12.0, # above ceiling
        4: 3.0,  # inside
    }
    calib = uncertainty_calibration(preds, actuals)
    assert calib["total_evaluated"] == 4
    assert calib["coverage_percent"] == 50.0
    assert calib["below_floor_percent"] == 25.0
    assert calib["above_ceiling_percent"] == 25.0


def test_evaluate_captaincy_and_bench_regret() -> None:
    starters = [1, 2, 3]
    bench = [4, 5]
    scores = {1: 4.0, 2: 12.0, 3: 2.0, 4: 9.0, 5: 1.0}
    names = {1: "Player 1", 2: "Player 2", 3: "Player 3", 4: "Player 4", 5: "Player 5"}

    # Captain was 1 (4 pts), best starter was 2 (12 pts) -> regret = 8.0
    cap_res = evaluate_captaincy_decision(starters, captain_id=1, vice_captain_id=3, actual_scores=scores, players_by_id=names)
    assert cap_res["captain_actual_points"] == 4.0
    assert cap_res["optimal_captain_id"] == 2
    assert cap_res["optimal_captain_actual_points"] == 12.0
    assert cap_res["captaincy_regret_points"] == 8.0

    # Best captain selected -> regret = 0.0
    cap_best = evaluate_captaincy_decision(starters, captain_id=2, vice_captain_id=1, actual_scores=scores, players_by_id=names)
    assert cap_best["captaincy_regret_points"] == 0.0

    # Bench: highest bench is 4 (9 pts), lowest starter is 3 (2 pts) -> regret = 7.0
    bench_res = evaluate_bench_decision(starters, bench, scores, names)
    assert bench_res["highest_bench_points"] == 9.0
    assert bench_res["lowest_starter_points"] == 2.0
    assert bench_res["bench_regret_points"] == 7.0


def test_compare_human_vs_model() -> None:
    decision = {
        "starting_player_ids": [1, 2, 3],
        "captain_id": 1,
        "transfer_hits": 1,
    }
    model_rec = {
        "starters": [{"id": 1}, {"id": 2}, {"id": 4}],
        "captain": {"id": 2},
    }
    scores = {1: 4.0, 2: 8.0, 3: 1.0, 4: 10.0}

    # Human: (4 + 8 + 1) + 4 (cap) - 4 (hit) = 13
    # Model: (4 + 8 + 10) + 8 (cap) = 30
    # Delta: 13 - 30 = -17
    hvm = compare_human_vs_model(decision, model_rec, scores)
    assert hvm["human_actual_total"] == 13.0
    assert hvm["model_actual_total"] == 30.0
    assert hvm["delta_points"] == -17.0
    assert hvm["starters_in_common"] == 2


@pytest.fixture
def eval_test_env(tmp_path: Path) -> Path:
    db_path = tmp_path / "fpl.sqlite3"
    store = SnapshotStore(db_path)
    store.initialize()

    bootstrap = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Liverpool", "short_name": "LIV"},
            {"id": 3, "name": "Manchester City", "short_name": "MCI"},
            {"id": 4, "name": "Chelsea", "short_name": "CHE"},
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
        {"id": 2, "event": 2, "team_h": 3, "team_a": 4, "team_h_difficulty": 2, "team_a_difficulty": 4, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())
    return db_path


def test_evaluate_gameweek_and_season(eval_test_env: Path, tmp_path: Path) -> None:
    db_path = eval_test_env
    squad_ids = list(range(1, 16))
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]
    bench = [2, 6, 7, 15]

    # Record decision for GW2
    record_gameweek_decision(
        gameweek=2,
        squad_player_ids=squad_ids,
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=13,
        vice_captain_id=8,
        database_path=db_path,
        overwrite=True,
    )

    actual_scores = {pid: 4.0 for pid in squad_ids}
    actual_scores[13] = 10.0  # captain
    actual_scores[8] = 6.0   # vice-captain
    actual_scores[14] = 12.0 # best starter

    res = evaluate_gameweek_decision(2, actual_scores=actual_scores, database_path=db_path)
    assert res["decision_logged"] is True
    assert res["captaincy"]["captain_actual_points"] == 10.0
    assert res["captaincy"]["optimal_captain_id"] == 14
    assert res["captaincy"]["captaincy_regret_points"] == 2.0

    # Finalize score for GW2
    record_actual_gameweek_score(2, 65, database_path=db_path)

    report_path = tmp_path / "evaluation.json"
    season_res = evaluate_season_decisions(database_path=db_path, report_path=report_path)
    assert season_res["finalized_gameweeks"] == 1
    assert season_res["total_actual_points"] == 65.0
    assert report_path.exists()


def test_scores_parser_and_formatters(tmp_path: Path) -> None:
    # Parser: dict string
    assert _parse_scores_argument('{"1": 5.0, "2": 3.5}') == {1: 5.0, 2: 3.5}
    # Parser: comma-separated
    assert _parse_scores_argument("1:5.0,2:3.5") == {1: 5.0, 2: 3.5}
    # Parser: file
    f = tmp_path / "scores.json"
    f.write_text('{"3": 7.0}', encoding="utf-8")
    assert _parse_scores_argument(str(f)) == {3: 7.0}
    # Parser: None / empty
    assert _parse_scores_argument(None) is None
    assert _parse_scores_argument("") is None

    # Formatters
    sample_eval = {
        "gameweek": 2,
        "season": "2026/27",
        "decision_logged": True,
        "predicted_lineup_xp": 55.0,
        "actual_lineup_score": 62.0,
        "prediction_error_delta": 7.0,
        "prediction_accuracy": {
            "players_evaluated": 15,
            "mae": 1.45,
            "rmse": 1.80,
            "spearman_rank_correlation": 0.62,
            "calibration": {"coverage_percent": 80.0, "below_floor_percent": 10.0, "above_ceiling_percent": 10.0},
        },
        "captaincy": {
            "captain_name": "Haaland",
            "captain_actual_points": 12.0,
            "optimal_captain_name": "Haaland",
            "optimal_captain_actual_points": 12.0,
            "captaincy_regret_points": 0.0,
        },
    }
    concise = format_evaluation_concise(sample_eval)
    assert "Gameweek 2" in concise
    assert "MAE: 1.45 pts" in concise
    assert "Regret: 0.0 pts" in concise
