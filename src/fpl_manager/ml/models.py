"""Gradient Boosting prediction models for FPL Manager (V1.3).

Provides:
- GBDTPredictor: HistGradientBoosting-based participation, conditional minutes, and matchday threat models.
- Predicts P(start), P(sub | not start), E[M | start], E[M | sub], xG, xA, and P(CS).
- Fully compatible with ParticipationPrediction interface.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import numpy as np

try:
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

from ..historical.models import HistoricalFixture, HistoricalPlayerState, Position
from ..participation import ParticipationPrediction
from .features import FEATURE_NAMES, extract_player_feature_vector


@dataclass
class GBDTPredictor:
    """Integrated Gradient Boosting predictor for FPL Manager V1.3."""

    clf_start: Any  # HistGradientBoostingClassifier
    clf_sub: Any    # HistGradientBoostingClassifier
    reg_start_mins: Any  # HistGradientBoostingRegressor
    reg_sub_mins: Any    # HistGradientBoostingRegressor
    reg_xg: Any | None = None          # HistGradientBoostingRegressor
    reg_xa: Any | None = None          # HistGradientBoostingRegressor
    clf_clean_sheet: Any | None = None  # HistGradientBoostingClassifier

    def predict_participation_from_vector(
        self,
        features: list[float],
        status: str,
        chance_val: float = 1.0,
    ) -> ParticipationPrediction:
        """Predict participation using a pre-extracted feature vector."""
        status_lower = status.lower()
        if status_lower in ("i", "s", "u") or chance_val <= 0.0:
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

        X = np.array([features], dtype=np.float32)

        # 1. P(start)
        p_start_raw = float(self.clf_start.predict_proba(X)[0, 1])
        # Scale by chance factor
        p_start = max(0.0, min(1.0, p_start_raw * chance_val))

        # 2. P(sub | not start)
        p_sub_raw = float(self.clf_sub.predict_proba(X)[0, 1])
        p_sub = max(0.0, min(1.0, (1.0 - p_start) * p_sub_raw * chance_val))

        p_play = min(1.0, p_start + p_sub)

        # 3. Conditional Minutes
        mins_if_start = float(np.clip(self.reg_start_mins.predict(X)[0], 45.0, 90.0))
        mins_if_sub = float(np.clip(self.reg_sub_mins.predict(X)[0], 5.0, 40.0))

        # Expected minutes
        expected_minutes = min(90.0, p_start * mins_if_start + p_sub * mins_if_sub)

        # Prob 60+
        if mins_if_start >= 60.0:
            prob_60 = p_start * 0.95
        else:
            prob_60 = p_start * 0.30

        role_cat = "starter" if p_start >= 0.70 else ("rotation" if p_start >= 0.35 else "fringe")

        return ParticipationPrediction(
            p_start=round(p_start, 4),
            p_sub=round(p_sub, 4),
            p_play=round(p_play, 4),
            prob_60_plus=round(prob_60, 4),
            mins_if_start=round(mins_if_start, 1),
            mins_if_sub=round(mins_if_sub, 1),
            expected_minutes=round(expected_minutes, 1),
            role_category=role_cat,
            congestion_discount_applied=0.0,
            consecutive_zero_discount_applied=0.0,
        )

    def predict_participation(
        self,
        player: HistoricalPlayerState,
        fixture: HistoricalFixture | None,
        finished_gameweeks: int,
        teams_map: dict[int, dict[str, Any]] | None = None,
    ) -> ParticipationPrediction:
        """Predict participation directly from player and fixture objects."""
        feat = extract_player_feature_vector(player, fixture, finished_gameweeks, teams_map)
        chance_val = 1.0
        if player.chance_of_playing_next_round is not None:
            chance_val = float(player.chance_of_playing_next_round) / 100.0
        elif player.status.lower() == "d":
            chance_val = 0.50
        elif player.status.lower() in ("i", "s", "u"):
            chance_val = 0.0

        return self.predict_participation_from_vector(feat, player.status, chance_val)

    def predict_threat(
        self,
        features: list[float],
        expected_minutes: float,
    ) -> tuple[float, float, float]:
        """Predict expected goals (xG), expected assists (xA), and clean sheet probability.
        
        Returns: (xg, xa, clean_sheet_prob)
        """
        if expected_minutes <= 0.0:
            return 0.0, 0.0, 0.0

        X = np.array([features], dtype=np.float32)

        xg = 0.0
        if self.reg_xg is not None:
            xg_pred = float(self.reg_xg.predict(X)[0])
            xg = max(0.0, xg_pred * (expected_minutes / 90.0))

        xa = 0.0
        if self.reg_xa is not None:
            xa_pred = float(self.reg_xa.predict(X)[0])
            xa = max(0.0, xa_pred * (expected_minutes / 90.0))

        cs_prob = 0.25
        if self.clf_clean_sheet is not None:
            cs_prob = float(self.clf_clean_sheet.predict_proba(X)[0, 1])

        return round(xg, 3), round(xa, 3), round(cs_prob, 3)

    @property
    def is_fitted(self) -> bool:
        """Return True if base models are fitted and ready."""
        return self.clf_start is not None

    def save(self, filepath: Path) -> None:
        """Persist GBDT models using joblib."""
        import joblib
        filepath.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, filepath)

    @classmethod
    def load(cls, filepath: Path) -> "GBDTPredictor":
        """Load GBDT models from disk."""
        import joblib
        return joblib.load(filepath)

    @classmethod
    def load_canonical(cls) -> "GBDTPredictor":
        """Load canonical GBDT model artifact."""
        canonical_path = Path(__file__).resolve().parent / "data" / "canonical_v13_gbdt.joblib"
        return cls.load(canonical_path)
