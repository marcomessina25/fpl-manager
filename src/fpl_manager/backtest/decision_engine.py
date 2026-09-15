"""Decision Engine implementations and version-controlled abstraction (V0.8 vs V0.9).

Provides explicit separation between the frozen V0.8 heuristic decision engine
and the V0.9 participation-aware decision engine.
"""

from abc import ABC, abstractmethod
from typing import Any

from ..expected_points import ExpectedPointsProjection
from ..historical.models import HistoricalGameweekSnapshot, Position

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


class DecisionEngineV09(BaseDecisionEngine):
    """V0.9 Participation-Aware Decision Engine:

    - Squad Init: Saturation-swap enabled greedy selection.
    - Lineup: Participation-risk adjusted starter valuation (penalizes uncertain starters).
    - Captaincy: Captain requires high start confidence (P(start) >= 0.60) to eliminate 0-min captains.
    - Bench: Outfield bench ordered by expected points weighted by play probability.
    - Transfers: Rejection/discounting of low-start-probability rotation traps.
    """

    @property
    def version(self) -> str:
        return "v0.9"

    @property
    def name(self) -> str:
        return "V0.9 Participation-Aware Decision Engine"

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
        for pos in by_pos:
            by_pos[pos].sort(
                key=lambda p: (
                    p.expected_points * (0.80 + 0.20 * p.start_probability),
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
                proj_map[pid].expected_points * (0.80 + 0.20 * proj_map[pid].start_probability)
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


def resolve_decision_engine(engine_version: str | BaseDecisionEngine = "v0.9") -> BaseDecisionEngine:
    """Instantiate and return the appropriate DecisionEngine implementation."""
    if isinstance(engine_version, BaseDecisionEngine):
        return engine_version

    clean = str(engine_version).lower().strip()
    if clean in ("v0.8", "v08"):
        return DecisionEngineV08()
    elif clean in ("v0.9", "v09"):
        return DecisionEngineV09()
    else:
        raise ValueError(f"Unknown decision engine version: '{engine_version}'. Supported: 'v0.8', 'v0.9'")
