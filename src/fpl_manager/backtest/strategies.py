"""Deterministic decision strategies for historical backtesting for FPL Manager (V1.0.1)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..expected_points import ExpectedPointsProjection
from ..historical.models import HistoricalGameweekSnapshot, Position
from ..models import Player
from .decision_engine import BaseDecisionEngine, resolve_decision_engine


class BacktestStrategy(ABC):
    """Abstract base class for decision engine backtesting strategies."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable strategy name."""
        ...

    @abstractmethod
    def decide_transfers(
        self,
        current_squad_ids: list[int],
        purchase_prices: dict[int, int],
        bank_tenths: int,
        free_transfers: int,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
    ) -> list[tuple[int, int]]:
        """Return list of (player_out_id, player_in_id) transfer tuples."""
        ...


class NoTransferStrategy(BacktestStrategy):
    """Baseline A: Zero transfers made. Retains initial squad throughout the season."""

    def __init__(self, decision_engine: str | BaseDecisionEngine = "v0.9") -> None:
        self.decision_engine = resolve_decision_engine(decision_engine)

    @property
    def name(self) -> str:
        return "No-Transfer Baseline"

    def decide_transfers(
        self,
        current_squad_ids: list[int],
        purchase_prices: dict[int, int],
        bank_tenths: int,
        free_transfers: int,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
    ) -> list[tuple[int, int]]:
        return self.decision_engine.decide_transfers(
            strategy_name=self.name,
            current_squad_ids=current_squad_ids,
            purchase_prices=purchase_prices,
            bank_tenths=bank_tenths,
            free_transfers=free_transfers,
            snapshot=snapshot,
            projections=projections,
        )


class SimpleXpStrategy(BacktestStrategy):
    """Baseline B: Greedy single transfer replacing lowest-xP starter with highest-xP affordable player."""

    def __init__(
        self,
        min_gain_threshold: float = 0.50,
        decision_engine: str | BaseDecisionEngine = "v0.9",
    ) -> None:
        self.min_gain_threshold = min_gain_threshold
        self.decision_engine = resolve_decision_engine(decision_engine)

    @property
    def name(self) -> str:
        return "Simple xP Baseline"

    def decide_transfers(
        self,
        current_squad_ids: list[int],
        purchase_prices: dict[int, int],
        bank_tenths: int,
        free_transfers: int,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
    ) -> list[tuple[int, int]]:
        return self.decision_engine.decide_transfers(
            strategy_name=self.name,
            current_squad_ids=current_squad_ids,
            purchase_prices=purchase_prices,
            bank_tenths=bank_tenths,
            free_transfers=free_transfers,
            snapshot=snapshot,
            projections=projections,
            min_net_gain=self.min_gain_threshold,
        )

class OptimizerStrategy(BacktestStrategy):
    """Baseline C: Production combinatorial branch-and-bound transfer optimizer."""

    def __init__(
        self,
        max_transfers: int = 1,
        allow_hits: bool = False,
        risk_profile: str = "neutral",
        min_net_gain: float = 0.50,
        decision_engine: str | BaseDecisionEngine = "v0.9",
    ) -> None:
        self.max_transfers = max(1, min(3, max_transfers))
        self.allow_hits = allow_hits
        self.risk_profile = risk_profile
        self.min_net_gain = min_net_gain
        self.decision_engine = resolve_decision_engine(decision_engine)

    @property
    def name(self) -> str:
        return f"Production Optimizer ({self.risk_profile})"

    def decide_transfers(
        self,
        current_squad_ids: list[int],
        purchase_prices: dict[int, int],
        bank_tenths: int,
        free_transfers: int,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
    ) -> list[tuple[int, int]]:
        return self.decision_engine.decide_transfers(
            strategy_name=self.name,
            current_squad_ids=current_squad_ids,
            purchase_prices=purchase_prices,
            bank_tenths=bank_tenths,
            free_transfers=free_transfers,
            snapshot=snapshot,
            projections=projections,
            max_transfers=self.max_transfers,
            allow_hits=self.allow_hits,
            risk_profile=self.risk_profile,
            min_net_gain=self.min_net_gain,
        )


@dataclass(frozen=True, slots=True)
class LLMDecisionLogRecord:
    """Audit record capturing an LLM advisory recommendation during backtesting."""
    season: str
    gameweek: int
    provider: str
    model: str
    prompt_version: str
    deterministic_transfers: tuple[tuple[int, int], ...]
    llm_transfers: tuple[tuple[int, int], ...]
    was_override: bool
    is_valid: bool
    validation_error: str | None
    executed_transfers: tuple[tuple[int, int], ...]


class LLMAdvisorStrategy(BacktestStrategy):
    """Baseline D: Deterministic Optimizer coupled with LLM advisory review (V0.7.4)."""

    def __init__(
        self,
        base_optimizer: OptimizerStrategy | None = None,
        advisor_engine: Any = None,
        provider: str = "heuristic",
        model: str = "offline-v0.7",
        prompt_version: str = "v0.7-tactical",
    ) -> None:
        self.base_optimizer = base_optimizer or OptimizerStrategy(max_transfers=1, min_net_gain=0.50)
        self.advisor_engine = advisor_engine
        self.provider = provider
        self.model = model
        self.prompt_version = prompt_version
        self.decision_logs: list[LLMDecisionLogRecord] = []
        self.invalid_recommendations_count = 0
        self.total_overrides_count = 0

    @property
    def name(self) -> str:
        return f"Optimizer + LLM Advisor ({self.provider}/{self.model})"

    def decide_transfers(
        self,
        current_squad_ids: list[int],
        purchase_prices: dict[int, int],
        bank_tenths: int,
        free_transfers: int,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
    ) -> list[tuple[int, int]]:
        # 1. Generate deterministic proposal from production optimizer
        det_transfers = self.base_optimizer.decide_transfers(
            current_squad_ids=current_squad_ids,
            purchase_prices=purchase_prices,
            bank_tenths=bank_tenths,
            free_transfers=free_transfers,
            snapshot=snapshot,
            projections=projections,
        )

        # If no advisor engine is attached, default to deterministic proposal
        if self.advisor_engine is None:
            log = LLMDecisionLogRecord(
                season=snapshot.season,
                gameweek=snapshot.gameweek,
                provider=self.provider,
                model=self.model,
                prompt_version=self.prompt_version,
                deterministic_transfers=tuple(det_transfers),
                llm_transfers=tuple(det_transfers),
                was_override=False,
                is_valid=True,
                validation_error=None,
                executed_transfers=tuple(det_transfers),
            )
            self.decision_logs.append(log)
            return det_transfers

        # 2. Consult the LLM Advisor
        llm_transfers = det_transfers
        was_override = False
        is_valid = True
        validation_error = None

        try:
            # Query advisor
            advice = self.advisor_engine(
                gameweek=snapshot.gameweek,
                squad_ids=current_squad_ids,
                proposed_transfers=det_transfers,
                projections=projections,
            )

            if isinstance(advice, dict) and "transfers" in advice:
                candidate_tx = advice["transfers"]
                if candidate_tx != det_transfers:
                    was_override = True
                    # 3. Deterministic validation of LLM transfer recommendation
                    proj_map = {p.player_id: p for p in projections}
                    squad_set = set(current_squad_ids)

                    cur_bank = bank_tenths
                    temp_squad = set(current_squad_ids)
                    team_counts: dict[int, int] = {}
                    for pid in current_squad_ids:
                        p = proj_map.get(pid)
                        if p:
                            team_counts[p.team_id] = team_counts.get(p.team_id, 0) + 1

                    for out_id, in_id in candidate_tx:
                        if out_id not in temp_squad:
                            is_valid = False
                            validation_error = f"Player {out_id} not in squad."
                            break
                        if in_id in temp_squad:
                            is_valid = False
                            validation_error = f"Player {in_id} already in squad."
                            break

                        out_p = proj_map.get(out_id)
                        in_p = proj_map.get(in_id)
                        if not out_p or not in_p:
                            is_valid = False
                            validation_error = f"Unknown player id in transfer."
                            break

                        if out_p.position != in_p.position:
                            is_valid = False
                            validation_error = f"Position mismatch: {out_p.position} to {in_p.position}."
                            break

                        cur_price = out_p.price_tenths
                        bought = purchase_prices.get(out_id, cur_price)
                        sell_price = bought + max(0, (cur_price - bought) // 2)
                        cur_bank = cur_bank + sell_price - in_p.price_tenths

                        if cur_bank < 0:
                            is_valid = False
                            validation_error = f"Insufficient bank budget (£{cur_bank/10:.1f}m)."
                            break

                        allowed_quota = 3 if in_p.team_id != out_p.team_id else 4
                        if team_counts.get(in_p.team_id, 0) >= allowed_quota:
                            is_valid = False
                            validation_error = f"Team quota exceeded for team {in_p.team_id}."
                            break

                        temp_squad.remove(out_id)
                        temp_squad.add(in_id)
                        team_counts[out_p.team_id] -= 1
                        team_counts[in_p.team_id] = team_counts.get(in_p.team_id, 0) + 1

                    if is_valid:
                        llm_transfers = candidate_tx
                        self.total_overrides_count += 1
                    else:
                        self.invalid_recommendations_count += 1
                        llm_transfers = det_transfers  # fallback to deterministic proposal
        except Exception as exc:
            is_valid = False
            validation_error = f"Advisor exception: {exc}"
            self.invalid_recommendations_count += 1
            llm_transfers = det_transfers

        log = LLMDecisionLogRecord(
            season=snapshot.season,
            gameweek=snapshot.gameweek,
            provider=self.provider,
            model=self.model,
            prompt_version=self.prompt_version,
            deterministic_transfers=tuple(det_transfers),
            llm_transfers=tuple(advice.get("transfers", []) if isinstance(advice, dict) else det_transfers),
            was_override=was_override,
            is_valid=is_valid,
            validation_error=validation_error,
            executed_transfers=tuple(llm_transfers),
        )
        self.decision_logs.append(log)
        return llm_transfers


