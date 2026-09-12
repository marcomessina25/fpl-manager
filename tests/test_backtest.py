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


def test_cli_backtest_commands(monkeypatch, capsys) -> None:
    from fpl_manager.cli import main

    # 1. Test backtest-predictions via CLI
    main(["backtest-predictions", "--season", "2023-24", "--start-gw", "1", "--end-gw", "2", "--report"])
    captured = capsys.readouterr()
    assert "Historical Prediction Backtest Report" in captured.out
    assert "MAE" in captured.out

    # 2. Test backtest-decisions via CLI
    main(["backtest-decisions", "--season", "2023-24", "--strategy", "notransfer", "--start-gw", "1", "--end-gw", "2"])
    captured = capsys.readouterr()
    assert "[No-Transfer Baseline" in captured.out
    assert "Net Points:" in captured.out


def test_build_backtest_report_path_naming(tmp_path: Path) -> None:
    from fpl_manager.backtest.reporting import build_backtest_report_path

    # Prediction report path
    pred_path = build_backtest_report_path("predictions", "2023-24", 1, 38, directory=tmp_path, version="0.7.0")
    assert pred_path.name == "0.7.0_backtest_predictions_2023-24_1_38.md"
    assert pred_path.parent == tmp_path

    # Decision report path
    dec_path = build_backtest_report_path("decisions", "2023-24", "all", 1, 10, directory=tmp_path, version="0.7.0")
    assert dec_path.name == "0.7.0_backtest_decisions_2023-24_all_1_10.md"
    assert dec_path.parent == tmp_path


def test_format_decision_report_single_and_multiple() -> None:
    from fpl_manager.backtest.engine import GameweekDecisionResult, SimulationResult
    from fpl_manager.backtest.reporting import format_decision_report

    sim1 = SimulationResult(
        strategy_name="No-Transfer Baseline",
        season="2023-24",
        start_gw=1,
        end_gw=2,
        gameweeks_played=2,
        total_net_points=100,
        total_gross_points=100,
        total_hits=0,
        total_transfers=0,
        final_bank_tenths=5,
        history=(
            GameweekDecisionResult(1, (), (), (), (), (), 1, 2, 50.0, 0, 50, 50, (), False),
            GameweekDecisionResult(2, (), (), (), (), (), 1, 2, 50.0, 0, 50, 50, (), False),
        ),
    )
    sim2 = SimulationResult(
        strategy_name="Optimizer",
        season="2023-24",
        start_gw=1,
        end_gw=2,
        gameweeks_played=2,
        total_net_points=115,
        total_gross_points=119,
        total_hits=4,
        total_transfers=2,
        final_bank_tenths=2,
        history=(
            GameweekDecisionResult(1, (), (), (), (), (), 3, 4, 55.0, 0, 55, 55, (), False),
            GameweekDecisionResult(2, (), ((1, 2),), (), (), (), 3, 4, 60.0, 4, 64, 60, (), False),
        ),
    )

    # Multi-strategy report
    multi_report = format_decision_report([sim1, sim2], season="2023-24", start_gw=1, end_gw=2)
    assert "# Historical Decision Simulation Backtest Report: Season 2023-24 (GW 1-2)" in multi_report
    assert "Optimizer" in multi_report
    assert "No-Transfer Baseline" in multi_report
    assert "Head-to-Head Comparisons" in multi_report
    assert "Gameweek-by-Gameweek Progression" in multi_report


def test_run_prediction_backtest_save_report(tmp_path: Path) -> None:
    season_dir = tmp_path / "mock_season"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=3, num_teams=4, players_per_team=5)
    custom_report = tmp_path / "custom_pred_report.md"

    metrics, _ = run_prediction_backtest(
        season_dir,
        start_gw=1,
        end_gw=2,
        save_report=True,
        output_path=custom_report,
    )

    assert custom_report.exists()
    assert metrics.get("saved_report_path") == str(custom_report)
    content = custom_report.read_text(encoding="utf-8")
    assert "Historical Prediction Backtest Report" in content
    assert "Overall Expected Points" in content


def test_run_decision_backtest_save_report(tmp_path: Path) -> None:
    from fpl_manager.backtest.engine import run_decision_backtest, run_sequential_simulation
    from fpl_manager.backtest.strategies import NoTransferStrategy

    season_dir = tmp_path / "mock_season"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=3, num_teams=6, players_per_team=5)

    # 1. run_sequential_simulation with save_report
    sim_report = tmp_path / "sim_report.md"
    sim = run_sequential_simulation(
        season_dir,
        NoTransferStrategy(),
        start_gw=1,
        end_gw=2,
        save_report=True,
        output_path=sim_report,
    )
    assert sim_report.exists()
    assert sim.saved_report_path == str(sim_report)
    sim_text = sim_report.read_text(encoding="utf-8")
    assert "Historical Decision Simulation Backtest Report" in sim_text

    # 2. run_decision_backtest with save_report
    dec_report = tmp_path / "dec_report.md"
    sims = run_decision_backtest(
        season_dir,
        strategy="notransfer",
        start_gw=1,
        end_gw=2,
        save_report=True,
        output_path=dec_report,
    )
    assert dec_report.exists()
    assert len(sims) == 1
    assert sims[0].saved_report_path == str(dec_report)
    dec_text = dec_report.read_text(encoding="utf-8")
    assert "Historical Decision Simulation Backtest Report" in dec_text


def test_cli_save_report_flags(capsys) -> None:
    from fpl_manager import __version__
    from fpl_manager.cli import main

    # 1. Prediction CLI with --save-report
    main(["backtest-predictions", "--season", "2023-24", "--start-gw", "1", "--end-gw", "2", "--save-report"])
    captured = capsys.readouterr()
    assert "Prediction backtest report saved to:" in captured.out
    pred_path_str = captured.out.strip().split("saved to: ")[1].split("\n")[0].strip()
    pred_file = Path(pred_path_str)
    assert pred_file.exists()
    assert f"{__version__}_backtest_predictions" in pred_file.name
    assert "2023-24_1_2.md" in pred_file.name

    # Clean up generated file
    if pred_file.exists():
        pred_file.unlink()

    # 2. Decision CLI with --save-report
    main(["backtest-decisions", "--season", "2023-24", "--strategy", "notransfer", "--start-gw", "1", "--end-gw", "2", "--save-report"])
    captured = capsys.readouterr()
    assert "Decision backtest report saved to:" in captured.out
    dec_path_str = captured.out.strip().split("saved to: ")[1].split("\n")[0].strip()
    dec_file = Path(dec_path_str)
    assert dec_file.exists()
    assert f"{__version__}_backtest_decisions" in dec_file.name
    assert "2023-24_notransfer_1_2.md" in dec_file.name

    # Clean up generated file
    if dec_file.exists():
        dec_file.unlink()


