"""Canonical Model Registry and Reproducibility Metadata for FPL Manager (V1.0.1).

Every quantitative prediction exposes explicit versioned provenance:
- model_version
- training_data_cutoff
- feature_set_version
- parameter_version
- prediction_timestamp

Enables deterministic reconstruction of any historical prediction from:
    snapshot + model_metadata + configuration
without relying on undocumented local state.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


REQUIRED_PROVENANCE_FIELDS: tuple[str, ...] = (
    "model_version",
    "training_data_cutoff",
    "feature_set_version",
    "parameter_version",
    "prediction_timestamp",
)


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    """Single canonical representation for quantitative model prediction provenance (P1.2, P1.3)."""

    model_version: str
    training_data_cutoff: str
    feature_set_version: str
    parameter_version: str
    prediction_timestamp: str

    def __post_init__(self) -> None:
        missing = [
            f
            for f in REQUIRED_PROVENANCE_FIELDS
            if getattr(self, f, None) is None or not str(getattr(self, f)).strip()
        ]
        if missing:
            raise ValueError(
                f"ModelMetadata missing or empty required provenance field(s): {missing}. "
                "Provenance must not be silently fabricated."
            )

    def to_dict(self) -> dict[str, str]:
        """Return dictionary representation of model metadata."""
        return asdict(self)

    @property
    def is_complete(self) -> bool:
        """Return False if any field is marked as 'incomplete/unknown'."""
        return all(
            getattr(self, f) != "incomplete/unknown"
            for f in REQUIRED_PROVENANCE_FIELDS
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, strict: bool = True) -> "ModelMetadata":
        """Construct ModelMetadata from a dictionary with explicit provenance validation (P1.2).

        When `strict=True` (default), missing or blank required provenance fields raise ValueError.
        When `strict=False`, missing fields are explicitly marked `"incomplete/unknown"` rather
        than silently fabricating valid-looking provenance.
        """
        if not isinstance(data, dict):
            raise ValueError("ModelMetadata.from_dict requires a dictionary.")

        missing = [
            f
            for f in REQUIRED_PROVENANCE_FIELDS
            if f not in data or data.get(f) is None or not str(data.get(f)).strip()
        ]
        if missing and strict:
            raise ValueError(
                f"Incomplete ModelMetadata dictionary; missing required provenance field(s): {missing}."
            )

        return cls(
            model_version=str(data["model_version"]).strip() if "model_version" not in missing else "incomplete/unknown",
            training_data_cutoff=str(data["training_data_cutoff"]).strip() if "training_data_cutoff" not in missing else "incomplete/unknown",
            feature_set_version=str(data["feature_set_version"]).strip() if "feature_set_version" not in missing else "incomplete/unknown",
            parameter_version=str(data["parameter_version"]).strip() if "parameter_version" not in missing else "incomplete/unknown",
            prediction_timestamp=str(data["prediction_timestamp"]).strip() if "prediction_timestamp" not in missing else "incomplete/unknown",
        )


MODEL_REGISTRY_CATALOG: dict[str, dict[str, str]] = {
    "v1.0.1": {
        "model_version": "v1.0.1",
        "quantitative_core_version": "v0.9.1-frozen",
        "training_data_cutoff": "pre-deadline-strict-pit (GWs 1..N-1 only)",
        "feature_set_version": "v0.9.1-pit-rolling-congestion",
        "parameter_version": "1.0.1-frozen-v0.9.1-w0.00",
    },
    "v1.0.1-canonical": {
        "model_version": "v1.0.1",
        "quantitative_core_version": "v0.9.1-frozen",
        "training_data_cutoff": "pre-deadline-strict-pit (GWs 1..N-1 only)",
        "feature_set_version": "v0.9.1-pit-rolling-congestion",
        "parameter_version": "1.0.1-frozen-v0.9.1-w0.00",
    },
    "v1.0": {
        "model_version": "v1.0.0",
        "quantitative_core_version": "v0.9.1-frozen",
        "training_data_cutoff": "pre-deadline-strict-pit (GWs 1..N-1 only)",
        "feature_set_version": "v0.9.1-pit-rolling-congestion",
        "parameter_version": "1.0.0-frozen-v0.9.1-w0.00",
    },
    "v1.0-canonical": {
        "model_version": "v1.0.0",
        "quantitative_core_version": "v0.9.1-frozen",
        "training_data_cutoff": "pre-deadline-strict-pit (GWs 1..N-1 only)",
        "feature_set_version": "v0.9.1-pit-rolling-congestion",
        "parameter_version": "1.0.0-frozen-v0.9.1-w0.00",
    },
    "v1.0.0": {
        "model_version": "v1.0.0",
        "quantitative_core_version": "v0.9.1-frozen",
        "training_data_cutoff": "pre-deadline-strict-pit (GWs 1..N-1 only)",
        "feature_set_version": "v0.9.1-pit-rolling-congestion",
        "parameter_version": "1.0.0-frozen-v0.9.1-w0.00",
    },
    "v0.9": {
        "model_version": "v0.9.1",
        "quantitative_core_version": "v0.9.1-frozen",
        "training_data_cutoff": "pre-deadline-strict-pit (GWs 1..N-1 only)",
        "feature_set_version": "v0.9.1-pit-rolling-congestion",
        "parameter_version": "0.9.1-frozen-w0.00",
    },
    "v0.9.1": {
        "model_version": "v0.9.1",
        "quantitative_core_version": "v0.9.1-frozen",
        "training_data_cutoff": "pre-deadline-strict-pit (GWs 1..N-1 only)",
        "feature_set_version": "v0.9.1-pit-rolling-congestion",
        "parameter_version": "0.9.1-frozen-w0.00",
    },
    "v0.8": {
        "model_version": "v0.8.0",
        "quantitative_core_version": "v0.8.0-frozen",
        "training_data_cutoff": "pre-deadline-strict-pit (GWs 1..N-1 only)",
        "feature_set_version": "v0.8.0-heuristic-participation",
        "parameter_version": "0.8.0-frozen",
    },
}


def resolve_historical_snapshot_timestamp(snapshot: Any, gameweek: int | None = None) -> str:
    """Extract deterministic historical snapshot/deadline timestamp without calling system clock (P1.3)."""
    for attr in ("timestamp_utc", "deadline_time", "snapshot_timestamp", "fetched_at"):
        val = getattr(snapshot, attr, None) if snapshot is not None else None
        if val is not None and str(val).strip():
            return str(val).strip()
    gw = gameweek if gameweek is not None else getattr(snapshot, "gameweek", None)
    season = getattr(snapshot, "season", None)
    if gw is not None and season:
        return f"{season}-gw{gw}-pre-deadline-snapshot"
    if gw is not None:
        return f"pre-deadline-gw{gw}-deterministic"
    raise ValueError(
        "Cannot resolve deterministic historical prediction_timestamp without snapshot timestamp, deadline, or gameweek."
    )


def get_model_metadata(
    predictor_version: str = "v1.0",
    gameweek: int | None = None,
    prediction_timestamp: str | None = None,
    training_data_cutoff: str | None = None,
    *,
    mode: str = "live",
    snapshot: Any | None = None,
) -> ModelMetadata:
    """Resolve canonical ModelMetadata for a given predictor version and gameweek context (P1.2, P1.3).

    Semantics (P1.3):
    - When `mode == 'historical'` (or `snapshot` is supplied):
      `prediction_timestamp` is resolved strictly from `prediction_timestamp` or the historical
      snapshot/deadline timestamp (`resolve_historical_snapshot_timestamp`), NEVER from `datetime.now(UTC)`.
    - When `mode == 'live'`:
      `prediction_timestamp` uses the supplied timestamp, deterministic GW pre-deadline anchor,
      or the current UTC prediction time.
    """
    norm = predictor_version.strip().lower()
    spec = MODEL_REGISTRY_CATALOG.get(norm, MODEL_REGISTRY_CATALOG["v1.0"])
    effective_gw = gameweek if gameweek is not None else getattr(snapshot, "gameweek", None)

    cutoff = training_data_cutoff
    if cutoff is None:
        if effective_gw is not None:
            prior_gw = max(0, int(effective_gw) - 1)
            cutoff = f"pre-gw{effective_gw}-deadline (completed_gws<=GW{prior_gw})"
        else:
            cutoff = spec["training_data_cutoff"]

    ts = prediction_timestamp
    if ts is None:
        if mode == "historical" or snapshot is not None:
            ts = resolve_historical_snapshot_timestamp(snapshot, gameweek=effective_gw)
        elif effective_gw is not None:
            ts = f"pre-deadline-gw{effective_gw}-deterministic"
        else:
            ts = datetime.now(UTC).replace(microsecond=0).isoformat()

    return ModelMetadata(
        model_version=spec["model_version"],
        training_data_cutoff=cutoff,
        feature_set_version=spec["feature_set_version"],
        parameter_version=spec["parameter_version"],
        prediction_timestamp=ts,
    )


def reconstruct_historical_prediction(
    snapshot: Any,
    model_metadata: ModelMetadata | dict[str, Any],
    configuration: dict[str, Any] | None = None,
) -> list[Any]:
    """Deterministically reconstruct historical projections from snapshot + metadata + config (P1.2, P1.3).

    Guarantees that `prediction_timestamp` on reconstructed historical metadata is anchored
    to the historical snapshot/deadline timestamp and never depends on the wall clock.
    """
    from dataclasses import replace
    from .historical.reconstruction import reconstruct_features_and_project

    hist_ts = resolve_historical_snapshot_timestamp(snapshot, gameweek=getattr(snapshot, "gameweek", None))
    if isinstance(model_metadata, ModelMetadata):
        deterministic_meta = (
            model_metadata
            if model_metadata.prediction_timestamp
            else replace(model_metadata, prediction_timestamp=hist_ts)
        )
    else:
        raw_meta = dict(model_metadata)
        if not str(raw_meta.get("prediction_timestamp", "") or "").strip():
            raw_meta["prediction_timestamp"] = hist_ts
        deterministic_meta = ModelMetadata.from_dict(raw_meta, strict=True)

    cfg = configuration or {}
    predictor_ver = cfg.get("predictor_version")
    if not predictor_ver:
        if deterministic_meta.model_version.startswith("v0.8"):
            predictor_ver = "v0.8"
        elif deterministic_meta.model_version.startswith("v0.7"):
            predictor_ver = "v0.7"
        else:
            predictor_ver = "v1.0"

    player_ids = cfg.get("player_ids")
    raw_projections = reconstruct_features_and_project(
        snapshot=snapshot,
        player_ids=player_ids,
        predictor_version=predictor_ver,
    )
    meta_dict = deterministic_meta.to_dict()
    return [replace(proj, model_metadata=meta_dict) for proj in raw_projections]


