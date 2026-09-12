"""Unit and integration tests for participation diagnostics and prediction model (V0.8.1 & V0.8.2)."""

from pathlib import Path
import pytest

from fpl_manager.backtest.participation import (
    ParticipationDiagnosticRecord,
    classify_participation_error,
    diagnose_participation_records,
    format_participation_report,
    run_participation_diagnostics,
)
from fpl_manager.historical.ingestion import generate_mock_season
from fpl_manager.models import Position
from fpl_manager.participation import (
    ParticipationPrediction,
    get_position_price_priors,
    predict_player_participation,
)


def test_classify_participation_error_high_conf_false_positive() -> None:
    # High predicted start and minutes, but 0 minutes actually played
    cat, root_cause, penalty = classify_participation_error(
        predicted_start_prob=0.92,
        predicted_xm=78.0,
        predicted_xp=5.5,
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
    assert cat == "HIGH_CONFIDENCE_FALSE_POSITIVE"
    assert root_cause == "TACTICAL_BENCH"
    assert penalty == 5.5


def test_classify_participation_error_injury_doubt() -> None:
    cat, root_cause, penalty = classify_participation_error(
        predicted_start_prob=0.40,
        predicted_xm=30.0,
        predicted_xp=2.0,
        status="d",
        chance_of_playing=50,
        actual_started=False,
        actual_minutes=0,
        actual_points=0,
        consecutive_zero_mins=0,
        starts_last_3=1,
        days_since_prev_fixture=6.0,
        matches_last_7_days=1,
    )
    assert root_cause == "INJURY_FITNESS_DOUBT"


def test_classify_participation_error_role_loss() -> None:
    cat, root_cause, penalty = classify_participation_error(
        predicted_start_prob=0.75,
        predicted_xm=65.0,
        predicted_xp=4.0,
        status="a",
        chance_of_playing=None,
        actual_started=False,
        actual_minutes=0,
        actual_points=0,
        consecutive_zero_mins=3,  # Missed last 3 games
        starts_last_3=0,
        days_since_prev_fixture=7.0,
        matches_last_7_days=1,
    )
    assert cat == "HIGH_CONFIDENCE_FALSE_POSITIVE"
    assert root_cause == "ROLE_LOSS"


def test_classify_participation_error_congestion_rotation() -> None:
    cat, root_cause, penalty = classify_participation_error(
        predicted_start_prob=0.72,
        predicted_xm=62.0,
        predicted_xp=3.8,
        status="a",
        chance_of_playing=None,
        actual_started=False,
        actual_minutes=0,
        actual_points=0,
        consecutive_zero_mins=0,
        starts_last_3=3,
        days_since_prev_fixture=2.5,  # Short turnaround
        matches_last_7_days=2,
    )
    assert cat == "HIGH_CONFIDENCE_FALSE_POSITIVE"
    assert root_cause == "CONGESTION_ROTATION"


def test_diagnose_participation_records_aggregation() -> None:
    records = [
        ParticipationDiagnosticRecord(
            season="2023-24",
            gameweek=1,
            player_id=1,
            web_name="Haaland",
            team_id=1,
            position=Position.FORWARD,
            price_tenths=140,
            status="a",
            chance_of_playing=None,
            predicted_availability=1.0,
            predicted_start_prob=0.95,
            predicted_expected_minutes=85.0,
            predicted_xp=7.5,
            actual_started=True,
            actual_minutes=90,
            actual_points=13,
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
            error_category="ACCURATE",
            root_cause="GENUINE_MODEL_MISS",
            decision_penalty=0.0,
        ),
        ParticipationDiagnosticRecord(
            season="2023-24",
            gameweek=1,
            player_id=2,
            web_name="Kane",
            team_id=2,
            position=Position.FORWARD,
            price_tenths=125,
            status="a",
            chance_of_playing=None,
            predicted_availability=1.0,
            predicted_start_prob=0.92,
            predicted_expected_minutes=80.0,
            predicted_xp=6.0,
            actual_started=False,
            actual_minutes=0,
            actual_points=0,
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
            fdr=3,
            is_home=True,
            error_category="HIGH_CONFIDENCE_FALSE_POSITIVE",
            root_cause="TACTICAL_BENCH",
            decision_penalty=6.0,
        ),
    ]

    res = diagnose_participation_records(records)
    assert res["total_records"] == 2
    assert res["active_players_count"] == 1
    assert res["zero_minute_count"] == 1
    assert res["false_positives"]["count"] == 1
    assert res["decision_impact"]["total_penalty_points"] == 6.0

    report = format_participation_report(res, season="2023-24", gameweek_range="1-1")
    assert "# Participation Error Diagnostics" in report
    assert "High-Confidence False Positives" in report
    assert "Kane" in report


def test_predict_player_participation_nailed_starter() -> None:
    pred = predict_player_participation(
        status="a",
        chance_of_playing_next_round=None,
        season_starts=10,
        season_minutes=900,
        finished_matches=10,
        starts_last_3=3,
        starts_last_5=5,
        minutes_last_3=270,
        minutes_last_5=450,
        consecutive_zero_mins=0,
        price_tenths=130,
        position=Position.FORWARD,
    )
    assert pred.p_start >= 0.85
    assert pred.expected_minutes >= 70.0
    assert pred.role_category == "nailed_starter"
    assert pred.prob_60_plus >= 0.70


def test_predict_player_participation_consecutive_zero_discount() -> None:
    # Regular starter who has missed last 3 matches (e.g. AFCON, unlisted injury)
    pred_normal = predict_player_participation(
        status="a",
        season_starts=15,
        season_minutes=1350,
        finished_matches=18,
        starts_last_3=3,
        consecutive_zero_mins=0,
        price_tenths=130,
        position=Position.MIDFIELDER,
    )

    pred_benched = predict_player_participation(
        status="a",
        season_starts=15,
        season_minutes=1350,
        finished_matches=18,
        starts_last_3=0,
        consecutive_zero_mins=3,
        price_tenths=130,
        position=Position.MIDFIELDER,
    )

    assert pred_benched.p_start < pred_normal.p_start * 0.30
    assert pred_benched.expected_minutes < pred_normal.expected_minutes * 0.40
    assert pred_benched.consecutive_zero_discount_applied > 0.0


def test_predict_player_participation_congestion_discount() -> None:
    # Fullback with short turnaround
    pred_rested = predict_player_participation(
        status="a",
        season_starts=10,
        season_minutes=900,
        finished_matches=10,
        starts_last_3=3,
        price_tenths=60,
        position=Position.DEFENDER,
        days_since_prev_fixture=7.0,
        matches_last_7_days=1,
    )

    pred_congested = predict_player_participation(
        status="a",
        season_starts=10,
        season_minutes=900,
        finished_matches=10,
        starts_last_3=3,
        price_tenths=60,
        position=Position.DEFENDER,
        days_since_prev_fixture=2.5,  # Short turnaround
        matches_last_7_days=2,
    )

    assert pred_congested.p_start < pred_rested.p_start
    assert pred_congested.congestion_discount_applied > 0.0


def test_run_participation_diagnostics_integration(tmp_path: Path) -> None:
    season_dir = tmp_path / "mock_season"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=3, num_teams=4, players_per_team=5)

    diagnostics, records = run_participation_diagnostics(
        season_dir=season_dir,
        start_gw=1,
        end_gw=2,
        save_report=True,
    )

    assert diagnostics["total_records"] > 0
    assert "saved_report_path" in diagnostics
    assert Path(diagnostics["saved_report_path"]).exists()
