"""Unit and integration tests for prediction backtesting engine (V0.7.1)."""

import json
from pathlib import Path
import pytest

from fpl_manager.backtest.metrics import (
    PredictionEvaluationRecord,
    evaluate_predictions,
    run_prediction_backtest,
)
from fpl_manager.backtest.reporting import format_prediction_report
from fpl_manager.historical.ingestion import generate_mock_season
from fpl_manager.historical.reconstruction import reconstruct_features_and_project
from fpl_manager.historical.snapshots import build_historical_snapshot
from fpl_manager.models import Position


def test_reconstruct_features_and_project(tmp_path: Path) -> None:
    season_dir = tmp_path / "mock_season"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=3, num_teams=4, players_per_team=5)

    snapshot = build_historical_snapshot(season_dir, gameweek=2)
    projections = reconstruct_features_and_project(snapshot)

    assert len(projections) == len(snapshot.players)
    assert len(projections) == 20

    for proj in projections:
        assert proj.gameweek == 2
        assert proj.expected_points >= 0.0
        assert proj.expected_minutes >= 0.0
        assert 0.0 <= proj.availability_pct <= 100.0


def test_evaluate_predictions_metrics() -> None:
    records = [
        PredictionEvaluationRecord(
            season="2023-24",
            gameweek=1,
            player_id=1,
            web_name="Player A",
            position=Position.FORWARD,
            price_tenths=85,
            predicted_xp=5.5,
            actual_points=6,
            predicted_minutes=85.0,
            actual_minutes=90,
            predicted_availability=1.0,
            actual_availability=True,
        ),
        PredictionEvaluationRecord(
            season="2023-24",
            gameweek=1,
            player_id=2,
            web_name="Player B",
            position=Position.MIDFIELDER,
            price_tenths=60,
            predicted_xp=4.0,
            actual_points=2,
            predicted_minutes=70.0,
            actual_minutes=45,
            predicted_availability=0.9,
            actual_availability=True,
        ),
        PredictionEvaluationRecord(
            season="2023-24",
            gameweek=1,
            player_id=3,
            web_name="Player C",
            position=Position.DEFENDER,
            price_tenths=45,
            predicted_xp=0.0,
            actual_points=0,
            predicted_minutes=0.0,
            actual_minutes=0,
            predicted_availability=0.0,
            actual_availability=False,
        ),
    ]

    metrics = evaluate_predictions(records)
    assert metrics["total_records"] == 3

    # Check xP metrics
    xp = metrics["xp"]
    assert "overall_mae" in xp
    assert "overall_rmse" in xp
    assert "spearman_correlation" in xp
    assert "bias" in xp
    assert xp["overall_mae"] > 0.0

    # Check xM metrics
    xm = metrics["xm"]
    assert "overall_mae" in xm
    assert "calibration_buckets" in xm

    # Check availability
    avail = metrics["availability"]
    assert avail["accuracy"] == 1.0
    assert avail["precision"] == 1.0
    assert avail["recall"] == 1.0

    # Test reporting
    report = format_prediction_report(metrics, season="2023-24", gameweek_range="1")
    assert "Historical Prediction Backtest Report" in report
    assert "MAE" in report
    assert "RMSE" in report


def test_run_prediction_backtest_integration(tmp_path: Path) -> None:
    season_dir = tmp_path / "mock_season"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=4, num_teams=4, players_per_team=5)

    metrics, records = run_prediction_backtest(season_dir, start_gw=1, end_gw=3)

    assert len(records) == 20 * 3  # 20 players * 3 GWs
    assert metrics["total_records"] == 60
    assert metrics["xp"]["overall_mae"] >= 0.0
    assert metrics["xm"]["overall_mae"] >= 0.0
    assert "FORWARD" in metrics["by_position"]
    assert "budget (<=5.0m)" in metrics["by_price_tier"]
