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


class OptimizerStrategy(BacktestStrategy):
    """Baseline C: Production combinatorial branch-and-bound transfer optimizer."""

    def __init__(
        self,
        max_transfers: int = 1,
        allow_hits: bool = False,
        risk_profile: str = "neutral",
        min_net_gain: float = 0.50,
    ) -> None:
        self.max_transfers = max(1, min(3, max_transfers))
        self.allow_hits = allow_hits
        self.risk_profile = risk_profile
        self.min_net_gain = min_net_gain

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
        from ..optimizer import PlayerOptInfo, solve_transfers

        # 1. Build PlayerOptInfo map
        opt_map: dict[int, PlayerOptInfo] = {}
        for p in projections:
            opt_map[p.player_id] = PlayerOptInfo(
                id=p.player_id,
                name=p.web_name,
                position=p.position,
                team_id=p.team_id,
                team_short=p.team_short,
                price_tenths=p.price_tenths,
                status=p.status,
                total_points=0,
                expected_points=p.expected_points,
                expected_minutes=p.expected_minutes,
                xp_floor=p.xp_floor,
                xp_ceiling=p.xp_ceiling,
                standard_deviation=p.standard_deviation,
            )

        squad_set = set(current_squad_ids)
        squad_opt = [opt_map[pid] for pid in current_squad_ids if pid in opt_map]
        cand_pool = [opt for pid, opt in opt_map.items() if pid not in squad_set]

        # 2. Build selling prices
        selling_prices: dict[int, int] = {}
        for pid in current_squad_ids:
            cur_p = opt_map.get(pid)
            cur_price = cur_p.price_tenths if cur_p else 50
            bought = purchase_prices.get(pid, cur_price)
            if cur_price > bought:
                selling_prices[pid] = bought + (cur_price - bought) // 2
            else:
                selling_prices[pid] = cur_price

        # 3. FDR & Ticker maps
        fdr_map: dict[str, float] = {}
        ticker_map: dict[str, str] = {}
        for fix in snapshot.fixtures:
            h_team = next((t.get("short_name", "") for t in snapshot.teams if t["team_id"] == fix.team_h), "")
            a_team = next((t.get("short_name", "") for t in snapshot.teams if t["team_id"] == fix.team_a), "")
            if h_team:
                fdr_map[h_team] = float(fix.team_h_difficulty)
                ticker_map[h_team] = f"{a_team} (H)"
            if a_team:
                fdr_map[a_team] = float(fix.team_a_difficulty)
                ticker_map[a_team] = f"{h_team} (A)"

        best_moves: list[tuple[int, int]] = []
        best_gain = self.min_net_gain

        # Evaluate transfer count options
        k_max = self.max_transfers if self.allow_hits else min(self.max_transfers, free_transfers)
        if k_max <= 0:
            return []

        for k in range(1, k_max + 1):
            recs, _ = solve_transfers(
                num_transfers=k,
                squad_players=squad_opt,
                candidate_pool=cand_pool,
                bank_tenths=bank_tenths,
                free_transfers=free_transfers,
                selling_prices=selling_prices,
                fdr_map=fdr_map,
                ticker_map=ticker_map,
                risk_profile=self.risk_profile,
                max_results=5,
            )

            for rec in recs:
                if not self.allow_hits and rec.get("hit_cost", 0) > 0:
                    continue
                net_gain = rec.get("score", rec.get("xp_delta", 0.0))
                if net_gain > best_gain:
                    best_gain = net_gain
                    out_list = [p["id"] for p in rec.get("outgoing", [])]
                    in_list = [p["id"] for p in rec.get("incoming", [])]
                    best_moves = list(zip(out_list, in_list))

        return best_moves

