"""Unit and integration tests for V0.9 Phase 4 (Calibration) and Phase 5 (Rotation Regimes)."""

import pytest

from fpl_manager.calibration import (
    IsotonicCalibrator,
    PlattCalibrator,
    compute_brier_score,
    compute_log_loss,
    compute_reliability_curve,
)
from fpl_manager.historical.models import Position
from fpl_manager.learned_participation import (
    HierarchicalParticipationModel,
    predict_player_participation_v09,
)
from fpl_manager.regimes import (
    PlayerRotationFingerprint,
    RegimeTransition,
    RoleRegime,
    compute_player_rotation_fingerprint,
    detect_role_regime,
)


# --- Phase 4 Calibration Tests ---

def test_compute_brier_score() -> None:
    assert compute_brier_score([], []) == 0.0
    assert compute_brier_score([1.0, 1.0], [1, 1]) == 0.0
    assert compute_brier_score([0.0, 0.0], [1, 1]) == 1.0
    assert compute_brier_score([0.5, 0.5], [1, 0]) == 0.25


def test_compute_log_loss() -> None:
    assert compute_log_loss([], []) == 0.0
    # Perfect predictions give virtually 0 log loss
    loss_perfect = compute_log_loss([0.9999, 0.0001], [1, 0])
    assert loss_perfect < 0.01

    # Uncertain predictions (0.5 for all) give log(2) ~ 0.6931
    loss_uncertain = compute_log_loss([0.5, 0.5], [1, 0])
    assert loss_uncertain == pytest.approx(0.6931, abs=1e-3)


def test_compute_reliability_curve() -> None:
    empty_curve = compute_reliability_curve([], [])
    assert empty_curve.total_samples == 0
    assert empty_curve.buckets == []

    preds = [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]
    acts = [0, 0, 0, 0, 0, 1, 1, 1, 1, 1]

    curve = compute_reliability_curve(preds, acts, n_bins=10)
    assert curve.total_samples == 10
    assert len(curve.buckets) == 10
    assert sum(b.count for b in curve.buckets) == 10
    assert 0.0 <= curve.expected_calibration_error <= 1.0
    assert 0.0 <= curve.maximum_calibration_error <= 1.0
    assert curve.brier_score >= 0.0
    assert curve.log_loss >= 0.0

    d = curve.to_dict()
    assert d["total_samples"] == 10
    assert "buckets" in d
    assert len(d["buckets"]) == 10


def test_platt_calibrator() -> None:
    cal = PlattCalibrator(a=1.0, b=0.0)
    # Calibrate preserves range [0, 1]
    assert 0.0 <= cal.calibrate(0.1) <= 1.0
    assert 0.0 <= cal.calibrate(0.9) <= 1.0
    assert cal.calibrate(0.1) < cal.calibrate(0.9)

    # Extreme bounds
    assert cal.calibrate(0.0) == pytest.approx(0.0, abs=1e-3)
    assert cal.calibrate(1.0) == pytest.approx(1.0, abs=1e-3)

    # Serialization
    saved = cal.to_dict()
    restored = PlattCalibrator.from_dict(saved)
    assert restored.a == cal.a
    assert restored.b == cal.b
    assert restored.calibrate(0.5) == cal.calibrate(0.5)

    # Test Platt fit
    uncalibrated_probs = [0.2, 0.3, 0.4, 0.7, 0.8, 0.9]
    actual_labels = [0, 0, 0, 1, 1, 1]
    fitted = PlattCalibrator.fit(uncalibrated_probs, actual_labels, epochs=100, learning_rate=0.1)
    assert fitted.calibrate(0.2) < fitted.calibrate(0.8)


def test_isotonic_calibrator_pava() -> None:
    # Training pairs where raw probability is not strictly monotonic with label
    raw_probs = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    targets = [0, 1, 0, 1, 1, 0, 1, 1]

    iso = IsotonicCalibrator.fit(raw_probs, targets)
    assert len(iso.thresholds) >= 2
    assert len(iso.calibrated_values) == len(iso.thresholds)

    # Test monotonicity of calibrated_values
    for i in range(len(iso.calibrated_values) - 1):
        assert iso.calibrated_values[i] <= iso.calibrated_values[i + 1]

    # Test calibrate interpolation and monotonicity
    val1 = iso.calibrate(0.15)
    val2 = iso.calibrate(0.45)
    val3 = iso.calibrate(0.75)
    assert 0.0 <= val1 <= val2 <= val3 <= 1.0

    # Boundary handling
    assert 0.0 <= iso.calibrate(0.0) <= 1.0
    assert 0.0 <= iso.calibrate(1.0) <= 1.0

    # Serialization
    saved = iso.to_dict()
    restored = IsotonicCalibrator.from_dict(saved)
    assert restored.calibrate(0.5) == iso.calibrate(0.5)


# --- Phase 5 Rotation Regimes Tests ---

def test_detect_role_regime_unavailable() -> None:
    state_injured = detect_role_regime(
        status="i",
        chance_of_playing=0,
        season_starts=10,
        finished_matches=10,
        starts_last_3=3,
        starts_last_5=5,
        minutes_last_3=270,
        consecutive_zero_mins=0,
    )
    assert state_injured.regime == RoleRegime.UNAVAILABLE
    assert state_injured.start_probability_adjustment == -1.0


def test_detect_role_regime_returning_from_injury() -> None:
    state_doubt = detect_role_regime(
        status="d",
        chance_of_playing=75,
        season_starts=8,
        finished_matches=10,
        starts_last_3=1,
        starts_last_5=2,
        minutes_last_3=90,
        consecutive_zero_mins=1,
    )
    assert state_doubt.regime == RoleRegime.RETURNING_FROM_INJURY
    assert state_doubt.transition == RegimeTransition.RETURNING
    assert state_doubt.recency_multiplier > 1.0
    assert state_doubt.start_probability_adjustment < 0.0


def test_detect_role_regime_demoted_to_bench() -> None:
    # Was starter for 8 of 10 matches, but was benched for last 2 games
    state_demoted = detect_role_regime(
        status="a",
        chance_of_playing=None,
        season_starts=8,
        finished_matches=10,
        starts_last_3=1,
        starts_last_5=3,
        minutes_last_3=45,
        consecutive_zero_mins=2,
    )
    assert state_demoted.regime == RoleRegime.DEMOTED_TO_BENCH
    assert state_demoted.transition == RegimeTransition.DEMOTED
    assert state_demoted.start_probability_adjustment <= -0.25
    assert state_demoted.recency_multiplier >= 1.5


def test_detect_role_regime_emerging_starter() -> None:
    # Was fringe earlier (season_starts 1 out of 6), but started last 2 consecutive games with heavy minutes
    state_promoted = detect_role_regime(
        status="a",
        chance_of_playing=None,
        season_starts=2,
        finished_matches=6,
        starts_last_3=2,
        starts_last_5=2,
        minutes_last_3=180,
        consecutive_zero_mins=0,
    )
    assert state_promoted.regime == RoleRegime.EMERGING_STARTER
    assert state_promoted.transition == RegimeTransition.PROMOTED
    assert state_promoted.start_probability_adjustment > 0.0


def test_detect_role_regime_fringe_reserve() -> None:
    state_fringe = detect_role_regime(
        status="a",
        chance_of_playing=None,
        season_starts=0,
        finished_matches=8,
        starts_last_3=0,
        starts_last_5=0,
        minutes_last_3=0,
        consecutive_zero_mins=5,
    )
    assert state_fringe.regime == RoleRegime.FRINGE_RESERVE
    assert state_fringe.transition == RegimeTransition.STABLE
    assert state_fringe.start_probability_adjustment < 0.0


def test_detect_role_regime_nailed_and_regular() -> None:
    state_nailed = detect_role_regime(
        status="a",
        chance_of_playing=None,
        season_starts=10,
        finished_matches=10,
        starts_last_3=3,
        starts_last_5=5,
        minutes_last_3=270,
        consecutive_zero_mins=0,
    )
    assert state_nailed.regime == RoleRegime.NAILED_STARTER
    assert state_nailed.transition == RegimeTransition.STABLE

    state_regular = detect_role_regime(
        status="a",
        chance_of_playing=None,
        season_starts=7,
        finished_matches=10,
        starts_last_3=2,
        starts_last_5=3,
        minutes_last_3=160,
        consecutive_zero_mins=0,
    )
    assert state_regular.regime == RoleRegime.REGULAR_STARTER
    assert state_regular.transition == RegimeTransition.STABLE


def test_compute_player_rotation_fingerprint() -> None:
    # Goalkeeper baseline: minimal rotation regardless of turnaround
    gk_fp = compute_player_rotation_fingerprint(
        normal_rest_starts=10,
        normal_rest_matches=10,
        short_rest_starts=4,
        short_rest_matches=4,
        position=Position.GOALKEEPER,
    )
    assert gk_fp.congestion_fatigue_penalty == pytest.approx(0.0, abs=0.01)

    # Midfielder with high sensitivity to short turnaround rest
    mid_fp = compute_player_rotation_fingerprint(
        normal_rest_starts=10,
        normal_rest_matches=10,
        short_rest_starts=1,
        short_rest_matches=4,
        position=Position.MIDFIELDER,
    )
    assert mid_fp.normal_rest_start_rate > mid_fp.short_rest_start_rate
    assert mid_fp.congestion_fatigue_penalty > 0.30

    # Bayesian shrinkage with 0 samples reverts to prior
    empty_fp = compute_player_rotation_fingerprint(
        normal_rest_starts=0,
        normal_rest_matches=0,
        short_rest_starts=0,
        short_rest_matches=0,
        position=Position.FORWARD,
    )
    assert empty_fp.normal_rest_start_rate == 0.75
    assert empty_fp.short_rest_start_rate == 0.62


# --- Model Integration with Calibration and Regimes ---

def test_hierarchical_participation_model_calibration_and_regimes_toggle() -> None:
    model_default = HierarchicalParticipationModel.default()
    assert model_default.use_calibration is True
    assert model_default.use_regimes is True

    # Prediction with calibration & regimes
    pred_full = model_default.predict(
        status="a",
        season_starts=8,
        finished_matches=10,
        starts_last_3=1,
        starts_last_5=3,
        minutes_last_3=45,
        consecutive_zero_mins=2,
        price_tenths=80,
        position=Position.MIDFIELDER,
    )

    # Player has been demoted to bench
    assert pred_full.role_category == "demoted_to_bench"
    assert pred_full.p_start < 0.50

    # Test turning off calibration and regimes
    model_raw = HierarchicalParticipationModel.default()
    model_raw.use_calibration = False
    model_raw.use_regimes = False

    pred_raw = model_raw.predict(
        status="a",
        season_starts=8,
        finished_matches=10,
        starts_last_3=1,
        starts_last_5=3,
        minutes_last_3=45,
        consecutive_zero_mins=2,
        price_tenths=80,
        position=Position.MIDFIELDER,
    )

    # Without regimes demotion adjustment, p_start is noticeably higher
    assert pred_raw.p_start > pred_full.p_start
