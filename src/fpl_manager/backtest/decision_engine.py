"""Decision Engine implementations and version-controlled abstraction (V0.8, V0.9, V1.0 / V1.0.1).

Provides explicit separation between the frozen V0.8 heuristic decision engine,
the V0.9 participation-aware decision engine, and the V1.0 / V1.0.1 canonical decision engine
(`DecisionEngineV10`, where `neutral` defaults to `lineup_penalty_weight = 0.0`).
"""

from abc import ABC, abstractmethod
import json
from pathlib import Path
from typing import Any

from ..expected_points import ExpectedPointsProjection
from ..historical.models import HistoricalGameweekSnapshot, Position
from ..models import is_departed_from_premier_league, is_long_term_unavailable

LEGAL_FORMATIONS = (
    (3, 5, 2),
    (3, 4, 3),
    (4, 4, 2),
    (4, 3, 3),
    (4, 5, 1),
    (5, 3, 2),
    (5, 4, 1),
    (5, 2, 3),
)


class BaseDecisionEngine(ABC):
    """Abstract base class for versioned FPL decision engines."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Engine version identifier (e.g. 'v0.8', 'v0.9')."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of the decision engine."""
        ...

    @property
    @abstractmethod
    def optimizer_implementation(self) -> str:
        """Name/path of the optimizer implementation function."""
        ...

    @abstractmethod
    def initialize_squad(
        self,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
        budget_tenths: int = 1000,
    ) -> tuple[list[int], dict[int, int], int]:
        """Select initial 15-player squad and return (squad_ids, purchase_prices, remaining_bank)."""
        ...

    @abstractmethod
    def select_lineup(
        self,
        squad_ids: list[int],
        projections: list[ExpectedPointsProjection],
    ) -> tuple[list[int], list[int], int, int, float]:
        """Select optimal starting 11, bench, captain, vice-captain, and predicted xP."""
        ...

    @abstractmethod
    def decide_transfers(
        self,
        strategy_name: str,
        current_squad_ids: list[int],
        purchase_prices: dict[int, int],
        bank_tenths: int,
        free_transfers: int,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
        max_transfers: int = 1,
        allow_hits: bool = True,
        risk_profile: str = "neutral",
        min_net_gain: float = 0.50,
    ) -> list[tuple[int, int]]:
        """Determine transfer moves (player_out_id, player_in_id) for the gameweek."""
        ...

    def get_strategy_config(self, strategy_name: str, **kwargs: Any) -> dict[str, Any]:
        """Return a structured machine-readable metadata dict for logging."""
        return {
            "engine_version": self.version,
            "engine_name": self.name,
            "optimizer_implementation": self.optimizer_implementation,
            "strategy_name": strategy_name,
            **kwargs,
        }


class DecisionEngineV08(BaseDecisionEngine):
    """Frozen V0.8 Decision Engine:

    - Squad Init: Pure greedy selection by position within budget (no swap fallback).
    - Lineup: Starters chosen purely by raw expected_points; captain is max xP.
    - Transfers: Standard solver evaluating unconstrained xP delta without participation risk penalty.
    """

    @property
    def version(self) -> str:
        return "v0.8"

    @property
    def name(self) -> str:
        return "V0.8 Frozen Heuristic Decision Engine"

    @property
    def optimizer_implementation(self) -> str:
        return "fpl_manager.optimizer.solve_transfers:v0.8_unconstrained"

    def initialize_squad(
        self,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
        budget_tenths: int = 1000,
    ) -> tuple[list[int], dict[int, int], int]:
        target_counts = {
            Position.GOALKEEPER: 2,
            Position.DEFENDER: 5,
            Position.MIDFIELDER: 5,
            Position.FORWARD: 3,
        }
        by_pos: dict[Position, list[ExpectedPointsProjection]] = {pos: [] for pos in Position}
        for p in projections:
            by_pos[p.position].append(p)

        for pos in by_pos:
            by_pos[pos].sort(key=lambda p: (p.expected_points, -p.price_tenths), reverse=True)

        selected_ids: list[int] = []
        purchase_prices: dict[int, int] = {}
        team_counts: dict[int, int] = {}
        spent = 0

        for pos, needed in target_counts.items():
            candidates = by_pos[pos]
            picked = 0
            for cand in candidates:
                if picked >= needed:
                    break
                if cand.player_id in selected_ids:
                    continue
                if team_counts.get(cand.team_id, 0) >= 3:
                    continue
                if spent + cand.price_tenths + (15 - len(selected_ids) - 1) * 40 > budget_tenths:
                    continue

                selected_ids.append(cand.player_id)
                purchase_prices[cand.player_id] = cand.price_tenths
                team_counts[cand.team_id] = team_counts.get(cand.team_id, 0) + 1
                spent += cand.price_tenths
                picked += 1

            if picked < needed:
                cheapest = sorted(candidates, key=lambda p: p.price_tenths)
                for cand in cheapest:
                    if picked >= needed:
                        break
                    if cand.player_id in selected_ids:
                        continue
                    if team_counts.get(cand.team_id, 0) >= 3:
                        continue
                    selected_ids.append(cand.player_id)
                    purchase_prices[cand.player_id] = cand.price_tenths
                    team_counts[cand.team_id] = team_counts.get(cand.team_id, 0) + 1
                    spent += cand.price_tenths
                    picked += 1

        remaining_bank = budget_tenths - spent
        return selected_ids, purchase_prices, remaining_bank

    def select_lineup(
        self,
        squad_ids: list[int],
        projections: list[ExpectedPointsProjection],
    ) -> tuple[list[int], list[int], int, int, float]:
        proj_map = {p.player_id: p for p in projections}
        by_pos: dict[Position, list[ExpectedPointsProjection]] = {pos: [] for pos in Position}
        for pid in squad_ids:
            p = proj_map.get(pid)
            if p:
                by_pos[p.position].append(p)

        for pos in by_pos:
            by_pos[pos].sort(key=lambda p: (p.expected_points, p.base_xp_per_match), reverse=True)

        gks = by_pos[Position.GOALKEEPER]
        defs = by_pos[Position.DEFENDER]
        mids = by_pos[Position.MIDFIELDER]
        fwds = by_pos[Position.FORWARD]

        best_starters: list[int] = []
        best_xp = -1.0

        starting_gk = gks[0].player_id if gks else squad_ids[0]

        for d_cnt, m_cnt, f_cnt in LEGAL_FORMATIONS:
            if len(defs) < d_cnt or len(mids) < m_cnt or len(fwds) < f_cnt:
                continue
            cur_starters = [starting_gk]
            cur_starters.extend(p.player_id for p in defs[:d_cnt])
            cur_starters.extend(p.player_id for p in mids[:m_cnt])
            cur_starters.extend(p.player_id for p in fwds[:f_cnt])

            tot_xp = sum(proj_map[pid].expected_points for pid in cur_starters if pid in proj_map)
            if tot_xp > best_xp:
                best_xp = tot_xp
                best_starters = cur_starters

        if not best_starters:
            best_starters = squad_ids[:11]
            best_xp = sum(proj_map[pid].expected_points for pid in best_starters if pid in proj_map)

        # Pure raw xP for captaincy in V0.8
        starters_sorted = sorted(
            best_starters,
            key=lambda pid: proj_map[pid].expected_points if pid in proj_map else 0.0,
            reverse=True,
        )
        captain_id = starters_sorted[0]
        vice_captain_id = starters_sorted[1] if len(starters_sorted) > 1 else starters_sorted[0]

        bench_set = set(squad_ids) - set(best_starters)
        outfield_bench = [
            pid for pid in squad_ids
            if pid in bench_set and proj_map.get(pid) and proj_map[pid].position != Position.GOALKEEPER
        ]
        outfield_bench.sort(key=lambda pid: proj_map[pid].expected_points if pid in proj_map else 0.0, reverse=True)
        gk_bench = [
            pid for pid in squad_ids
            if pid in bench_set and proj_map.get(pid) and proj_map[pid].position == Position.GOALKEEPER
        ]

        ordered_bench = outfield_bench + gk_bench
        return best_starters, ordered_bench, captain_id, vice_captain_id, round(best_xp, 2)

    def decide_transfers(
        self,
        strategy_name: str,
        current_squad_ids: list[int],
        purchase_prices: dict[int, int],
        bank_tenths: int,
        free_transfers: int,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
        max_transfers: int = 1,
        allow_hits: bool = True,
        risk_profile: str = "neutral",
        min_net_gain: float = 0.50,
    ) -> list[tuple[int, int]]:
        strat = strategy_name.lower().strip().replace("-", "").replace("_", "").replace(" ", "")
        if "notransfer" in strat:
            return []

        if "simplexp" in strat:
            if free_transfers <= 0:
                return []
            proj_by_id = {p.player_id: p for p in projections}
            squad_set = set(current_squad_ids)
            team_counts: dict[int, int] = {}
            for pid in current_squad_ids:
                p = proj_by_id.get(pid)
                if p:
                    team_counts[p.team_id] = team_counts.get(p.team_id, 0) + 1

            selling_prices: dict[int, int] = {}
            for pid in current_squad_ids:
                p = proj_by_id.get(pid)
                cur_price = p.price_tenths if p else 50
                bought_price = purchase_prices.get(pid, cur_price)
                selling_prices[pid] = bought_price + max(0, (cur_price - bought_price) // 2)

            squad_projs = [proj_by_id[pid] for pid in current_squad_ids if pid in proj_by_id]
            squad_projs.sort(key=lambda p: p.expected_points)

            for out_p in squad_projs:
                out_id = out_p.player_id
                available_cash = bank_tenths + selling_prices[out_id]
                cands = [
                    p for p in projections
                    if p.player_id not in squad_set
                    and p.position == out_p.position
                    and p.price_tenths <= available_cash
                ]
                valid_cands = [
                    p for p in cands
                    if p.team_id == out_p.team_id or team_counts.get(p.team_id, 0) < 3
                ]
                if not valid_cands:
                    continue
                valid_cands.sort(key=lambda p: p.expected_points, reverse=True)
                best_in = valid_cands[0]
                if (best_in.expected_points - out_p.expected_points) >= min_net_gain:
                    return [(out_id, best_in.player_id)]
            return []

        # Production Optimizer Strategy (V0.8 unconstrained)
        from ..optimizer import PlayerOptInfo, solve_transfers

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
                is_long_term_unavailable=getattr(p, "is_long_term_unavailable", False),
            )

        squad_set = set(current_squad_ids)
        squad_opt = [opt_map[pid] for pid in current_squad_ids if pid in opt_map]
        cand_pool = [opt for pid, opt in opt_map.items() if pid not in squad_set]

        selling_prices = {}
        for pid in current_squad_ids:
            cur_p = opt_map.get(pid)
            cur_price = cur_p.price_tenths if cur_p else 50
            bought = purchase_prices.get(pid, cur_price)
            selling_prices[pid] = bought + max(0, (cur_price - bought) // 2)

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
        best_gain = min_net_gain
        k_max = max_transfers if allow_hits else min(max_transfers, free_transfers)
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
                risk_profile=risk_profile,
                max_results=5,
            )
            for rec in recs:
                if not allow_hits and rec.get("hit_cost", 0) > 0:
                    continue
                net_gain = rec.get("score", rec.get("xp_delta", 0.0))
                if net_gain > best_gain:
                    best_gain = net_gain
                    out_list = [p["id"] for p in rec.get("outgoing", [])]
                    in_list = [p["id"] for p in rec.get("incoming", [])]
                    best_moves = list(zip(out_list, in_list))

        return best_moves


def calculate_lineup_risk_score(expected_points: float, start_probability: float, penalty_weight: float = 0.0) -> float:
    """Calculate risk-adjusted lineup score.

    Formula: score = xp * [1 - weight * (1 - p_start)]
    At weight=0.00 (V0.9.1 default / unconstrained):
        score = xp
    At weight=0.20 (legacy V0.9 baseline):
        score = xp * (0.80 + 0.20 * p_start)
    """
    return expected_points * (1.0 - penalty_weight * (1.0 - start_probability))


class DecisionEngineV09(BaseDecisionEngine):
    """V0.9 / V0.9.1 Participation-Aware Decision Engine:

    - Squad Init: Saturation-swap enabled greedy selection.
    - Lineup: Participation-risk adjusted starter valuation (penalizes uncertain starters if weight > 0; default weight=0.00 based on multi-year calibration).
    - Captaincy: Captain requires high start confidence (P(start) >= 0.60) to eliminate 0-min captains.
    - Bench: Outfield bench ordered by expected points weighted by play probability.
    - Transfers: Rejection/discounting of low-start-probability rotation traps.
    """

    def __init__(self, lineup_penalty_weight: float = 0.0) -> None:
        self.lineup_penalty_weight = lineup_penalty_weight

    @property
    def version(self) -> str:
        return "v0.9"

    @property
    def name(self) -> str:
        if abs(self.lineup_penalty_weight - 0.0) < 1e-6:
            return "V0.9 Participation-Aware Decision Engine"
        return f"V0.9 Participation-Aware Decision Engine (w={self.lineup_penalty_weight:.2f})"

    @property
    def optimizer_implementation(self) -> str:
        return "fpl_manager.optimizer.solve_transfers:v0.9_participation_aware"

    def initialize_squad(
        self,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
        budget_tenths: int = 1000,
    ) -> tuple[list[int], dict[int, int], int]:
        target_counts = {
            Position.GOALKEEPER: 2,
            Position.DEFENDER: 5,
            Position.MIDFIELDER: 5,
            Position.FORWARD: 3,
        }
        by_pos: dict[Position, list[ExpectedPointsProjection]] = {pos: [] for pos in Position}
        for p in projections:
            by_pos[p.position].append(p)

        for pos in by_pos:
            # Sort by risk-adjusted xP in V0.9 squad init
            by_pos[pos].sort(key=lambda p: (p.expected_points * (0.8 + 0.2 * p.start_probability), -p.price_tenths), reverse=True)

        selected_ids: list[int] = []
        purchase_prices: dict[int, int] = {}
        team_counts: dict[int, int] = {}
        spent = 0

        for pos, needed in target_counts.items():
            candidates = by_pos[pos]
            picked = 0
            for cand in candidates:
                if picked >= needed:
                    break
                if cand.player_id in selected_ids:
                    continue
                if team_counts.get(cand.team_id, 0) >= 3:
                    continue
                if spent + cand.price_tenths + (15 - len(selected_ids) - 1) * 40 > budget_tenths:
                    continue

                selected_ids.append(cand.player_id)
                purchase_prices[cand.player_id] = cand.price_tenths
                team_counts[cand.team_id] = team_counts.get(cand.team_id, 0) + 1
                spent += cand.price_tenths
                picked += 1

            if picked < needed:
                cheapest = sorted(candidates, key=lambda p: p.price_tenths)
                for cand in cheapest:
                    if picked >= needed:
                        break
                    if cand.player_id in selected_ids:
                        continue
                    if team_counts.get(cand.team_id, 0) >= 3:
                        continue
                    selected_ids.append(cand.player_id)
                    purchase_prices[cand.player_id] = cand.price_tenths
                    team_counts[cand.team_id] = team_counts.get(cand.team_id, 0) + 1
                    spent += cand.price_tenths
                    picked += 1

            # V0.9 Club saturation swap fallback
            if picked < needed:
                blocked_cands = [
                    c for c in candidates
                    if c.player_id not in selected_ids and team_counts.get(c.team_id, 0) >= 3
                ]
                for cand in blocked_cands:
                    if picked >= needed:
                        break
                    swapped = False
                    for sel_id in list(selected_ids):
                        sel_p = next((p for p in projections if p.player_id == sel_id), None)
                        if sel_p is None or sel_p.team_id != cand.team_id or sel_p.position == pos:
                            continue
                        alt_candidates = sorted(by_pos[sel_p.position], key=lambda p: p.price_tenths)
                        for alt in alt_candidates:
                            if alt.player_id in selected_ids or alt.player_id == sel_p.player_id:
                                continue
                            if team_counts.get(alt.team_id, 0) >= 3 or alt.team_id == cand.team_id:
                                continue

                            selected_ids.remove(sel_p.player_id)
                            spent -= purchase_prices[sel_p.player_id]
                            del purchase_prices[sel_p.player_id]
                            team_counts[sel_p.team_id] -= 1

                            selected_ids.append(alt.player_id)
                            purchase_prices[alt.player_id] = alt.price_tenths
                            team_counts[alt.team_id] = team_counts.get(alt.team_id, 0) + 1
                            spent += alt.price_tenths

                            selected_ids.append(cand.player_id)
                            purchase_prices[cand.player_id] = cand.price_tenths
                            team_counts[cand.team_id] = team_counts.get(cand.team_id, 0) + 1
                            spent += cand.price_tenths
                            picked += 1
                            swapped = True
                            break
                        if swapped:
                            break

        remaining_bank = budget_tenths - spent
        return selected_ids, purchase_prices, remaining_bank

    def select_lineup(
        self,
        squad_ids: list[int],
        projections: list[ExpectedPointsProjection],
    ) -> tuple[list[int], list[int], int, int, float]:
        proj_map = {p.player_id: p for p in projections}
        by_pos: dict[Position, list[ExpectedPointsProjection]] = {pos: [] for pos in Position}
        for pid in squad_ids:
            p = proj_map.get(pid)
            if p:
                by_pos[p.position].append(p)

        # In V0.9, rank players within position by risk-adjusted starting utility:
        # players with high P(start) are prioritized over players with low P(start)
        w = self.lineup_penalty_weight
        for pos in by_pos:
            by_pos[pos].sort(
                key=lambda p: (
                    calculate_lineup_risk_score(p.expected_points, p.start_probability, w),
                    p.expected_points,
                    p.base_xp_per_match,
                ),
                reverse=True,
            )

        gks = by_pos[Position.GOALKEEPER]
        defs = by_pos[Position.DEFENDER]
        mids = by_pos[Position.MIDFIELDER]
        fwds = by_pos[Position.FORWARD]

        best_starters: list[int] = []
        best_score = -1.0
        best_raw_xp = -1.0

        starting_gk = gks[0].player_id if gks else squad_ids[0]

        for d_cnt, m_cnt, f_cnt in LEGAL_FORMATIONS:
            if len(defs) < d_cnt or len(mids) < m_cnt or len(fwds) < f_cnt:
                continue
            cur_starters = [starting_gk]
            cur_starters.extend(p.player_id for p in defs[:d_cnt])
            cur_starters.extend(p.player_id for p in mids[:m_cnt])
            cur_starters.extend(p.player_id for p in fwds[:f_cnt])

            tot_score = sum(
                calculate_lineup_risk_score(proj_map[pid].expected_points, proj_map[pid].start_probability, w)
                for pid in cur_starters if pid in proj_map
            )
            raw_xp = sum(proj_map[pid].expected_points for pid in cur_starters if pid in proj_map)
            if tot_score > best_score:
                best_score = tot_score
                best_raw_xp = raw_xp
                best_starters = cur_starters

        if not best_starters:
            best_starters = squad_ids[:11]
            best_raw_xp = sum(proj_map[pid].expected_points for pid in best_starters if pid in proj_map)

        # V0.9 Participation-Aware Captaincy Safeguard:
        # Require P(start) >= 0.60 for captaincy if any starter qualifies, avoiding 0-min captains.
        starter_objs = [proj_map[pid] for pid in best_starters if pid in proj_map]
        reliable_cap_cands = [p for p in starter_objs if p.start_probability >= 0.60]
        if not reliable_cap_cands:
            reliable_cap_cands = starter_objs

        if reliable_cap_cands:
            reliable_cap_cands.sort(key=lambda p: (p.expected_points * (0.85 + 0.15 * p.start_probability)), reverse=True)
            captain_id = reliable_cap_cands[0].player_id
        else:
            captain_id = best_starters[0] if best_starters else squad_ids[0]

        rem_starters = [p for p in starter_objs if p.player_id != captain_id]
        if rem_starters:
            reliable_vc = [p for p in rem_starters if p.start_probability >= 0.60] or rem_starters
            reliable_vc.sort(key=lambda p: (p.expected_points * (0.85 + 0.15 * p.start_probability)), reverse=True)
            vice_captain_id = reliable_vc[0].player_id
        else:
            vice_captain_id = captain_id

        # V0.9 Bench Ordering:
        # Outfield bench ordered by expected points weighted by play probability,
        # ensuring players who actually play are first on the bench to be autosubbed in.
        bench_set = set(squad_ids) - set(best_starters)
        outfield_bench = [
            pid for pid in squad_ids
            if pid in bench_set and proj_map.get(pid) and proj_map[pid].position != Position.GOALKEEPER
        ]
        outfield_bench.sort(
            key=lambda pid: proj_map[pid].expected_points * max(0.2, proj_map[pid].play_probability) if pid in proj_map else 0.0,
            reverse=True,
        )
        gk_bench = [
            pid for pid in squad_ids
            if pid in bench_set and proj_map.get(pid) and proj_map[pid].position == Position.GOALKEEPER
        ]

        ordered_bench = outfield_bench + gk_bench
        return best_starters, ordered_bench, captain_id, vice_captain_id, round(best_raw_xp, 2)

    def decide_transfers(
        self,
        strategy_name: str,
        current_squad_ids: list[int],
        purchase_prices: dict[int, int],
        bank_tenths: int,
        free_transfers: int,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
        max_transfers: int = 1,
        allow_hits: bool = True,
        risk_profile: str = "neutral",
        min_net_gain: float = 0.50,
    ) -> list[tuple[int, int]]:
        strat = strategy_name.lower().strip().replace("-", "").replace("_", "").replace(" ", "")
        if "notransfer" in strat:
            return []

        if "simplexp" in strat:
            if free_transfers <= 0:
                return []
            proj_by_id = {p.player_id: p for p in projections}
            squad_set = set(current_squad_ids)
            team_counts: dict[int, int] = {}
            for pid in current_squad_ids:
                p = proj_by_id.get(pid)
                if p:
                    team_counts[p.team_id] = team_counts.get(p.team_id, 0) + 1

            selling_prices: dict[int, int] = {}
            for pid in current_squad_ids:
                p = proj_by_id.get(pid)
                cur_price = p.price_tenths if p else 50
                bought_price = purchase_prices.get(pid, cur_price)
                selling_prices[pid] = bought_price + max(0, (cur_price - bought_price) // 2)

            squad_projs = [proj_by_id[pid] for pid in current_squad_ids if pid in proj_by_id]
            # In V0.9, replace squad players with lowest risk-adjusted points
            squad_projs.sort(key=lambda p: p.expected_points * (0.8 + 0.2 * p.start_probability))

            for out_p in squad_projs:
                out_id = out_p.player_id
                available_cash = bank_tenths + selling_prices[out_id]
                cands = [
                    p for p in projections
                    if p.player_id not in squad_set
                    and p.position == out_p.position
                    and p.price_tenths <= available_cash
                    and p.start_probability >= 0.30  # V0.9: reject low-start rotation traps
                ]
                valid_cands = [
                    p for p in cands
                    if p.team_id == out_p.team_id or team_counts.get(p.team_id, 0) < 3
                ]
                if not valid_cands:
                    continue
                valid_cands.sort(key=lambda p: p.expected_points * (0.85 + 0.15 * p.start_probability), reverse=True)
                best_in = valid_cands[0]
                if (best_in.expected_points - out_p.expected_points) >= min_net_gain:
                    return [(out_id, best_in.player_id)]
            return []

        # Production Optimizer Strategy (V0.9 Participation-Aware)
        from ..optimizer import PlayerOptInfo, solve_transfers

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
                is_long_term_unavailable=getattr(p, "is_long_term_unavailable", False),
            )

        squad_set = set(current_squad_ids)
        squad_opt = [opt_map[pid] for pid in current_squad_ids if pid in opt_map]
        # V0.9 Candidate safeguard: Exclude transfer targets who are inactive or doubt traps
        proj_map = {p.player_id: p for p in projections}
        cand_pool = [
            opt for pid, opt in opt_map.items()
            if pid not in squad_set and proj_map.get(pid) and proj_map[pid].play_probability >= 0.35
        ]

        selling_prices = {}
        for pid in current_squad_ids:
            cur_p = opt_map.get(pid)
            cur_price = cur_p.price_tenths if cur_p else 50
            bought = purchase_prices.get(pid, cur_price)
            selling_prices[pid] = bought + max(0, (cur_price - bought) // 2)

        fdr_map = {}
        ticker_map = {}
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
        best_gain = min_net_gain
        k_max = max_transfers if allow_hits else min(max_transfers, free_transfers)
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
                risk_profile=risk_profile,
                max_results=5,
            )
            for rec in recs:
                if not allow_hits and rec.get("hit_cost", 0) > 0:
                    continue
                net_gain = rec.get("score", rec.get("xp_delta", 0.0))
                if net_gain > best_gain:
                    best_gain = net_gain
                    out_list = [p["id"] for p in rec.get("outgoing", [])]
                    in_list = [p["id"] for p in rec.get("incoming", [])]
                    best_moves = list(zip(out_list, in_list))

        return best_moves

    def get_strategy_config(self, strategy_name: str, **kwargs: Any) -> dict[str, Any]:
        cfg = super().get_strategy_config(strategy_name, **kwargs)
        cfg["lineup_penalty_weight"] = self.lineup_penalty_weight
        return cfg


class DecisionEngineV10(DecisionEngineV09):
    """V1.0 Production Decision Engine (Frozen V0.9.1 baseline with lineup_penalty_weight = 0.0).

    Explicitly separates quantitative prediction from the decision objective:
    - Neutral lineup path uses calibrated expected points directly (lineup_penalty_weight = 0.0).
    - Preserves participation signals (P(start), P(sub), P(play), expected_minutes, regime).
    - Enforces captaincy safeguard (P(start) >= 0.60) and play-probability bench ordering.
    """

    def __init__(self, lineup_penalty_weight: float = 0.0) -> None:
        super().__init__(lineup_penalty_weight=lineup_penalty_weight)

    @property
    def version(self) -> str:
        return "v1.0"

    @property
    def name(self) -> str:
        if abs(self.lineup_penalty_weight - 0.0) < 1e-6:
            return "V1.0 Production Decision Engine (Neutral Calibrated xP, w=0.00)"
        return f"V1.0 Production Decision Engine (w={self.lineup_penalty_weight:.2f})"


class DecisionEngineV11(DecisionEngineV10):
    """V1.1 Strategic Decision Engine with multi-objective squad initialization.

    Features:
    - Multi-objective strategic starting squad construction (Initial Squad before GW1).
    - Configurable strategic profile: 'balanced', 'maximum_ev', 'ceiling', 'floor', 'flexibility', etc.
    - Multi-gameweek horizon optimization (default: 5 gameweeks).
    - Full budget feasibility enforcement (strictly <= £100.0m, legal formations, position quotas).
    - Preserves calibrated xP, participation safeguards, and optimal transfer solving.
    """

    def __init__(
        self,
        initial_strategy: str = "balanced",
        initial_horizon: int = 5,
        lineup_penalty_weight: float = 0.0,
    ) -> None:
        super().__init__(lineup_penalty_weight=lineup_penalty_weight)
        self.initial_strategy = initial_strategy
        self.initial_horizon = initial_horizon
        self.fallback_occurred = False
        self.fallback_reason: str | None = None

    @property
    def version(self) -> str:
        return "v1.1"

    @property
    def name(self) -> str:
        return f"V1.1 Strategic Decision Engine ({self.initial_strategy}, horizon={self.initial_horizon} GWs)"

    @property
    def optimizer_implementation(self) -> str:
        return "fpl_manager.strategic_squad.solve_strategic_squad:v1.1"

    def initialize_squad(
        self,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
        budget_tenths: int = 1000,
    ) -> tuple[list[int], dict[int, int], int]:
        """Select ideal initial 15-player squad using V1.1 Strategic Squad Optimizer."""
        from ..strategic_squad import StrategicConstraints, solve_strategic_squad
        from ..suggest_transfers import PlayerInfo

        try:
            proj_map = {p.player_id: p for p in projections}
            candidate_pool = []
            for p in snapshot.players:
                proj = proj_map.get(p.player_id)
                xp = proj.expected_points if proj else 0.0
                xm = proj.expected_minutes if proj else 0.0
                flr = proj.xp_floor if proj and proj.xp_floor > 0 else xp
                ceil = proj.xp_ceiling if proj and proj.xp_ceiling > 0 else xp
                p_info = PlayerInfo(
                    id=p.player_id,
                    name=p.web_name,
                    position=p.position,
                    team_short=next((t.get("short_name", f"T{p.team_id}") for t in snapshot.teams if t["team_id"] == p.team_id), f"T{p.team_id}"),
                    team_id=p.team_id,
                    price_tenths=p.price_tenths,
                    expected_points=xp,
                    gw_xp=xp,
                    horizon_xp=xp * self.initial_horizon,
                    xp_floor=flr,
                    xp_ceiling=ceil,
                    horizon_floor=flr * self.initial_horizon,
                    horizon_ceiling=ceil * self.initial_horizon,
                    expected_minutes=xm,
                    total_points=p.total_points,
                    status=p.status,
                    is_long_term_unavailable=p.is_long_term_unavailable,
                )
                candidate_pool.append(p_info)

            effective_end = min(39, snapshot.gameweek + self.initial_horizon)
            effective_horizon = max(1, effective_end - snapshot.gameweek)
            constraints = StrategicConstraints(
                budget_tenths=budget_tenths,
                target_gameweeks=tuple(range(snapshot.gameweek, effective_end)),
                bench_weight=1.0,
            )
            cand = solve_strategic_squad(
                candidate_pool=candidate_pool,
                constraints=constraints,
                strategy=self.initial_strategy,
                mode="initial" if snapshot.gameweek == 1 else "wildcard",
                horizon=effective_horizon,
                bench_weight=1.0,
            )
            squad_ids = list(cand.player_ids)
            purchase_prices = {p.id: p.price_tenths for p in candidate_pool if p.id in squad_ids}
            bank = max(0, budget_tenths - sum(purchase_prices.values()))
            return squad_ids, purchase_prices, bank
        except Exception as exc:
            self.fallback_occurred = True
            self.fallback_reason = str(exc)
            return super().initialize_squad(snapshot, projections, budget_tenths=budget_tenths)

    def get_strategy_config(self, strategy_name: str, **kwargs: Any) -> dict[str, Any]:
        cfg = super().get_strategy_config(strategy_name, **kwargs)
        cfg["fallback_occurred"] = self.fallback_occurred
        cfg["fallback_reason"] = self.fallback_reason
        return cfg


class DecisionEngineV115(DecisionEngineV11):
    """V1.1.5 Strategic Decision Engine with PL Departure Lifecycle and Dead Capital Prioritization.

    Features:
    - Dead capital offloading: Prioritizes selling departed players via dead capital penalty weight.
    - Buy-side candidate filtering: Guarantees departed players never enter transfer or squad candidate pools.
    - Multi-objective strategic squad initialization with strict departure exclusion.
    - Full provenance and transparent fallback reporting (never silent fallback).
    """

    def __init__(
        self,
        initial_strategy: str = "balanced",
        initial_horizon: int = 5,
        lineup_penalty_weight: float = 0.0,
        dead_capital_weight: float = 3.0,
    ) -> None:
        super().__init__(
            initial_strategy=initial_strategy,
            initial_horizon=initial_horizon,
            lineup_penalty_weight=lineup_penalty_weight,
        )
        self.dead_capital_weight = dead_capital_weight

    def _is_dead_capital(self, player: Any, snapshot: HistoricalGameweekSnapshot) -> bool:
        """Determine whether a player counts as "dead capital" to be prioritized for sale.

        V1.1.5 only ever treats Premier League departures as dead capital (master behavior).
        DecisionEngineV12 overrides this to additionally include long-term unavailability.
        """
        return is_departed_from_premier_league(player, snapshot)

    @property
    def version(self) -> str:
        return "v1.1.5"

    @property
    def name(self) -> str:
        return f"V1.1.5 Strategic Decision Engine ({self.initial_strategy}, horizon={self.initial_horizon} GWs, dead_cap={self.dead_capital_weight})"

    @property
    def optimizer_implementation(self) -> str:
        return "fpl_manager.strategic_squad.solve_strategic_squad:v1.1.5"

    def initialize_squad(
        self,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
        budget_tenths: int = 1000,
    ) -> tuple[list[int], dict[int, int], int]:
        """Select ideal initial 15-player squad strictly excluding any departed players."""
        from ..strategic_squad import StrategicConstraints, solve_strategic_squad
        from ..suggest_transfers import PlayerInfo

        try:
            proj_map = {p.player_id: p for p in projections}
            candidate_pool = []
            for p in snapshot.players:
                # Exclude dead-capital players from candidate pool at squad initialization
                if self._is_dead_capital(p, snapshot):
                    continue
                proj = proj_map.get(p.player_id)
                xp = proj.expected_points if proj else 0.0
                xm = proj.expected_minutes if proj else 0.0
                flr = proj.xp_floor if proj and proj.xp_floor > 0 else xp
                ceil = proj.xp_ceiling if proj and proj.xp_ceiling > 0 else xp
                p_info = PlayerInfo(
                    id=p.player_id,
                    name=p.web_name,
                    position=p.position,
                    team_short=next((t.get("short_name", f"T{p.team_id}") for t in snapshot.teams if t["team_id"] == p.team_id), f"T{p.team_id}"),
                    team_id=p.team_id,
                    price_tenths=p.price_tenths,
                    expected_points=xp,
                    gw_xp=xp,
                    horizon_xp=xp * self.initial_horizon,
                    xp_floor=flr,
                    xp_ceiling=ceil,
                    horizon_floor=flr * self.initial_horizon,
                    horizon_ceiling=ceil * self.initial_horizon,
                    expected_minutes=xm,
                    total_points=p.total_points,
                    status=p.status,
                    is_long_term_unavailable=p.is_long_term_unavailable,
                )
                candidate_pool.append(p_info)

            effective_end = min(39, snapshot.gameweek + self.initial_horizon)
            effective_horizon = max(1, effective_end - snapshot.gameweek)
            constraints = StrategicConstraints(
                budget_tenths=budget_tenths,
                target_gameweeks=tuple(range(snapshot.gameweek, effective_end)),
                bench_weight=1.0,
            )
            cand = solve_strategic_squad(
                candidate_pool=candidate_pool,
                constraints=constraints,
                strategy=self.initial_strategy,
                mode="initial" if snapshot.gameweek == 1 else "wildcard",
                horizon=effective_horizon,
                bench_weight=1.0,
            )
            squad_ids = list(cand.player_ids)
            purchase_prices = {p.id: p.price_tenths for p in candidate_pool if p.id in squad_ids}
            bank = max(0, budget_tenths - sum(purchase_prices.values()))
            return squad_ids, purchase_prices, bank
        except Exception as exc:
            self.fallback_occurred = True
            self.fallback_reason = str(exc)
            return super().initialize_squad(snapshot, projections, budget_tenths=budget_tenths)

    def decide_transfers(
        self,
        strategy_name: str,
        current_squad_ids: list[int],
        purchase_prices: dict[int, int],
        bank_tenths: int,
        free_transfers: int,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
        max_transfers: int = 1,
        allow_hits: bool = True,
        risk_profile: str = "neutral",
        min_net_gain: float = 0.50,
    ) -> list[tuple[int, int]]:
        strat = strategy_name.lower().strip().replace("-", "").replace("_", "").replace(" ", "")
        if "notransfer" in strat:
            return []

        if "simplexp" in strat:
            if free_transfers <= 0:
                return []
            proj_by_id = {p.player_id: p for p in projections}
            squad_set = set(current_squad_ids)
            team_counts: dict[int, int] = {}
            for pid in current_squad_ids:
                p = proj_by_id.get(pid)
                if p:
                    team_counts[p.team_id] = team_counts.get(p.team_id, 0) + 1

            selling_prices: dict[int, int] = {}
            for pid in current_squad_ids:
                p = proj_by_id.get(pid)
                cur_price = p.price_tenths if p else 50
                bought_price = purchase_prices.get(pid, cur_price)
                selling_prices[pid] = bought_price + max(0, (cur_price - bought_price) // 2)

            squad_projs = [proj_by_id[pid] for pid in current_squad_ids if pid in proj_by_id]
            # Prioritize selling dead-capital players first
            squad_projs.sort(
                key=lambda p: (
                    0 if self._is_dead_capital(p, snapshot) else 1,
                    p.expected_points,
                )
            )

            for out_p in squad_projs:
                out_id = out_p.player_id
                available_cash = bank_tenths + selling_prices[out_id]
                cands = [
                    p
                    for p in projections
                    if p.player_id not in squad_set
                    and p.position == out_p.position
                    and p.price_tenths <= available_cash
                    and not self._is_dead_capital(p, snapshot)
                ]
                valid_cands = [
                    p
                    for p in cands
                    if p.team_id == out_p.team_id or team_counts.get(p.team_id, 0) < 3
                ]
                if not valid_cands:
                    continue
                valid_cands.sort(key=lambda p: p.expected_points, reverse=True)
                best_in = valid_cands[0]
                thresh = 0.0 if self._is_dead_capital(out_p, snapshot) else min_net_gain
                if (best_in.expected_points - out_p.expected_points) >= thresh:
                    return [(out_id, best_in.player_id)]
            return []

        # Production Optimizer Strategy with dead capital priority offloading
        from ..optimizer import PlayerOptInfo, solve_transfers

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
                is_long_term_unavailable=getattr(p, "is_long_term_unavailable", False),
            )

        squad_set = set(current_squad_ids)
        squad_opt = [opt_map[pid] for pid in current_squad_ids if pid in opt_map]
        proj_map = {p.player_id: p for p in projections}
        # Strictly exclude dead-capital players from incoming candidates
        cand_pool = [
            opt
            for pid, opt in opt_map.items()
            if pid not in squad_set
            and proj_map.get(pid)
            and proj_map[pid].play_probability >= 0.35
            and not self._is_dead_capital(opt, snapshot)
        ]

        selling_prices = {}
        for pid in current_squad_ids:
            cur_p = opt_map.get(pid)
            cur_price = cur_p.price_tenths if cur_p else 50
            bought = purchase_prices.get(pid, cur_price)
            selling_prices[pid] = bought + max(0, (cur_price - bought) // 2)

        fdr_map = {}
        ticker_map = {}
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
        best_gain = min_net_gain
        k_max = max_transfers if allow_hits else min(max_transfers, free_transfers)
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
                risk_profile=risk_profile,
                max_results=5,
                dead_capital_weight=self.dead_capital_weight,
            )
            for rec in recs:
                if not allow_hits and rec.get("hit_cost", 0) > 0:
                    continue
                net_gain = rec.get("score", rec.get("xp_delta", 0.0))
                if net_gain > best_gain:
                    best_gain = net_gain
                    out_list = [p["id"] for p in rec.get("outgoing", [])]
                    in_list = [p["id"] for p in rec.get("incoming", [])]
                    best_moves = list(zip(out_list, in_list))

        return best_moves

    def get_strategy_config(self, strategy_name: str, **kwargs: Any) -> dict[str, Any]:
        cfg = super().get_strategy_config(strategy_name, **kwargs)
        cfg["dead_capital_weight"] = self.dead_capital_weight
        return cfg


def _evaluate_squad_lineup_xp(squad: list[Any], bench_w: float = 0.15) -> float:
    """Evaluate optimal starting XI and weighted bench score for 15 squad players."""
    by_pos: dict[Position, list[float]] = {pos: [] for pos in Position}
    for p in squad:
        xp = getattr(p, "expected_points", 0.0)
        by_pos[p.position].append(xp)
    for pos in by_pos:
        by_pos[pos].sort(reverse=True)

    gk = by_pos[Position.GOALKEEPER]
    defs = by_pos[Position.DEFENDER]
    mids = by_pos[Position.MIDFIELDER]
    fwds = by_pos[Position.FORWARD]

    if not gk or len(defs) < 3 or len(mids) < 2 or len(fwds) < 1:
        return sum(getattr(p, "expected_points", 0.0) for p in squad)

    total_val = gk[0] + (gk[1] if len(gk) > 1 else 0.0) + sum(defs) + sum(mids) + sum(fwds)
    best_lineup = -float("inf")

    for n_def, n_mid, n_fwd in LEGAL_FORMATIONS:
        if len(defs) < n_def or len(mids) < n_mid or len(fwds) < n_fwd:
            continue
        st_val = gk[0] + sum(defs[:n_def]) + sum(mids[:n_mid]) + sum(fwds[:n_fwd])
        cap_val = max(gk[0], defs[0] if defs else 0.0, mids[0] if mids else 0.0, fwds[0] if fwds else 0.0)
        bench_val = total_val - st_val
        score = st_val + cap_val + bench_w * bench_val
        if score > best_lineup:
            best_lineup = score

    return best_lineup


class _PlayerWithXp:
    __slots__ = ("id", "position", "expected_points")

    def __init__(self, pid: int, position: Position, expected_points: float) -> None:
        self.id = pid
        self.position = position
        self.expected_points = expected_points


def _evaluate_squad_multi_horizon_lineup_xp(
    squad: list[Any],
    projections_by_gw: dict[int, dict[int, float]],
    horizon: int = 3,
    gamma: float = 0.75,
    bench_w: float = 0.15,
) -> float:
    """Evaluate discounted lineup expected points across a rolling multi-gameweek horizon (Pillar 3).

    Delta xP_rolling = sum_{t=0}^{H-1} gamma^t * LineupXP_{GW+t}(S)
    """
    if not squad:
        return 0.0

    if not projections_by_gw:
        return _evaluate_squad_lineup_xp(squad, bench_w=bench_w)

    sorted_gws = sorted(projections_by_gw.keys())[:max(1, horizon)]
    if not sorted_gws:
        return _evaluate_squad_lineup_xp(squad, bench_w=bench_w)

    total_discounted_xp = 0.0

    for t, gw in enumerate(sorted_gws):
        discount = gamma**t
        gw_map = projections_by_gw[gw]
        gw_squad = [
            _PlayerWithXp(
                pid=getattr(p, "id", getattr(p, "player_id", 0)),
                position=p.position,
                expected_points=gw_map.get(
                    getattr(p, "id", getattr(p, "player_id", 0)),
                    getattr(p, "expected_points", 0.0),
                ),
            )
            for p in squad
        ]
        lineup_xp = _evaluate_squad_lineup_xp(gw_squad, bench_w=bench_w)
        total_discounted_xp += discount * lineup_xp

    return total_discounted_xp


_HISTORICAL_FIXTURES_BY_GW_CACHE: dict[Path, dict[int, list[dict[str, Any]]]] = {}
_FIXTURES_BY_SEASON_GW_CACHE: dict[tuple[Path, int], list[dict[str, Any]]] = {}


def _load_historical_fixtures_by_gw(season_dir: Path) -> dict[int, list[dict[str, Any]]]:
    """Load and index all scheduled fixtures by gameweek for a historical season."""
    resolved = season_dir.resolve()
    if resolved in _HISTORICAL_FIXTURES_BY_GW_CACHE:
        return _HISTORICAL_FIXTURES_BY_GW_CACHE[resolved]
    fix_file = resolved / "fixtures.json"
    if not fix_file.exists():
        return {}
    raw_fixtures: list[dict[str, Any]] = json.loads(fix_file.read_text(encoding="utf-8"))
    by_gw: dict[int, list[dict[str, Any]]] = {}
    for fix in raw_fixtures:
        ev = fix.get("event")
        if ev is not None:
            by_gw.setdefault(int(ev), []).append(fix)
    _HISTORICAL_FIXTURES_BY_GW_CACHE[resolved] = by_gw
    return by_gw


def get_historical_fixtures_for_gw(season_dir: Path, gw: int) -> list[dict[str, Any]]:
    """Get fixtures for a specific gameweek with second-level (season_dir, gw) caching."""
    resolved = season_dir.resolve()
    key = (resolved, gw)
    if key in _FIXTURES_BY_SEASON_GW_CACHE:
        return _FIXTURES_BY_SEASON_GW_CACHE[key]
    fixtures_by_gw = _load_historical_fixtures_by_gw(resolved)
    fixes = fixtures_by_gw.get(gw, [])
    _FIXTURES_BY_SEASON_GW_CACHE[key] = fixes
    return fixes


def clear_historical_fixtures_cache() -> None:
    """Clear both fixture cache tiers."""
    _HISTORICAL_FIXTURES_BY_GW_CACHE.clear()
    _FIXTURES_BY_SEASON_GW_CACHE.clear()


def _get_forward_projections(
    snapshot: HistoricalGameweekSnapshot,
    projections: list[ExpectedPointsProjection],
    horizon: int = 3,
    gamma: float = 0.75,
    season_dir: Path | None = None,
    needed_pids: set[int] | None = None,
) -> dict[int, dict[int, float]]:
    """Produce point-in-time expected points projections across a multi-gameweek rolling horizon (Pillar 3).

    Zero-leakage invariant:
    - Current and future gameweek projections are computed strictly using player stats known
      at the gameweek deadline (from `snapshot.players`) and pre-season fixture schedule (`fixtures.json`).
    - Ground truth match outcomes and future event files are NEVER accessed.
    """
    from ..expected_points import DATA_DIRECTORY, project_player_gameweek

    proj_map = {p.player_id: p.expected_points for p in projections}
    projections_by_gw: dict[int, dict[int, float]] = {snapshot.gameweek: proj_map}

    if horizon <= 1 or not snapshot.players:
        return projections_by_gw

    target_gws = [gw for gw in range(snapshot.gameweek + 1, min(39, snapshot.gameweek + horizon))]
    if not target_gws:
        return projections_by_gw

    if season_dir is None:
        season_dir = DATA_DIRECTORY / "historical" / snapshot.season

    if not season_dir.exists():
        return projections_by_gw

    team_map = {t["team_id"]: t.get("short_name", f"T{t['team_id']}") for t in snapshot.teams}

    predictor_version = "v1.0.1"
    if projections and projections[0].model_metadata:
        predictor_version = projections[0].model_metadata.get("predictor_version", "v1.0.1")

    players_to_project = snapshot.players
    if needed_pids is not None:
        players_to_project = tuple(p for p in snapshot.players if p.player_id in needed_pids)

    for gw in target_gws:
        gw_fixes = get_historical_fixtures_for_gw(season_dir, gw)
        gw_projs: dict[int, float] = {}
        for p in players_to_project:
            team_fixes: list[dict[str, Any]] = []
            for f in gw_fixes:
                if f["team_h"] == p.team_id:
                    team_fixes.append({
                        "opponent_id": f["team_a"],
                        "opponent_short": team_map.get(f["team_a"], f"T{f['team_a']}"),
                        "is_home": True,
                        "fdr": f.get("team_h_difficulty", 3),
                    })
                elif f["team_a"] == p.team_id:
                    team_fixes.append({
                        "opponent_id": f["team_h"],
                        "opponent_short": team_map.get(f["team_h"], f"T{f['team_h']}"),
                        "is_home": False,
                        "fdr": f.get("team_a_difficulty", 3),
                    })

            proj = project_player_gameweek(
                player_id=p.player_id,
                web_name=p.web_name,
                position=p.position,
                team_id=p.team_id,
                team_short=team_map.get(p.team_id, f"T{p.team_id}"),
                price_tenths=p.price_tenths,
                status=p.status,
                total_points=p.total_points,
                finished_matches=snapshot.finished_gameweeks,
                gameweek=gw,
                team_fixtures_in_gw=team_fixes,
                minutes=p.minutes,
                starts=p.starts,
                chance_of_playing_next_round=p.chance_of_playing_next_round,
                chance_of_playing_this_round=p.chance_of_playing_this_round,
                expected_goals=p.expected_goals,
                expected_assists=p.expected_assists,
                expected_goal_involvements=p.expected_goal_involvements,
                expected_goals_conceded=p.expected_goals_conceded,
                expected_goals_per_90=p.expected_goals_per_90,
                expected_assists_per_90=p.expected_assists_per_90,
                expected_goals_conceded_per_90=p.expected_goals_conceded_per_90,
                clean_sheets_per_90=p.clean_sheets_per_90,
                bps=p.bps,
                ict_index=p.ict_index,
                starts_last_3=p.starts_last_3,
                starts_last_5=p.starts_last_5,
                minutes_last_3=p.minutes_last_3,
                minutes_last_5=p.minutes_last_5,
                consecutive_zero_mins=p.consecutive_zero_mins,
                predictor_version=predictor_version,
                is_long_term_unavailable=p.is_long_term_unavailable,
            )
            gw_projs[p.player_id] = proj.expected_points

        projections_by_gw[gw] = gw_projs

    return projections_by_gw


class DecisionEngineV12(DecisionEngineV115):
    """V1.2 Strategic Decision Engine with Asymmetric Squad Balancing & Lineup-Aware Transfer Evaluation.

    Features:
    - Pillar 1: Asymmetric Starting XI vs Bench objective weighting (bench_weight=0.15)
      prioritizing high-performing starting premiums over costly substitutes.
    - Pillar 2: Long-Term Unavailability Modeling (multi-month bans and ACL tears)
      with point-in-time registry checks, purchase exclusions, and dead capital recovery.
    - Pillar 3: Lineup-Aware Transfer Planning: candidate transfers are evaluated by their
      impact on Starting XI lineup expected return (new_lineup - old_lineup - hits)
      rather than flat squad sum deltas, preventing wasted transfers on non-playing bench warmers.
    """

    def __init__(
        self,
        initial_strategy: str = "balanced",
        initial_horizon: int = 5,
        lineup_penalty_weight: float = 0.0,
        dead_capital_weight: float = 3.0,
        bench_weight: float = 0.15,
        max_results: int = 5,
    ) -> None:
        super().__init__(
            initial_strategy=initial_strategy,
            initial_horizon=initial_horizon,
            lineup_penalty_weight=lineup_penalty_weight,
            dead_capital_weight=dead_capital_weight,
        )
        self.bench_weight = bench_weight
        self.max_results = max_results

    def _is_dead_capital(self, player: Any, snapshot: HistoricalGameweekSnapshot) -> bool:
        """V1.2 additionally treats long-term unavailable players (multi-month bans, ACL tears) as dead capital."""
        return is_departed_from_premier_league(player, snapshot) or is_long_term_unavailable(player, snapshot)

    @property
    def version(self) -> str:
        return "v1.2"

    @property
    def name(self) -> str:
        return (
            f"V1.2 Strategic Decision Engine ({self.initial_strategy}, "
            f"horizon={self.initial_horizon} GWs, dead_cap={self.dead_capital_weight}, "
            f"bench_w={self.bench_weight})"
        )

    @property
    def optimizer_implementation(self) -> str:
        return "fpl_manager.strategic_squad.solve_strategic_squad:v1.2"

    def initialize_squad(
        self,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
        budget_tenths: int = 1000,
    ) -> tuple[list[int], dict[int, int], int]:
        """Select ideal initial 15-player squad strictly excluding departed and long-term unavailable players,
        optimizing with asymmetric Starting XI vs Bench weighting (bench_weight=0.15).
        """
        from ..strategic_squad import StrategicConstraints, solve_strategic_squad
        from ..suggest_transfers import PlayerInfo

        try:
            proj_map = {p.player_id: p for p in projections}
            candidate_pool = []
            for p in snapshot.players:
                if self._is_dead_capital(p, snapshot):
                    continue
                proj = proj_map.get(p.player_id)
                xp = proj.expected_points if proj else 0.0
                xm = proj.expected_minutes if proj else 0.0
                flr = proj.xp_floor if proj and proj.xp_floor > 0 else xp
                ceil = proj.xp_ceiling if proj and proj.xp_ceiling > 0 else xp
                p_info = PlayerInfo(
                    id=p.player_id,
                    name=p.web_name,
                    position=p.position,
                    team_short=next((t.get("short_name", f"T{p.team_id}") for t in snapshot.teams if t["team_id"] == p.team_id), f"T{p.team_id}"),
                    team_id=p.team_id,
                    price_tenths=p.price_tenths,
                    expected_points=xp,
                    gw_xp=xp,
                    horizon_xp=xp * self.initial_horizon,
                    xp_floor=flr,
                    xp_ceiling=ceil,
                    horizon_floor=flr * self.initial_horizon,
                    horizon_ceiling=ceil * self.initial_horizon,
                    expected_minutes=xm,
                    total_points=p.total_points,
                    status=p.status,
                    is_long_term_unavailable=p.is_long_term_unavailable,
                )
                candidate_pool.append(p_info)

            effective_end = min(39, snapshot.gameweek + self.initial_horizon)
            effective_horizon = max(1, effective_end - snapshot.gameweek)
            constraints = StrategicConstraints(
                budget_tenths=budget_tenths,
                target_gameweeks=tuple(range(snapshot.gameweek, effective_end)),
                bench_weight=self.bench_weight,
            )
            cand = solve_strategic_squad(
                candidate_pool=candidate_pool,
                constraints=constraints,
                strategy=self.initial_strategy,
                mode="initial" if snapshot.gameweek == 1 else "wildcard",
                horizon=effective_horizon,
                bench_weight=self.bench_weight,
            )
            squad_ids = list(cand.player_ids)
            purchase_prices = {p.id: p.price_tenths for p in candidate_pool if p.id in squad_ids}
            bank = max(0, budget_tenths - sum(purchase_prices.values()))
            return squad_ids, purchase_prices, bank
        except Exception as exc:
            self.fallback_occurred = True
            self.fallback_reason = str(exc)
            return super().initialize_squad(snapshot, projections, budget_tenths=budget_tenths)

    def decide_transfers(
        self,
        strategy_name: str,
        current_squad_ids: list[int],
        purchase_prices: dict[int, int],
        bank_tenths: int,
        free_transfers: int,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
        max_transfers: int = 1,
        allow_hits: bool = True,
        risk_profile: str = "neutral",
        min_net_gain: float = 0.50,
    ) -> list[tuple[int, int]]:
        strat = strategy_name.lower().strip().replace("-", "").replace("_", "").replace(" ", "")
        if "notransfer" in strat:
            return []

        if "simplexp" in strat:
            return super().decide_transfers(
                strategy_name=strategy_name,
                current_squad_ids=current_squad_ids,
                purchase_prices=purchase_prices,
                bank_tenths=bank_tenths,
                free_transfers=free_transfers,
                snapshot=snapshot,
                projections=projections,
                max_transfers=max_transfers,
                allow_hits=allow_hits,
                risk_profile=risk_profile,
                min_net_gain=min_net_gain,
            )

        # Production Optimizer Strategy with Lineup-Aware Transfer Evaluation & Dead Capital Offloading
        from ..optimizer import PlayerOptInfo, solve_transfers

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
                is_long_term_unavailable=getattr(p, "is_long_term_unavailable", False),
            )

        squad_set = set(current_squad_ids)
        squad_opt = [opt_map[pid] for pid in current_squad_ids if pid in opt_map]
        proj_map = {p.player_id: p for p in projections}

        # Strictly exclude dead-capital players from incoming candidates
        cand_pool = [
            opt
            for pid, opt in opt_map.items()
            if pid not in squad_set
            and proj_map.get(pid)
            and proj_map[pid].play_probability >= 0.35
            and not self._is_dead_capital(opt, snapshot)
        ]

        selling_prices = {}
        for pid in current_squad_ids:
            cur_p = opt_map.get(pid)
            cur_price = cur_p.price_tenths if cur_p else 50
            bought = purchase_prices.get(pid, cur_price)
            selling_prices[pid] = bought + max(0, (cur_price - bought) // 2)

        fdr_map = {}
        ticker_map = {}
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
        best_gain = min_net_gain
        k_max = max_transfers if allow_hits else min(max_transfers, free_transfers)
        if k_max <= 0:
            return []

        curr_lineup_xp = _evaluate_squad_lineup_xp(squad_opt, bench_w=self.bench_weight)

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
                risk_profile=risk_profile,
                max_results=self.max_results,
                dead_capital_weight=self.dead_capital_weight,
            )
            for rec in recs:
                if not allow_hits and rec.get("hit_cost", 0) > 0:
                    continue

                out_list = [p["id"] for p in rec.get("outgoing", [])]
                in_list = [p["id"] for p in rec.get("incoming", [])]
                out_set = set(out_list)

                # Lineup-Aware Evaluation (Pillar 3)
                if len(squad_opt) == 15:
                    new_squad = [p for p in squad_opt if p.id not in out_set] + [opt_map[pid] for pid in in_list if pid in opt_map]
                    new_lineup_xp = _evaluate_squad_lineup_xp(new_squad, bench_w=self.bench_weight)
                    lineup_delta = round(new_lineup_xp - curr_lineup_xp, 2)
                    hit_pts = rec.get("transfer_hits", 0) * 4
                    fdr_gain = rec.get("fdr_improvement", 0.0)
                    dead_cap_gain = rec.get("dead_capital_bonus", 0.0)
                    net_gain = round(lineup_delta - hit_pts + 0.1 * fdr_gain + dead_cap_gain, 2)
                else:
                    net_gain = rec.get("score", rec.get("xp_delta", 0.0))

                hurdle = self._get_transfer_hurdle(out_list, opt_map, proj_map, min_net_gain)
                if net_gain >= hurdle and net_gain > best_gain:
                    best_gain = net_gain
                    best_moves = list(zip(out_list, in_list))

        return best_moves

    def _get_transfer_hurdle(
        self,
        out_list: list[int],
        opt_map: dict[int, Any],
        proj_map: dict[int, Any],
        min_net_gain: float,
    ) -> float:
        """Derive minimum net gain hurdle for candidate transfer. Defaults to min_net_gain."""
        return min_net_gain

    def get_strategy_config(self, strategy_name: str, **kwargs: Any) -> dict[str, Any]:
        cfg = super().get_strategy_config(strategy_name, **kwargs)
        cfg["bench_weight"] = self.bench_weight
        return cfg


class DecisionEngineV125(DecisionEngineV12):
    """V1.2.5 Strategic Decision Engine with Lineup-Aware Transfer Evaluation Refinements.

    Features:
    - Inherits V1.2 Asymmetric Squad Balancing & Unavailability Modeling.
    - Pillar 1: Candidate Pool Expansion & Direct Lineup Scoring (max_results expansion).
    - Pillar 2: Goalkeeper Churn Suppression & Role-Specific Transfer Hurdles.
    - Pillar 3: Multi-Gameweek Discounted Lineup Horizon (H=3, gamma=0.75).
    - Pillar 4: Double / Blank Gameweek Awareness.
    - Pillar 5: Dynamic Chip-Aware Bench Weighting.
    - Pillar 6: Resolution of Inert Long-Term Unavailability Modeling.
    """

    def __init__(
        self,
        initial_strategy: str = "balanced",
        initial_horizon: int = 5,
        lineup_penalty_weight: float = 0.0,
        dead_capital_weight: float = 3.0,
        bench_weight: float = 0.15,
        max_results: int = 25,
        gk_min_net_gain: float = 3.00,
        outfield_min_net_gain: float = 0.50,
        gk_play_probability_floor: float = 0.50,
        horizon: int = 3,
        gamma: float = 0.75,
    ) -> None:
        super().__init__(
            initial_strategy=initial_strategy,
            initial_horizon=initial_horizon,
            lineup_penalty_weight=lineup_penalty_weight,
            dead_capital_weight=dead_capital_weight,
            bench_weight=bench_weight,
            max_results=max_results,
        )
        self.gk_min_net_gain = gk_min_net_gain
        self.outfield_min_net_gain = outfield_min_net_gain
        self.gk_play_probability_floor = gk_play_probability_floor
        self.horizon = horizon
        self.gamma = gamma

    def _get_transfer_hurdle(
        self,
        out_list: list[int],
        opt_map: dict[int, Any],
        proj_map: dict[int, Any],
        min_net_gain: float,
    ) -> float:
        """Enforce role-specific transfer hurdle (3.0 for healthy GKP at H>=3 vs 0.50 for outfield/injured GKP)."""
        has_gk = any(getattr(opt_map.get(pid), "position", None) == Position.GOALKEEPER for pid in out_list)
        if has_gk:
            gk_insecure = all(
                getattr(proj_map.get(pid), "play_probability", 1.0) < self.gk_play_probability_floor
                for pid in out_list
                if getattr(opt_map.get(pid), "position", None) == Position.GOALKEEPER
            )
            if gk_insecure:
                return max(min_net_gain, self.outfield_min_net_gain)
            hurdle = 3.0 if self.horizon >= 3 else self.gk_min_net_gain
            return max(min_net_gain, hurdle)
        return max(min_net_gain, self.outfield_min_net_gain)

    def initialize_squad(
        self,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
        budget_tenths: int = 1000,
        bench_weight: float | None = None,
        mode: str | None = None,
    ) -> tuple[list[int], dict[int, int], int]:
        """Select ideal initial 15-player squad with dynamic chip-aware bench weighting (Pillar 5)."""
        from ..strategic_squad import StrategicConstraints, solve_strategic_squad
        from ..suggest_transfers import PlayerInfo

        try:
            proj_map = {p.player_id: p for p in projections}
            candidate_pool = []
            eff_bench_weight = bench_weight if bench_weight is not None else self.bench_weight
            eff_mode = mode if mode is not None else ("initial" if snapshot.gameweek == 1 else "wildcard")
            eff_horizon = 1 if eff_mode == "free_hit" else max(1, min(39, snapshot.gameweek + self.initial_horizon) - snapshot.gameweek)

            for p in snapshot.players:
                if self._is_dead_capital(p, snapshot):
                    continue
                proj = proj_map.get(p.player_id)
                xp = proj.expected_points if proj else 0.0
                xm = proj.expected_minutes if proj else 0.0
                flr = proj.xp_floor if proj and proj.xp_floor > 0 else xp
                ceil = proj.xp_ceiling if proj and proj.xp_ceiling > 0 else xp
                p_info = PlayerInfo(
                    id=p.player_id,
                    name=p.web_name,
                    position=p.position,
                    team_short=next((t.get("short_name", f"T{p.team_id}") for t in snapshot.teams if t["team_id"] == p.team_id), f"T{p.team_id}"),
                    team_id=p.team_id,
                    price_tenths=p.price_tenths,
                    expected_points=xp,
                    gw_xp=xp,
                    horizon_xp=xp * eff_horizon,
                    xp_floor=flr,
                    xp_ceiling=ceil,
                    horizon_floor=flr * eff_horizon,
                    horizon_ceiling=ceil * eff_horizon,
                    expected_minutes=xm,
                    total_points=p.total_points,
                    status=p.status,
                    is_long_term_unavailable=p.is_long_term_unavailable,
                )
                candidate_pool.append(p_info)

            target_gws = (snapshot.gameweek,) if eff_mode == "free_hit" else tuple(range(snapshot.gameweek, snapshot.gameweek + eff_horizon))
            constraints = StrategicConstraints(
                budget_tenths=budget_tenths,
                target_gameweeks=target_gws,
                bench_weight=eff_bench_weight,
            )
            cand = solve_strategic_squad(
                candidate_pool=candidate_pool,
                constraints=constraints,
                strategy=self.initial_strategy,
                mode=eff_mode,
                horizon=eff_horizon,
                bench_weight=eff_bench_weight,
            )
            squad_ids = list(cand.player_ids)
            purchase_prices = {p.id: p.price_tenths for p in candidate_pool if p.id in squad_ids}
            bank = max(0, budget_tenths - sum(purchase_prices.values()))
            return squad_ids, purchase_prices, bank
        except Exception as exc:
            self.fallback_occurred = True
            self.fallback_reason = str(exc)
            return super().initialize_squad(snapshot, projections, budget_tenths=budget_tenths)

    def decide_transfers(
        self,
        strategy_name: str,
        current_squad_ids: list[int],
        purchase_prices: dict[int, int],
        bank_tenths: int,
        free_transfers: int,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
        max_transfers: int = 1,
        allow_hits: bool = True,
        risk_profile: str = "neutral",
        min_net_gain: float = 0.50,
        projections_by_gw: dict[int, dict[int, float]] | None = None,
    ) -> list[tuple[int, int]]:
        strat = strategy_name.lower().strip().replace("-", "").replace("_", "").replace(" ", "")
        if "notransfer" in strat:
            return []

        if "simplexp" in strat:
            return super().decide_transfers(
                strategy_name=strategy_name,
                current_squad_ids=current_squad_ids,
                purchase_prices=purchase_prices,
                bank_tenths=bank_tenths,
                free_transfers=free_transfers,
                snapshot=snapshot,
                projections=projections,
                max_transfers=max_transfers,
                allow_hits=allow_hits,
                risk_profile=risk_profile,
                min_net_gain=min_net_gain,
            )

        # Production Optimizer Strategy with Multi-Gameweek Lineup-Aware Evaluation & Dead Capital Offloading
        from ..optimizer import PlayerOptInfo, solve_transfers

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
                is_long_term_unavailable=getattr(p, "is_long_term_unavailable", False),
            )

        squad_set = set(current_squad_ids)
        squad_opt = [opt_map[pid] for pid in current_squad_ids if pid in opt_map]
        proj_map = {p.player_id: p for p in projections}

        cand_pool = [
            opt
            for pid, opt in opt_map.items()
            if pid not in squad_set
            and proj_map.get(pid)
            and proj_map[pid].play_probability >= 0.35
            and not self._is_dead_capital(opt, snapshot)
        ]

        selling_prices = {}
        for pid in current_squad_ids:
            cur_p = opt_map.get(pid)
            cur_price = cur_p.price_tenths if cur_p else 50
            bought = purchase_prices.get(pid, cur_price)
            selling_prices[pid] = bought + max(0, (cur_price - bought) // 2)

        fdr_map = {}
        ticker_map = {}
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
        best_gain = min_net_gain
        k_max = max_transfers if allow_hits else min(max_transfers, free_transfers)
        if k_max <= 0:
            return []

        # Point-in-time multi-gameweek projections (Pillar 3)
        if projections_by_gw is None:
            needed_pids = set(current_squad_ids) | {p.id for p in cand_pool}
            projections_by_gw = _get_forward_projections(
                snapshot=snapshot,
                projections=projections,
                horizon=self.horizon,
                gamma=self.gamma,
                needed_pids=needed_pids,
            )

        curr_lineup_xp = _evaluate_squad_multi_horizon_lineup_xp(
            squad_opt,
            projections_by_gw,
            horizon=self.horizon,
            gamma=self.gamma,
            bench_w=self.bench_weight,
        )

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
                risk_profile=risk_profile,
                max_results=self.max_results,
                dead_capital_weight=self.dead_capital_weight,
            )
            for rec in recs:
                if not allow_hits and rec.get("hit_cost", 0) > 0:
                    continue

                out_list = [p["id"] for p in rec.get("outgoing", [])]
                in_list = [p["id"] for p in rec.get("incoming", [])]
                out_set = set(out_list)

                # Lineup-Aware Multi-Horizon Evaluation (Pillars 1, 2, 3)
                if len(squad_opt) == 15:
                    new_squad = [p for p in squad_opt if p.id not in out_set] + [opt_map[pid] for pid in in_list if pid in opt_map]
                    new_lineup_xp = _evaluate_squad_multi_horizon_lineup_xp(
                        new_squad,
                        projections_by_gw,
                        horizon=self.horizon,
                        gamma=self.gamma,
                        bench_w=self.bench_weight,
                    )
                    lineup_delta = round(new_lineup_xp - curr_lineup_xp, 2)
                    hit_pts = rec.get("transfer_hits", 0) * 4
                    fdr_gain = rec.get("fdr_improvement", 0.0)
                    dead_cap_gain = rec.get("dead_capital_bonus", 0.0)
                    net_gain = round(lineup_delta - hit_pts + 0.1 * fdr_gain + dead_cap_gain, 2)
                else:
                    net_gain = rec.get("score", rec.get("xp_delta", 0.0))

                hurdle = self._get_transfer_hurdle(out_list, opt_map, proj_map, min_net_gain)
                if net_gain >= hurdle and net_gain > best_gain:
                    best_gain = net_gain
                    best_moves = list(zip(out_list, in_list))

        return best_moves

    @property
    def version(self) -> str:
        return "v1.2.5"

    @property
    def name(self) -> str:
        return (
            f"V1.2.5 Strategic Decision Engine ({self.initial_strategy}, "
            f"horizon={self.initial_horizon} GWs, dead_cap={self.dead_capital_weight}, "
            f"bench_w={self.bench_weight}, max_results={self.max_results}, "
            f"roll_h={self.horizon}, gamma={self.gamma})"
        )

    @property
    def optimizer_implementation(self) -> str:
        return "fpl_manager.strategic_squad.solve_strategic_squad:v1.2.5"


def resolve_decision_engine(
    engine_version: str | BaseDecisionEngine = "v0.9",
    initial_strategy: str = "balanced",
    initial_horizon: int = 5,
    dead_capital_weight: float = 3.0,
    bench_weight: float = 0.15,
    gamma: float = 0.75,
) -> BaseDecisionEngine:
    """Instantiate and return the appropriate DecisionEngine implementation."""
    if isinstance(engine_version, BaseDecisionEngine):
        return engine_version

    clean = str(engine_version).lower().strip()
    eff_gamma = gamma
    if "_g" in clean and not clean.endswith("_gw"):
        try:
            parts = clean.split("_g")
            eff_gamma = float(parts[1].split("_")[0])
            clean = parts[0]
        except (ValueError, IndexError):
            pass

    if clean in ("v0.8", "v08"):
        return DecisionEngineV08()
    elif clean in ("v0.9", "v09"):
        return DecisionEngineV09()
    elif clean in ("v1.0", "v10", "v1.0.0", "v1.0.1", "v101", "v0.9.1", "v091"):
        return DecisionEngineV10()
    elif clean in ("v1.1", "v11", "v1.1.0", "strategic"):
        return DecisionEngineV11(initial_strategy=initial_strategy, initial_horizon=initial_horizon)
    elif clean in ("v1.1.5", "v115", "v1.1.5.0"):
        return DecisionEngineV115(
            initial_strategy=initial_strategy,
            initial_horizon=initial_horizon,
            dead_capital_weight=dead_capital_weight,
        )
    elif clean.startswith("v1.1.5_"):
        strat = clean.replace("v1.1.5_", "")
        return DecisionEngineV115(
            initial_strategy=strat,
            initial_horizon=initial_horizon,
            dead_capital_weight=dead_capital_weight,
        )
    elif clean in ("v1.2.5", "v125", "v1.2.5.0", "balanced_v125"):
        return DecisionEngineV125(
            initial_strategy=initial_strategy,
            initial_horizon=initial_horizon,
            dead_capital_weight=dead_capital_weight,
            bench_weight=bench_weight,
            gamma=eff_gamma,
        )
    elif clean.startswith("v1.2.5_"):
        strat = clean.replace("v1.2.5_", "")
        return DecisionEngineV125(
            initial_strategy=strat,
            initial_horizon=initial_horizon,
            dead_capital_weight=dead_capital_weight,
            bench_weight=bench_weight,
            gamma=eff_gamma,
        )
    elif clean in ("v1.2", "v12", "v1.2.0", "balanced_v12"):
        return DecisionEngineV12(
            initial_strategy=initial_strategy,
            initial_horizon=initial_horizon,
            dead_capital_weight=dead_capital_weight,
            bench_weight=bench_weight,
        )
    elif clean.startswith("v1.2_"):
        strat = clean.replace("v1.2_", "")
        return DecisionEngineV12(
            initial_strategy=strat,
            initial_horizon=initial_horizon,
            dead_capital_weight=dead_capital_weight,
            bench_weight=bench_weight,
        )
    elif clean.startswith("v1.1_"):
        strat = clean.replace("v1.1_", "")
        return DecisionEngineV11(initial_strategy=strat, initial_horizon=initial_horizon)
    elif "_w" in clean:
        parts = clean.split("_w")
        base = parts[0].replace(".", "")
        try:
            w_val = float(parts[1])
            if base == "v09":
                return DecisionEngineV09(lineup_penalty_weight=w_val)
            if base == "v10":
                return DecisionEngineV10(lineup_penalty_weight=w_val)
            if base == "v11":
                return DecisionEngineV11(initial_strategy=initial_strategy, initial_horizon=initial_horizon, lineup_penalty_weight=w_val)
            if base == "v115":
                return DecisionEngineV115(
                    initial_strategy=initial_strategy,
                    initial_horizon=initial_horizon,
                    lineup_penalty_weight=w_val,
                    dead_capital_weight=dead_capital_weight,
                )
            if base == "v12":
                return DecisionEngineV12(
                    initial_strategy=initial_strategy,
                    initial_horizon=initial_horizon,
                    lineup_penalty_weight=w_val,
                    dead_capital_weight=dead_capital_weight,
                    bench_weight=bench_weight,
                )
            if base == "v125":
                return DecisionEngineV125(
                    initial_strategy=initial_strategy,
                    initial_horizon=initial_horizon,
                    lineup_penalty_weight=w_val,
                    dead_capital_weight=dead_capital_weight,
                    bench_weight=bench_weight,
                    gamma=eff_gamma,
                )
        except ValueError:
            pass
    raise ValueError(
        f"Unknown decision engine version: '{engine_version}'. Supported: 'v0.8', 'v0.9', 'v1.0', 'v1.1', 'v1.1.5', 'v1.2', 'v1.2.5', 'v0.9_w<float>'"
    )

