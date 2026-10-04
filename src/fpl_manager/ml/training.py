"""Training pipeline for Gradient Boosting models in FPL Manager (V1.3).

Builds training datasets from historical season snapshots and ground truth outcomes,
fitting HistGradientBoosting estimators under strict temporal discipline.
"""

from pathlib import Path
from typing import Any

try:
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    np = None  # type: ignore[assignment]

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

    # Return rate targets (normalized goals and assists per 90 from historical outcomes)
    X_threat = []
    y_goal_rate = []
    y_assist_rate = []
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

                # Return rate targets (conditioned on playing at least 15 mins)
                # Targets are actual goals and assists normalized to per-90 rates
                if actual_minutes >= 15:
                    X_threat.append(feat)
                    mins_rate = float(actual_minutes) / 90.0
                    y_goal_rate.append(float(outcome.goals_scored) / max(0.2, mins_rate))
                    y_assist_rate.append(float(outcome.assists) / max(0.2, mins_rate))
                    y_cs.append(1 if outcome.clean_sheets >= 1 and actual_minutes >= 60 else 0)

    y_goal_arr = np.array(y_goal_rate, dtype=np.float32)
    y_assist_arr = np.array(y_assist_rate, dtype=np.float32)

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
        "y_goal_rate": y_goal_arr,
        "y_assist_rate": y_assist_arr,
        "y_xg": y_goal_arr,    # Backward-compatible alias
        "y_xa": y_assist_arr,  # Backward-compatible alias
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

    # 5. Attacking Return Rates & Clean Sheet models
    reg_goal_rate = HistGradientBoostingRegressor(
        max_iter=100,
        max_leaf_nodes=20,
        learning_rate=0.08,
        min_samples_leaf=30,
        random_state=random_state,
    )
    goal_target = data.get("y_goal_rate", data.get("y_xg"))
    reg_goal_rate.fit(data["X_threat"], goal_target)

    reg_assist_rate = HistGradientBoostingRegressor(
        max_iter=100,
        max_leaf_nodes=20,
        learning_rate=0.08,
        min_samples_leaf=30,
        random_state=random_state,
    )
    assist_target = data.get("y_assist_rate", data.get("y_xa"))
    reg_assist_rate.fit(data["X_threat"], assist_target)

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
        reg_goal_rate=reg_goal_rate,
        reg_assist_rate=reg_assist_rate,
        clf_clean_sheet=clf_cs,
    )


_CANONICAL_PREDICTOR_CACHE: GBDTPredictor | None = None
_WALK_FORWARD_CACHE: dict[str, GBDTPredictor] = {}


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
        data_dir = Path(__file__).resolve().parents[3] / "data" / "historical"

    train_data = extract_historical_training_dataset(["2021-22", "2022-23"], data_dir)
    predictor = fit_gbdt_predictor(train_data)
    try:
        predictor.save(CANONICAL_MODEL_PATH)
    except Exception:
        pass

    _CANONICAL_PREDICTOR_CACHE = predictor
    return predictor


def get_walk_forward_gbdt_predictor(
    eval_season: str,
    data_dir: Path | None = None,
    all_seasons: tuple[str, ...] = ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26"),
) -> GBDTPredictor:
    """Retrieve or train GBDT predictor with strict out-of-sample temporal discipline.

    Invariant:
    - Primary Walk-Forward Seasons (2022-23 onwards): Training data strictly includes only prior
      historical seasons (D_{< eval_season}) to eliminate lookahead bias.
    - Retrospective Stress Test ('2021-22'): Because 2020-21 pre-season data is unavailable in the
      repository, 2021-22 is evaluated via an out-of-fold model trained on subsequent seasons
      ('2022-23', '2023-24') as a labeled retrospective stress test.
    """
    global _WALK_FORWARD_CACHE
    if eval_season in _WALK_FORWARD_CACHE:
        return _WALK_FORWARD_CACHE[eval_season]

    wf_path = CANONICAL_MODEL_PATH.parent / f"gbdt_wf_{eval_season.replace('-', '_')}.joblib"
    if wf_path.exists():
        try:
            pred = GBDTPredictor.load(wf_path)
            _WALK_FORWARD_CACHE[eval_season] = pred
            return pred
        except Exception:
            pass

    if data_dir is None:
        data_dir = Path(__file__).resolve().parents[3] / "data" / "historical"

    prior_seasons = [s for s in all_seasons if s < eval_season]
    if not prior_seasons:
        train_seasons = [s for s in all_seasons if s != eval_season][:2]
    else:
        train_seasons = prior_seasons

    train_data = extract_historical_training_dataset(train_seasons, data_dir)
    predictor = fit_gbdt_predictor(train_data)
    try:
        predictor.save(wf_path)
    except Exception:
        pass

    _WALK_FORWARD_CACHE[eval_season] = predictor
    return predictor
