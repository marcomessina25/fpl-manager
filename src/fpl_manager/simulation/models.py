"""Data models for historical interactive simulation (V1.4)."""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class StagedTransfer:
    """A transfer staged for the upcoming deadline."""
    out_id: int
    in_id: int
    out_name: str = ""
    in_name: str = ""
    cost_tenths: int = 0  # in_price - out_selling_price

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GameweekResolution:
    """Detailed resolution record for a simulated matchday."""
    gameweek: int
    gross_points: int
    transfer_hits: int
    net_points: int
    cumulative_net_points: int
    captain_id: int
    vice_captain_id: int
    effective_captain_id: int
    captain_promoted: bool
    captain_points: int
    chip_used: str | None
    autosubs: list[dict[str, Any]]
    starters_points: list[dict[str, Any]]
    bench_points: list[dict[str, Any]]
    transfers_executed: list[dict[str, Any]]
    squad_ids_after: list[int]
    bank_tenths_after: int
    squad_value_tenths_after: int
    # Comparison against frozen baseline engine
    engine_recommendation: dict[str, Any] | None = None
    engine_net_points: int | None = None
    human_engine_divergence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SimulationSummary:
    """Season-level analytics and benchmark results."""
    session_id: str
    season: str
    gameweeks_completed: int
    total_gross_points: int
    total_transfer_hits: int
    total_net_points: int
    total_transfers_made: int
    final_bank_tenths: int
    final_squad_value_tenths: int
    chips_used: dict[str, int]
    captain_points: int
    captain_promotions: int
    autosubs_count: int
    # Benchmark metrics
    engine_baseline_total_net_points: int | None = None
    human_vs_engine_delta: int | None = None
    override_count: int = 0
    override_positive_count: int = 0
    override_negative_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
