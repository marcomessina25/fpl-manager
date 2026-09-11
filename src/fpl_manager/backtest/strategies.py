"""Deterministic decision strategies for historical backtesting (V0.7.2 & V0.7.3)."""

from abc import ABC, abstractmethod
from typing import Any

from ..expected_points import ExpectedPointsProjection
from ..historical.models import HistoricalGameweekSnapshot, Position
from ..models import Player


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
        return []


class SimpleXpStrategy(BacktestStrategy):
    """Baseline B: Greedy single transfer replacing lowest-xP starter with highest-xP affordable player."""

    def __init__(self, min_gain_threshold: float = 0.50) -> None:
        self.min_gain_threshold = min_gain_threshold

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
        if free_transfers <= 0:
            return []

        proj_by_id = {p.player_id: p for p in projections}
        squad_set = set(current_squad_ids)

        # Team counts
        team_counts: dict[int, int] = {}
        for pid in current_squad_ids:
            p = proj_by_id.get(pid)
            if p:
                team_counts[p.team_id] = team_counts.get(p.team_id, 0) + 1

        # Calculate selling prices
        selling_prices: dict[int, int] = {}
        for pid in current_squad_ids:
            p = proj_by_id.get(pid)
            cur_price = p.price_tenths if p else 50
            bought_price = purchase_prices.get(pid, cur_price)
            if cur_price > bought_price:
                selling_prices[pid] = bought_price + (cur_price - bought_price) // 2
            else:
                selling_prices[pid] = cur_price

        # Sort squad players by projected xP ascending
        squad_projs = [proj_by_id[pid] for pid in current_squad_ids if pid in proj_by_id]
        squad_projs.sort(key=lambda p: p.expected_points)

        best_transfer: tuple[int, int] | None = None
        max_gain = self.min_gain_threshold

        for out_p in squad_projs:
            sell_price = selling_prices.get(out_p.player_id, out_p.price_tenths)
            available_budget = bank_tenths + sell_price

            # Candidate pool of same position not in squad
            candidates = [
                cand for cand in projections
                if cand.position == out_p.position
                and cand.player_id not in squad_set
                and cand.price_tenths <= available_budget
            ]

            for cand in candidates:
                # Check club quota
                allowed_quota = 3 if cand.team_id != out_p.team_id else 4
                if team_counts.get(cand.team_id, 0) >= allowed_quota:
                    continue

                gain = cand.expected_points - out_p.expected_points
                if gain > max_gain:
                    max_gain = gain
                    best_transfer = (out_p.player_id, cand.player_id)

            if best_transfer:
                break

        return [best_transfer] if best_transfer else []
