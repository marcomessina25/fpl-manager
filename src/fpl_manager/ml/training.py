"""Training pipeline for Gradient Boosting models in FPL Manager (V1.3).

Builds training datasets from historical season snapshots and ground truth outcomes,
fitting HistGradientBoosting estimators under strict temporal discipline.
"""

from pathlib import Path
from typing import Any
import numpy as np

try:
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

from ..historical.snapshots import build_historical_snapshot, load_gameweek_outcomes
from ..historical.models import Position
from .features import extract_player_feature_vector
from .models import GBDTPredictor

CANONICAL_MODEL_PATH = Path(__file__).resolve().parent / "data" / "canonical_v13_gbdt.joblib"


def extract_historical_training_dataset(
    seasons: list[str],
    data_dir: Path,
    start_gw: int = 2,
    end_gw: int = 38,
) -> dict[str, Any]:
    """Extract features and targets from historical seasons."""
    X_all = []
    y_start = []
    
    X_sub = []
    y_sub = []
    
    X_starters = []
    y_start_mins = []
    
    X_subs_played = []
    y_sub_mins = []

    # Threat targets
    X_threat = []
    y_xg = []
    y_xa = []
    y_cs = []

    for season in seasons:
        season_dir = data_dir / season
        if not season_dir.exists():
            continue

        for gw in range(start_gw, end_gw + 1):
            try:
                snap = build_historical_snapshot(season_dir, gw)
                outcomes = load_gameweek_outcomes(season_dir, gw)
            except Exception:
                continue

            teams_map = {t["team_id"]: t for t in snap.teams}
            fixture_map = {}
            for f in snap.fixtures:
                fixture_map[f.team_h] = f
                fixture_map[f.team_a] = f

            for p in snap.players:
                if p.player_id not in outcomes:
                    continue
                outcome = outcomes[p.player_id]

                # Hard-gate: omit clearly unavailable players from active training distribution
                if p.status.lower() in ("i", "s", "u"):
                    continue

                fixture = fixture_map.get(p.team_id)
                feat = extract_player_feature_vector(
                    player=p,
                    fixture=fixture,
                    finished_gameweeks=snap.finished_gameweeks,
                    teams_map=teams_map,
                )

                actual_started = 1 if outcome.starts >= 1 else 0
                actual_minutes = outcome.minutes

                X_all.append(feat)
                y_start.append(actual_started)

                if actual_started == 1:
                    X_starters.append(feat)
                    y_start_mins.append(float(actual_minutes))
                else:
                    X_sub.append(feat)
                    actual_subbed = 1 if actual_minutes > 0 else 0
                    y_sub.append(actual_subbed)
                    if actual_subbed == 1:
                        X_subs_played.append(feat)
                        y_sub_mins.append(float(actual_minutes))

                # Threat targets (conditioned on playing at least 15 mins)
                if actual_minutes >= 15:
                    X_threat.append(feat)
                    # Normalize actual goal and assist returns to per-90 rate
                    mins_rate = float(actual_minutes) / 90.0
                    y_xg.append(float(outcome.goals_scored) / max(0.2, mins_rate))
                    y_xa.append(float(outcome.assists) / max(0.2, mins_rate))
                    y_cs.append(1 if outcome.clean_sheets >= 1 and actual_minutes >= 60 else 0)

    return {
        "X_all": np.array(X_all, dtype=np.float32),
        "y_start": np.array(y_start, dtype=np.int32),
        "X_sub": np.array(X_sub, dtype=np.float32),
        "y_sub": np.array(y_sub, dtype=np.int32),
        "X_starters": np.array(X_starters, dtype=np.float32),
        "y_start_mins": np.array(y_start_mins, dtype=np.float32),
        "X_subs_played": np.array(X_subs_played, dtype=np.float32),
        "y_sub_mins": np.array(y_sub_mins, dtype=np.float32),
        "X_threat": np.array(X_threat, dtype=np.float32),
        "y_xg": np.array(y_xg, dtype=np.float32),
        "y_xa": np.array(y_xa, dtype=np.float32),
        "y_cs": np.array(y_cs, dtype=np.int32),
    }


def fit_gbdt_predictor(data: dict[str, Any], random_state: int = 42) -> GBDTPredictor:
    """Train all GBDT estimators from extracted tabular data."""
    if not HAS_SKLEARN:
        raise RuntimeError("scikit-learn is required to train GBDTPredictor.")

    # 1. P(start) Classifier
    clf_start = HistGradientBoostingClassifier(
        max_iter=150,
        max_leaf_nodes=31,
        learning_rate=0.08,
        min_samples_leaf=30,
        random_state=random_state,
    )
    clf_start.fit(data["X_all"], data["y_start"])

    # 2. P(sub | not start) Classifier
    clf_sub = HistGradientBoostingClassifier(
        max_iter=100,
        max_leaf_nodes=20,
        learning_rate=0.08,
        min_samples_leaf=25,
        random_state=random_state,
    )
    clf_sub.fit(data["X_sub"], data["y_sub"])

    # 3. Starters Conditional Minutes Regressor
    reg_start_mins = HistGradientBoostingRegressor(
        max_iter=100,
        max_leaf_nodes=20,
        learning_rate=0.08,
        min_samples_leaf=25,
        random_state=random_state,
    )
    reg_start_mins.fit(data["X_starters"], data["y_start_mins"])

    # 4. Subs Conditional Minutes Regressor
    reg_sub_mins = HistGradientBoostingRegressor(
        max_iter=80,
        max_leaf_nodes=15,
        learning_rate=0.08,
        min_samples_leaf=20,
        random_state=random_state,
    )
    reg_sub_mins.fit(data["X_subs_played"], data["y_sub_mins"])

    # 5. Attacking Threat & Clean Sheet models
    reg_xg = HistGradientBoostingRegressor(
        max_iter=100,
        max_leaf_nodes=20,
        learning_rate=0.08,
        min_samples_leaf=30,
        random_state=random_state,
    )
    reg_xg.fit(data["X_threat"], data["y_xg"])

    reg_xa = HistGradientBoostingRegressor(
        max_iter=100,
        max_leaf_nodes=20,
        learning_rate=0.08,
        min_samples_leaf=30,
        random_state=random_state,
    )
    reg_xa.fit(data["X_threat"], data["y_xa"])

    clf_cs = HistGradientBoostingClassifier(
        max_iter=100,
        max_leaf_nodes=20,
        learning_rate=0.08,
        min_samples_leaf=30,
        random_state=random_state,
    )
    clf_cs.fit(data["X_threat"], data["y_cs"])

    return GBDTPredictor(
        clf_start=clf_start,
        clf_sub=clf_sub,
        reg_start_mins=reg_start_mins,
        reg_sub_mins=reg_sub_mins,
        reg_xg=reg_xg,
        reg_xa=reg_xa,
        clf_clean_sheet=clf_cs,
    )


_CANONICAL_PREDICTOR_CACHE: GBDTPredictor | None = None


def get_canonical_gbdt_predictor(
    data_dir: Path | None = None,
    force_retrain: bool = False,
) -> GBDTPredictor:
    """Retrieve canonical pre-trained GBDT predictor, loading from disk or training if needed."""
    global _CANONICAL_PREDICTOR_CACHE

    if _CANONICAL_PREDICTOR_CACHE is not None and not force_retrain:
        return _CANONICAL_PREDICTOR_CACHE

    if not force_retrain and CANONICAL_MODEL_PATH.exists():
        try:
            _CANONICAL_PREDICTOR_CACHE = GBDTPredictor.load(CANONICAL_MODEL_PATH)
            return _CANONICAL_PREDICTOR_CACHE
        except Exception:
            pass

    if data_dir is None:
        # Default data directory relative to repository root
        data_dir = Path(__file__).resolve().parents[3] / "data" / "historical"

    # Train on base training seasons: 2021-22 and 2022-23
    train_data = extract_historical_training_dataset(["2021-22", "2022-23"], data_dir)
    predictor = fit_gbdt_predictor(train_data)
    try:
        predictor.save(CANONICAL_MODEL_PATH)
    except Exception:
        pass

    _CANONICAL_PREDICTOR_CACHE = predictor
    return predictor
