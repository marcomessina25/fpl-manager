"""Learned hierarchical participation and conditional minutes engine for V0.9 (Phases 2 & 3).

Implements:
- Phase 2: Structured probability model decomposing participation into:
    P(no appearance), P(appearance)
    P(start), P(sub | not start)
    E[M | start], E[M | sub]
    E[M] = P(start) * E[M | start] + (1 - P(start)) * P(sub | not start) * E[M | sub]
- Phase 3: Pure-Python, deterministic learned statistical classifier estimating
    P(start | pre-deadline features) and P(sub | not start).
- Zero external dependencies: operates purely on the standard library.
- Zero-leakage temporal point-in-time discipline.
"""

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any

from .calibration import PlattCalibrator, IsotonicCalibrator
from .historical.models import Position
from .participation import ParticipationPrediction, get_position_price_priors
from .regimes import RoleRegime, RegimeTransition, detect_role_regime


def _safe_sigmoid(z: float) -> float:
    """Clamped numerically-stable sigmoid activation function."""
    if z >= 35.0:
        return 1.0
    if z <= -35.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


@dataclass
class LogisticModel:
    """Pure-Python regularized logistic regression model for binary probability estimation."""

    feature_names: list[str]
    weights: list[float]  # weights[0] is the intercept bias term
    l2_reg: float = 0.0005

    def predict_proba(self, features: list[float]) -> float:
        """Compute P(y = 1 | x) = sigmoid(w0 + w^T x)."""
        # features should include the leading 1.0 bias term or match len(weights)
        if len(features) == len(self.weights) - 1:
            z = self.weights[0] + sum(w * x for w, x in zip(self.weights[1:], features))
        elif len(features) == len(self.weights):
            z = sum(w * x for w, x in zip(self.weights, features))
        else:
            raise ValueError(f"Feature length {len(features)} does not match model weights {len(self.weights)}")
        return _safe_sigmoid(z)

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_names": self.feature_names,
            "weights": [round(w, 6) for w in self.weights],
            "l2_reg": self.l2_reg,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LogisticModel":
        return cls(
            feature_names=data["feature_names"],
            weights=data["weights"],
            l2_reg=data.get("l2_reg", 0.0005),
        )

    @classmethod
    def fit(
        cls,
        feature_names: list[str],
        X: list[list[float]],
        y: list[int],
        epochs: int = 350,
        learning_rate: float = 0.15,
        l2_reg: float = 0.0005,
    ) -> "LogisticModel":
        """Fit regularized logistic regression on sample data using gradient descent."""
        if not X or not y or len(X) != len(y):
            raise ValueError("Invalid training dataset for logistic regression.")

        n_features = len(X[0])
        weights = [0.0] * n_features
        N = len(X)

        for _ in range(epochs):
            grad = [0.0] * n_features
            for i in range(N):
                xi = X[i]
                yi = y[i]
                z = sum(w * x for w, x in zip(weights, xi))
                p = _safe_sigmoid(z)
                err = p - yi
                for j in range(n_features):
                    grad[j] += err * xi[j]

            # Update weights with L2 penalty on non-intercept features
            for j in range(n_features):
                penalty = l2_reg * weights[j] if j > 0 else 0.0
                weights[j] -= learning_rate * ((grad[j] / N) + penalty)

        return cls(feature_names=feature_names, weights=weights, l2_reg=l2_reg)


# Calibrated Baseline Weights derived from 48,187 multi-season observations (2021-22 & 2022-23)
DEFAULT_START_FEATURE_NAMES = [
    "bias",
    "prior_p_start",
    "starts_last_3_rate",
    "starts_last_5_rate",
    "minutes_last_3_norm",
    "consecutive_zero_penalty",
    "short_rest_turnaround",
    "dense_schedule_7d",
    "is_gkp",
    "is_def",
    "is_mid",
    "is_fwd",
]

DEFAULT_START_WEIGHTS = [
    -1.12876,   # Intercept
    0.08209,    # Prior p_start weight
    1.43093,    # Starts in last 3 matches (strongest positive driver)
    1.25683,    # Starts in last 5 matches
    0.84800,    # Minutes in last 3 matches
    -1.77117,   # Consecutive zero minutes (decisive role loss penalty)
    -0.09817,   # Short rest turnaround (<= 3.2 days)
    -0.08910,   # Dense schedule (2+ matches in 7 days)
    -0.18918,   # GKP base adjustment
    -0.23106,   # DEF base adjustment
    -0.36808,   # MID base adjustment
    -0.31480,   # FWD base adjustment
]

DEFAULT_SUB_FEATURE_NAMES = [
    "bias",
    "is_gkp",
    "is_def",
    "is_mid",
    "is_fwd",
    "price_norm",
    "starts_last_3_rate",
    "consecutive_zero_penalty",
]

DEFAULT_SUB_WEIGHTS = [
    -0.18511,   # Intercept
    -0.45566,   # GKP rarely subbed on
    -0.19997,   # DEF less frequently subbed on
    0.27685,    # MID high frequency substitute appearances
    0.20379,    # FWD high frequency substitute appearances
    0.21990,    # Price tier: higher priced bench assets brought on as impact subs
    -0.07788,   # Recent starts
    -2.63668,   # Out-of-squad / inactive zero minutes penalty
]

DEFAULT_STARTERS_CONDITIONAL_MINUTES = {
    "GOALKEEPER": {"mean_minutes": 89.4, "prob_60_plus": 0.989},
    "DEFENDER": {"mean_minutes": 85.3, "prob_60_plus": 0.946},
    "MIDFIELDER": {"mean_minutes": 80.0, "prob_60_plus": 0.912},
    "FORWARD": {"mean_minutes": 79.4, "prob_60_plus": 0.921},
}

DEFAULT_SUBS_CONDITIONAL_MINUTES = {
    "GOALKEEPER": {"mean_minutes": 20.0},
    "DEFENDER": {"mean_minutes": 18.9},
    "MIDFIELDER": {"mean_minutes": 18.1},
    "FORWARD": {"mean_minutes": 17.0},
}

DEFAULT_ISOTONIC_THRESHOLDS = [
    0.0, 0.002, 0.041, 0.081, 0.098, 0.139, 0.141, 0.148, 0.16, 0.161,
    0.162, 0.163, 0.308, 0.318, 0.332, 0.334, 0.628, 0.631, 0.637, 0.666,
    0.693, 0.705, 0.726, 0.734, 0.87, 0.893, 0.898, 0.906, 0.927, 0.929,
    0.93, 0.935, 1.0,
]

DEFAULT_ISOTONIC_VALUES = [
    0.0, 0.0158, 0.0453, 0.0459, 0.0469, 0.0964, 0.1127, 0.1354, 0.1931, 0.2162,
    0.2174, 0.2326, 0.2452, 0.3148, 0.4645, 0.4762, 0.5144, 0.575, 0.5902, 0.6104,
    0.6303, 0.6444, 0.6722, 0.6829, 0.6974, 0.7387, 0.7723, 0.8161, 0.837, 0.8678,
    0.8689, 0.878, 0.8864,
]


@dataclass
class HierarchicalParticipationModel:
    """Structured hierarchical participation predictor (V0.9)."""

    model_start: LogisticModel
    model_sub: LogisticModel
    starters_conditional_minutes: dict[str, dict[str, float]] = field(
        default_factory=lambda: json.loads(json.dumps(DEFAULT_STARTERS_CONDITIONAL_MINUTES))
    )
    subs_conditional_minutes: dict[str, dict[str, float]] = field(
        default_factory=lambda: json.loads(json.dumps(DEFAULT_SUBS_CONDITIONAL_MINUTES))
    )
    calibrator_start: IsotonicCalibrator | PlattCalibrator | None = field(
        default_factory=lambda: IsotonicCalibrator(
            thresholds=list(DEFAULT_ISOTONIC_THRESHOLDS),
            calibrated_values=list(DEFAULT_ISOTONIC_VALUES),
        )
    )
    calibrator_sub: PlattCalibrator | None = None
    use_calibration: bool = True
    use_regimes: bool = True

    @classmethod
    def default(cls) -> "HierarchicalParticipationModel":
        """Instantiate pre-trained baseline model with calibrated historical weights."""
        m_start = LogisticModel(feature_names=DEFAULT_START_FEATURE_NAMES, weights=list(DEFAULT_START_WEIGHTS))
        m_sub = LogisticModel(feature_names=DEFAULT_SUB_FEATURE_NAMES, weights=list(DEFAULT_SUB_WEIGHTS))
        return cls(model_start=m_start, model_sub=m_sub)

    def extract_start_features(
        self,
        position: Position,
        price_tenths: int,
        starts_last_3: int,
        starts_last_5: int,
        minutes_last_3: int,
        consecutive_zero_mins: int,
        days_since_prev_fixture: float | None,
        matches_last_7_days: int,
        finished_matches: int = 3,
    ) -> list[float]:
        """Extract pre-deadline feature vector for P(start) with Bayesian shrinkage early in season."""
        prior_p_start, _ = get_position_price_priors(position, price_tenths)

        eff_finished = max(
            finished_matches,
            3 if (starts_last_3 > 0 or starts_last_5 > 0 or minutes_last_3 > 0 or consecutive_zero_mins > 0) else 0,
        )

        if eff_finished < 3:
            w = max(0.0, float(eff_finished)) / 3.0
            s3_rate = w * (starts_last_3 / max(1.0, float(eff_finished))) + (1.0 - w) * prior_p_start
            s5_rate = w * (max(starts_last_5, starts_last_3) / max(1.0, float(eff_finished))) + (1.0 - w) * prior_p_start
            m3_rate = w * min(1.0, minutes_last_3 / (90.0 * max(1.0, float(eff_finished)))) + (1.0 - w) * prior_p_start
            c_zero = w * (min(4.0, float(consecutive_zero_mins)) / 4.0)
        else:
            s3_rate = starts_last_3 / 3.0
            eff_starts_5 = max(starts_last_5, starts_last_3)
            s5_rate = eff_starts_5 / 5.0
            m3_rate = min(1.0, minutes_last_3 / 270.0)
            c_zero = min(4.0, float(consecutive_zero_mins)) / 4.0

        short_rest = 1.0 if (days_since_prev_fixture is not None and days_since_prev_fixture <= 3.2) else 0.0
        dense_7d = 1.0 if matches_last_7_days >= 2 else 0.0

        is_gkp = 1.0 if position == Position.GOALKEEPER else 0.0
        is_def = 1.0 if position == Position.DEFENDER else 0.0
        is_mid = 1.0 if position == Position.MIDFIELDER else 0.0
        is_fwd = 1.0 if position == Position.FORWARD else 0.0

        return [
            1.0,  # Bias term
            prior_p_start,
            s3_rate,
            s5_rate,
            m3_rate,
            c_zero,
            short_rest,
            dense_7d,
            is_gkp,
            is_def,
            is_mid,
            is_fwd,
        ]

    def extract_sub_features(
        self,
        position: Position,
        price_tenths: int,
        starts_last_3: int,
        consecutive_zero_mins: int,
        finished_matches: int = 3,
    ) -> list[float]:
        """Extract pre-deadline feature vector for P(sub | not start)."""
        prior_p_start, _ = get_position_price_priors(position, price_tenths)
        is_gkp = 1.0 if position == Position.GOALKEEPER else 0.0
        is_def = 1.0 if position == Position.DEFENDER else 0.0
        is_mid = 1.0 if position == Position.MIDFIELDER else 0.0
        is_fwd = 1.0 if position == Position.FORWARD else 0.0
        price_norm = min(140.0, float(price_tenths)) / 140.0

        eff_finished = max(
            finished_matches,
            3 if (starts_last_3 > 0 or consecutive_zero_mins > 0) else 0,
        )

        if eff_finished < 3:
            w = max(0.0, float(eff_finished)) / 3.0
            s3_rate = w * (starts_last_3 / max(1.0, float(eff_finished))) + (1.0 - w) * prior_p_start
            c_zero = w * (min(4.0, float(consecutive_zero_mins)) / 4.0)
        else:
            s3_rate = starts_last_3 / 3.0
            c_zero = min(4.0, float(consecutive_zero_mins)) / 4.0

        return [
            1.0,  # Bias term
            is_gkp,
            is_def,
            is_mid,
            is_fwd,
            price_norm,
            s3_rate,
            c_zero,
        ]

    def predict(
        self,
        status: str,
        chance_of_playing_next_round: int | None = None,
        season_starts: int = 0,
        season_minutes: int = 0,
        finished_matches: int = 0,
        starts_last_3: int = 0,
        starts_last_5: int = 0,
        minutes_last_3: int = 0,
        minutes_last_5: int = 0,
        consecutive_zero_mins: int = 0,
        price_tenths: int = 50,
        position: Position = Position.MIDFIELDER,
        days_since_prev_fixture: float | None = None,
        matches_last_7_days: int = 0,
        fdr: int = 3,
        is_home: bool = True,
    ) -> ParticipationPrediction:
        """Compute structured hierarchical participation prediction (100% deterministic)."""
        status_lower = status.lower()

        # 1. Base Availability Hard-Gate
        if status_lower in ("i", "s", "u"):
            return ParticipationPrediction(
                p_start=0.0,
                p_sub=0.0,
                p_play=0.0,
                prob_60_plus=0.0,
                mins_if_start=0.0,
                mins_if_sub=0.0,
                expected_minutes=0.0,
                role_category="unavailable",
                congestion_discount_applied=0.0,
                consecutive_zero_discount_applied=0.0,
            )

        if chance_of_playing_next_round is not None:
            try:
                avail_factor = max(0.0, min(100.0, float(chance_of_playing_next_round))) / 100.0
            except (ValueError, TypeError):
                avail_factor = 0.75 if status_lower == "d" else 1.0
        elif status_lower == "d":
            avail_factor = 0.50
        else:
            avail_factor = 1.0

        eff_season_starts = max(season_starts, starts_last_5, starts_last_3)
        eff_finished_matches = max(
            finished_matches,
            eff_season_starts,
            3 if (starts_last_3 > 0 or starts_last_5 > 0 or minutes_last_3 > 0 or consecutive_zero_mins > 0) else 0,
        )

        # 2. Dynamic Regime Detection & Role Transitions (Phase 5)
        regime_state = None
        if self.use_regimes:
            regime_state = detect_role_regime(
                status=status,
                chance_of_playing=chance_of_playing_next_round,
                season_starts=eff_season_starts,
                finished_matches=eff_finished_matches,
                starts_last_3=starts_last_3,
                starts_last_5=starts_last_5,
                minutes_last_3=minutes_last_3,
                consecutive_zero_mins=consecutive_zero_mins,
                price_tenths=price_tenths,
                position=position,
            )

        # 3. Estimate P(start) using learned statistical model
        x_start = self.extract_start_features(
            position=position,
            price_tenths=price_tenths,
            starts_last_3=starts_last_3,
            starts_last_5=starts_last_5,
            minutes_last_3=minutes_last_3,
            consecutive_zero_mins=consecutive_zero_mins,
            days_since_prev_fixture=days_since_prev_fixture,
            matches_last_7_days=matches_last_7_days,
            finished_matches=eff_finished_matches,
        )
        raw_p_start = self.model_start.predict_proba(x_start)

        # Apply dynamic regime transition adjustment
        if regime_state is not None and regime_state.start_probability_adjustment != 0.0:
            raw_p_start = max(0.0, min(1.0, raw_p_start + regime_state.start_probability_adjustment))

        # Probability Calibration (Phase 4: Isotonic Regression on pre-evaluation data)
        if self.use_calibration and self.calibrator_start is not None:
            p_start_cal = self.calibrator_start.calibrate(raw_p_start)
        else:
            p_start_cal = raw_p_start

        # Cap start probability at realistic empirical ceiling
        start_ceil = 0.95 if position == Position.GOALKEEPER else 0.90
        p_start_cal = min(start_ceil, p_start_cal)

        # Apply availability scaling
        p_start = round(max(0.0, min(1.0, p_start_cal * avail_factor)), 3)

        # 4. Estimate P(sub | not start) using learned statistical model
        x_sub = self.extract_sub_features(
            position=position,
            price_tenths=price_tenths,
            starts_last_3=starts_last_3,
            consecutive_zero_mins=consecutive_zero_mins,
            finished_matches=eff_finished_matches,
        )
        cond_p_sub = self.model_sub.predict_proba(x_sub)

        # Calibrate substitute probability if calibrator provided
        if self.use_calibration and self.calibrator_sub is not None:
            cond_p_sub = self.calibrator_sub.calibrate(cond_p_sub)

        # Joint substitute probability: (1 - P(start)) * P(sub | not start) * avail_factor
        p_sub = round(max(0.0, min(1.0, (1.0 - p_start) * cond_p_sub * avail_factor)), 3)

        # Deep bench pruning rule (P4 Recommendation):
        # Inactive squad players with low start and sub probabilities should not receive cameo inflation
        if p_start < 0.15 and p_sub < 0.35:
            p_sub = 0.0

        # Stage 1 Total appearance probability
        p_play = round(min(1.0, p_start + p_sub), 3)

        # 5. Conditional minutes distributions by position and regime
        pos_str = position.name
        start_info = self.starters_conditional_minutes.get(pos_str, {"mean_minutes": 82.0, "prob_60_plus": 0.93})
        sub_info = self.subs_conditional_minutes.get(pos_str, {"mean_minutes": 18.0})

        mins_if_start = start_info["mean_minutes"]
        mins_if_sub = sub_info["mean_minutes"]
        prob_60_start = start_info["prob_60_plus"]

        # Regime-sensitive conditional minutes modulation
        if regime_state is not None:
            if regime_state.regime == RoleRegime.RETURNING_FROM_INJURY:
                mins_if_start = min(mins_if_start, 75.0)
                mins_if_sub = 14.0
            elif regime_state.regime == RoleRegime.FRINGE_RESERVE:
                mins_if_start = min(mins_if_start, 70.0)
                mins_if_sub = 13.0
            elif regime_state.regime == RoleRegime.NAILED_STARTER:
                mins_if_start = max(mins_if_start, 86.0)

        # 6. Three-Stage Conditional Expected Minutes
        expected_minutes = round(min(90.0, p_start * mins_if_start + p_sub * mins_if_sub), 1)

        # Probability of 60+ minutes
        prob_60_plus = round(min(1.0, p_start * prob_60_start), 3)

        # Dynamic Role Categorization from detected regime
        if regime_state is not None:
            role = regime_state.regime.value.lower()
        elif p_start >= 0.80 and expected_minutes >= 65.0:
            role = "nailed_starter"
        elif p_start >= 0.60:
            role = "regular_starter"
        elif expected_minutes >= 25.0 or p_play >= 0.50:
            role = "rotation"
        else:
            role = "fringe"

        congested = 0.10 if (days_since_prev_fixture is not None and days_since_prev_fixture <= 3.2) else 0.0
        zero_disc = min(1.0, consecutive_zero_mins * 0.25)

        return ParticipationPrediction(
            p_start=p_start,
            p_sub=p_sub,
            p_play=p_play,
            prob_60_plus=prob_60_plus,
            mins_if_start=round(mins_if_start, 1),
            mins_if_sub=round(mins_if_sub, 1),
            expected_minutes=expected_minutes,
            role_category=role,
            congestion_discount_applied=congested,
            consecutive_zero_discount_applied=zero_disc,
        )


_DEFAULT_V09_MODEL: HierarchicalParticipationModel | None = None


def get_default_v09_participation_model() -> HierarchicalParticipationModel:
    """Return singleton instance of default calibrated V0.9 participation model."""
    global _DEFAULT_V09_MODEL
    if _DEFAULT_V09_MODEL is None:
        _DEFAULT_V09_MODEL = HierarchicalParticipationModel.default()
    return _DEFAULT_V09_MODEL


def predict_player_participation_v09(
    status: str,
    chance_of_playing_next_round: int | None = None,
    season_starts: int = 0,
    season_minutes: int = 0,
    finished_matches: int = 0,
    starts_last_3: int = 0,
    starts_last_5: int = 0,
    minutes_last_3: int = 0,
    minutes_last_5: int = 0,
    consecutive_zero_mins: int = 0,
    price_tenths: int = 50,
    position: Position = Position.MIDFIELDER,
    days_since_prev_fixture: float | None = None,
    matches_last_7_days: int = 0,
    fdr: int = 3,
    is_home: bool = True,
    model: HierarchicalParticipationModel | None = None,
) -> ParticipationPrediction:
    """Predict decomposed participation probabilities using V0.9 learned model."""
    pred_model = model or get_default_v09_participation_model()
    return pred_model.predict(
        status=status,
        chance_of_playing_next_round=chance_of_playing_next_round,
        season_starts=season_starts,
        season_minutes=season_minutes,
        finished_matches=finished_matches,
        starts_last_3=starts_last_3,
        starts_last_5=starts_last_5,
        minutes_last_3=minutes_last_3,
        minutes_last_5=minutes_last_5,
        consecutive_zero_mins=consecutive_zero_mins,
        price_tenths=price_tenths,
        position=position,
        days_since_prev_fixture=days_since_prev_fixture,
        matches_last_7_days=matches_last_7_days,
        fdr=fdr,
        is_home=is_home,
    )
