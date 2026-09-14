"""Unit and integration tests for V0.9 Phase 1 residual-error dataset and taxonomy."""

import json
from pathlib import Path
import pytest

from fpl_manager.backtest.residual_dataset import (
    ResidualRecord,
    V09_ERROR_TAXONOMY,
    build_residual_dataset,
    classify_v09_residual_error,
    diagnose_residual_dataset,
    export_residual_dataset_csv,
    export_residual_dataset_json,
    format_residual_dataset_report,
)
from fpl_manager.historical.ingestion import generate_mock_season
from fpl_manager.models import Position


def test_classify_v09_error_no_appearance() -> None:
    # Player with injury/doubt who logs 0 minutes
    err_cat, res_class, penalty = classify_v09_residual_error(
        p_start=0.30,
        p_sub=0.10,
        p_play=0.40,
        expected_minutes=25.0,
        predicted_xp=2.0,
        status="d",
        chance_of_playing=25,
        actual_started=False,
        actual_minutes=0,
        actual_points=0,
        consecutive_zero_mins=0,
        starts_last_3=1,
        days_since_prev_fixture=7.0,
        matches_last_7_days=1,
    )
    assert res_class == "NO_APPEARANCE"


def test_classify_v09_error_benched() -> None:
    # Fit player, but left on bench with 0 minutes
    err_cat, res_class, penalty = classify_v09_residual_error(
        p_start=0.50,
        p_sub=0.20,
        p_play=0.70,
        expected_minutes=45.0,
        predicted_xp=3.2,
        status="a",
        chance_of_playing=None,
        actual_started=False,
        actual_minutes=0,
        actual_points=0,
        consecutive_zero_mins=0,
        starts_last_3=1,
        days_since_prev_fixture=7.0,
        matches_last_7_days=1,
    )
    assert res_class == "BENCHED"


def test_classify_v09_error_sub_appearance() -> None:
    # Player did not start, brought on as sub for 22 mins
    err_cat, res_class, penalty = classify_v09_residual_error(
        p_start=0.75,
        p_sub=0.15,
        p_play=0.90,
        expected_minutes=68.0,
        predicted_xp=4.8,
        status="a",
        chance_of_playing=None,
        actual_started=False,
        actual_minutes=22,
        actual_points=1,
        consecutive_zero_mins=0,
        starts_last_3=3,
        days_since_prev_fixture=7.0,
        matches_last_7_days=1,
    )
    assert err_cat == "FALSE_STARTER"
    assert res_class == "SUB_APPEARANCE"
    assert penalty > 0


def test_classify_v09_error_early_substitution() -> None:
    # Player started, but substituted early at minute 42
    err_cat, res_class, penalty = classify_v09_residual_error(
        p_start=0.90,
        p_sub=0.05,
        p_play=0.95,
        expected_minutes=80.0,
        predicted_xp=5.5,
        status="a",
        chance_of_playing=None,
        actual_started=True,
        actual_minutes=42,
        actual_points=1,
        consecutive_zero_mins=0,
        starts_last_3=3,
        days_since_prev_fixture=7.0,
        matches_last_7_days=1,
    )
    assert res_class == "EARLY_SUBSTITUTION"


def test_classify_v09_error_role_loss() -> None:
    # Player missed previous 3 games, losing role
    err_cat, res_class, penalty = classify_v09_residual_error(
        p_start=0.60,
        p_sub=0.10,
        p_play=0.70,
        expected_minutes=50.0,
        predicted_xp=3.0,
        status="a",
        chance_of_playing=None,
        actual_started=False,
        actual_minutes=0,
        actual_points=0,
        consecutive_zero_mins=3,
        starts_last_3=0,
        days_since_prev_fixture=7.0,
        matches_last_7_days=1,
    )
    assert res_class == "ROLE_LOSS"


def test_classify_v09_error_return_from_injury() -> None:
    # Player returning from injury doubt
    err_cat, res_class, penalty = classify_v09_residual_error(
        p_start=0.20,
        p_sub=0.30,
        p_play=0.50,
        expected_minutes=25.0,
        predicted_xp=2.0,
        status="d",
        chance_of_playing=50,
        actual_started=True,
        actual_minutes=60,
        actual_points=6,
        consecutive_zero_mins=2,
        starts_last_3=0,
        days_since_prev_fixture=7.0,
        matches_last_7_days=1,
    )
    assert res_class == "RETURN_FROM_INJURY"


def test_classify_v09_error_tactical_change() -> None:
    # Regular starter dropped unexpectedly
    err_cat, res_class, penalty = classify_v09_residual_error(
        p_start=0.92,
        p_sub=0.05,
        p_play=0.97,
        expected_minutes=85.0,
        predicted_xp=6.2,
        status="a",
        chance_of_playing=None,
        actual_started=False,
        actual_minutes=0,
        actual_points=0,
        consecutive_zero_mins=0,
        starts_last_3=3,
        days_since_prev_fixture=7.0,
        matches_last_7_days=1,
    )
    assert err_cat == "HIGH_CONFIDENCE_FALSE_POSITIVE"
    assert res_class == "TACTICAL_CHANGE"
    assert penalty == 6.2


def test_classify_v09_error_congestion() -> None:
    # Short turnaround causes player to be rested
    err_cat, res_class, penalty = classify_v09_residual_error(
        p_start=0.75,
        p_sub=0.10,
        p_play=0.85,
        expected_minutes=65.0,
        predicted_xp=4.5,
        status="a",
        chance_of_playing=None,
        actual_started=False,
        actual_minutes=0,
        actual_points=0,
        consecutive_zero_mins=0,
        starts_last_3=2,
        days_since_prev_fixture=2.5,
        matches_last_7_days=2,
    )
    assert res_class == "CONGESTION"


def test_classify_v09_error_accurate() -> None:
    # Prediction within 15 minutes of actual outcome
    err_cat, res_class, penalty = classify_v09_residual_error(
        p_start=0.95,
        p_sub=0.02,
        p_play=0.97,
        expected_minutes=85.0,
        predicted_xp=7.0,
        status="a",
        chance_of_playing=None,
        actual_started=True,
        actual_minutes=90,
        actual_points=8,
        consecutive_zero_mins=0,
        starts_last_3=3,
        days_since_prev_fixture=7.0,
        matches_last_7_days=1,
    )
    assert err_cat == "ACCURATE"
    assert res_class == "ACCURATE"
    assert penalty == 0.0


def test_diagnose_and_report_residual_dataset(tmp_path: Path) -> None:
    # Create sample ResidualRecords
    r1 = ResidualRecord(
        season="2023-24",
        gameweek=1,
        player_id=1,
        web_name="Saka",
        team_id=1,
        position=Position.MIDFIELDER,
        price_tenths=85,
        status="a",
        chance_of_playing=None,
        p_start=0.95,
        p_sub=0.02,
        p_play=0.97,
        expected_minutes=85.0,
        predicted_xp=7.0,
        actual_minutes=90,
        actual_started=True,
        actual_points=10,
        historical_starts=0,
        historical_minutes=0,
        starts_last_3=0,
        starts_last_5=0,
        minutes_last_3=0,
        minutes_last_5=0,
        consecutive_zero_mins=0,
        days_since_prev_fixture=None,
        matches_last_7_days=0,
        matches_last_14_days=0,
        fdr=2,
        is_home=True,
        error_category="ACCURATE",
        residual_classification="ACCURATE",
        minute_error=-5.0,
        absolute_minute_error=5.0,
        decision_penalty=0.0,
    )

    r2 = ResidualRecord(
        season="2023-24",
        gameweek=1,
        player_id=2,
        web_name="De Bruyne",
        team_id=2,
        position=Position.MIDFIELDER,
        price_tenths=105,
        status="a",
        chance_of_playing=None,
        p_start=0.92,
        p_sub=0.03,
        p_play=0.95,
        expected_minutes=80.0,
        predicted_xp=6.5,
        actual_minutes=23,
        actual_started=True,
        actual_points=1,
        historical_starts=0,
        historical_minutes=0,
        starts_last_3=0,
        starts_last_5=0,
        minutes_last_3=0,
        minutes_last_5=0,
        consecutive_zero_mins=0,
        days_since_prev_fixture=None,
        matches_last_7_days=0,
        matches_last_14_days=0,
        fdr=2,
        is_home=False,
        error_category="MODERATE_MISS",
        residual_classification="EARLY_SUBSTITUTION",
        minute_error=57.0,
        absolute_minute_error=57.0,
        decision_penalty=0.0,
    )

    records = [r1, r2]
    summary = diagnose_residual_dataset(records)
    assert summary["total_records"] == 2
    assert summary["accurate_records"] == 1
    assert summary["non_accurate_records"] == 1
    assert summary["residual_taxonomy"]["EARLY_SUBSTITUTION"]["count"] == 1
    assert summary["brier_start"] >= 0.0

    report = format_residual_dataset_report(summary, season="2023-24", gameweek_range="GW1-1")
    assert "# V0.9 Residual-Error Dataset" in report
    assert "EARLY_SUBSTITUTION" in report

    # Test export JSON
    json_path = tmp_path / "residuals.json"
    export_residual_dataset_json(records, json_path)
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert data[0]["web_name"] == "Saka"

    # Test export CSV
    csv_path = tmp_path / "residuals.csv"
    export_residual_dataset_csv(records, csv_path)
    assert csv_path.exists()
    content = csv_path.read_text(encoding="utf-8")
    assert "De Bruyne" in content


def test_build_residual_dataset_on_mock_season(tmp_path: Path) -> None:
    season_dir = tmp_path / "mock_2023_24"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=3, num_teams=4, players_per_team=5)

    records = build_residual_dataset(season_dir, start_gw=1, end_gw=3)
    assert len(records) > 0
    # Check all records have valid taxonomy and probability attributes
    for r in records:
        assert r.residual_classification in V09_ERROR_TAXONOMY or r.residual_classification == "ACCURATE"
        assert 0.0 <= r.p_start <= 1.0
        assert 0.0 <= r.p_play <= 1.0
        assert r.expected_minutes >= 0.0
