"""Canonical Model Registry and Reproducibility Metadata for FPL Manager V1.0 (P1.2).

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


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    """Single canonical representation for quantitative model prediction provenance."""

    model_version: str
    training_data_cutoff: str
    feature_set_version: str
    parameter_version: str
    prediction_timestamp: str

    def to_dict(self) -> dict[str, str]:
        """Return dictionary representation of model metadata."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelMetadata":
        """Construct ModelMetadata from a dictionary."""
        return cls(
            model_version=str(data.get("model_version", "v1.0.0")),
            training_data_cutoff=str(data.get("training_data_cutoff", "pre-deadline-strict-pit")),
            feature_set_version=str(data.get("feature_set_version", "v0.9.1-pit-rolling-congestion")),
            parameter_version=str(data.get("parameter_version", "1.0.0-frozen-v0.9.1-w0.00")),
            prediction_timestamp=str(data.get("prediction_timestamp", "1970-01-01T00:00:00+00:00")),
        )


MODEL_REGISTRY_CATALOG: dict[str, dict[str, str]] = {
    "v1.0": {
        "model_version": "v1.0.0",
        "training_data_cutoff": "pre-deadline-strict-pit (GWs 1..N-1 only)",
        "feature_set_version": "v0.9.1-pit-rolling-congestion",
        "parameter_version": "1.0.0-frozen-v0.9.1-w0.00",
    },
    "v1.0.0": {
        "model_version": "v1.0.0",
        "training_data_cutoff": "pre-deadline-strict-pit (GWs 1..N-1 only)",
        "feature_set_version": "v0.9.1-pit-rolling-congestion",
        "parameter_version": "1.0.0-frozen-v0.9.1-w0.00",
    },
    "v0.9": {
        "model_version": "v0.9.1",
        "training_data_cutoff": "pre-deadline-strict-pit (GWs 1..N-1 only)",
        "feature_set_version": "v0.9.1-pit-rolling-congestion",
        "parameter_version": "0.9.1-frozen-w0.00",
    },
    "v0.9.1": {
        "model_version": "v0.9.1",
        "training_data_cutoff": "pre-deadline-strict-pit (GWs 1..N-1 only)",
        "feature_set_version": "v0.9.1-pit-rolling-congestion",
        "parameter_version": "0.9.1-frozen-w0.00",
    },
    "v0.8": {
        "model_version": "v0.8.0",
        "training_data_cutoff": "pre-deadline-strict-pit (GWs 1..N-1 only)",
        "feature_set_version": "v0.8.0-heuristic-participation",
        "parameter_version": "0.8.0-frozen",
    },
}


def get_model_metadata(
    predictor_version: str = "v1.0",
    gameweek: int | None = None,
    prediction_timestamp: str | None = None,
    training_data_cutoff: str | None = None,
) -> ModelMetadata:
    """Resolve canonical ModelMetadata for a given predictor version and gameweek context."""
    norm = predictor_version.strip().lower()
    spec = MODEL_REGISTRY_CATALOG.get(norm, MODEL_REGISTRY_CATALOG["v1.0"])

    cutoff = training_data_cutoff
    if cutoff is None:
        if gameweek is not None:
            prior_gw = max(0, int(gameweek) - 1)
            cutoff = f"pre-gw{gameweek}-deadline (completed_gws<=GW{prior_gw})"
        else:
            cutoff = spec["training_data_cutoff"]

    ts = prediction_timestamp
    if ts is None:
        if gameweek is not None:
            ts = f"pre-deadline-gw{gameweek}-deterministic"
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
    """Deterministically reconstruct historical projections from snapshot + metadata + config.

    Proves P1.2 acceptance criterion: a historical prediction can be reconstructed
    from (snapshot + model metadata + configuration) without relying on undocumented
    local state.
    """
    from dataclasses import replace
    from .historical.reconstruction import reconstruct_features_and_project

    meta = (
        model_metadata
        if isinstance(model_metadata, ModelMetadata)
        else ModelMetadata.from_dict(model_metadata)
    )
    cfg = configuration or {}
    predictor_ver = cfg.get("predictor_version")
    if not predictor_ver:
        if meta.model_version.startswith("v0.8"):
            predictor_ver = "v0.8"
        elif meta.model_version.startswith("v0.7"):
            predictor_ver = "v0.7"
        else:
            predictor_ver = "v1.0"

    player_ids = cfg.get("player_ids")
    raw_projections = reconstruct_features_and_project(
        snapshot=snapshot,
        player_ids=player_ids,
        predictor_version=predictor_ver,
    )
    meta_dict = meta.to_dict()
    return [replace(proj, model_metadata=meta_dict) for proj in raw_projections]

