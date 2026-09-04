"""Mathematical optimization engine for FPL Manager V0.3.

Provides high-performance combinatorial solvers for:
1. Multi-transfer recommendations (1, 2, 3, 4+ transfers) using recursive branch-and-bound
   with symmetry breaking, upper-bound heap pruning, budget bounds, and team limits.
2. Wildcard and Free-Hit 15-player squad optimization using greedy feasible initialization,
   1-opt upgrading, and 2-opt cross-position local search with exact FPL constraint validation.
"""

from dataclasses import dataclass
import heapq
import itertools
from pathlib import Path
from typing import Any

from .models import Player, Position
from .rules import validate_starting_lineup, validate_squad

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


@dataclass(frozen=True, slots=True)
class PlayerOptInfo:
    id: int
    name: str
    position: Position
    team_id: int
    team_short: str
    price_tenths: int
    status: str
    total_points: int
    expected_points: float = 0.0
    expected_minutes: float = 0.0
    xp_floor: float = 0.0
    xp_ceiling: float = 0.0
    standard_deviation: float = 0.0


def solve_transfers(
    num_transfers: int,
    squad_players: list[Any],
    candidate_pool: list[Any],
    bank_tenths: int,
    free_transfers: int,
    selling_prices: dict[int, int],
    fdr_map: dict[str, float],
    ticker_map: dict[str, str],
    risk_profile: str = "neutral",
    max_results: int = 15,
    cand_limit: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Find top multi-transfer moves using recursive branch-and-bound search.

    Features:
    - Supports arbitrary K transfers (1, 2, 3, 4+).
    - Eliminates permutation symmetry for multiple outgoing players of the same position.
    - Uses upper-bound pruning against a bounded min-heap of top candidates.
    - Prunes paths that exceed remaining budget or team quota limits.
    """
    if num_transfers < 1:
        raise ValueError("num_transfers must be at least 1.")

    if cand_limit is None:
        if num_transfers == 1:
            cand_limit = 60
        elif num_transfers == 2:
            cand_limit = 45
        elif num_transfers == 3:
            cand_limit = 30
        else:
            cand_limit = 25

    # Group and sort candidates by risk profile
    by_pos: dict[Position, list[Any]] = {pos: [] for pos in Position}
    for p in candidate_pool:
        by_pos[p.position].append(p)

    for pos in by_pos:
        if risk_profile == "floor":
            sort_key = lambda p: (p.xp_floor, p.expected_points, -fdr_map.get(p.team_short, 3.0))
        elif risk_profile == "ceiling":
            sort_key = lambda p: (p.xp_ceiling, p.expected_points, -fdr_map.get(p.team_short, 3.0))
        else:
            sort_key = lambda p: (p.expected_points, p.total_points, -fdr_map.get(p.team_short, 3.0))

        by_pos[pos].sort(key=sort_key, reverse=True)
        by_pos[pos] = by_pos[pos][:cand_limit]

    base_team_counts: dict[int, int] = {}
    for p in squad_players:
        base_team_counts[p.team_id] = base_team_counts.get(p.team_id, 0) + 1

    transfer_hits = max(0, num_transfers - free_transfers) * 4

    min_price: dict[Position, int] = {}
    max_metric: dict[Position, float] = {}
    for pos in Position:
        cands = by_pos[pos]
        min_price[pos] = min((p.price_tenths for p in cands), default=0)
        if not cands:
            max_metric[pos] = 0.0
        else:
            top_p = cands[0]
            top_fdr_term = 0.1 * (3.0 - fdr_map.get(top_p.team_short, 3.0))
            if risk_profile == "floor":
                max_metric[pos] = top_p.xp_floor + top_fdr_term
            elif risk_profile == "ceiling":
                max_metric[pos] = top_p.xp_ceiling + top_fdr_term
            else:
                max_metric[pos] = top_p.expected_points + top_fdr_term

    heap: list[tuple[float, float, int, int, dict[str, Any]]] = []
    entry_counter = [0]
    total_evaluated = [0]

    def add_result(score: float, fdr_delta: float, points_delta: int, payload: dict[str, Any]) -> None:
        total_evaluated[0] += 1
        item = (score, fdr_delta, points_delta, entry_counter[0], payload)
        entry_counter[0] += 1
        if len(heap) < max_results:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heappushpop(heap, item)

    out_combos = list(itertools.combinations(squad_players, num_transfers))

    for out_combo in out_combos:
        out_sell_sum = sum(selling_prices[p.id] for p in out_combo)
        max_budget = bank_tenths + out_sell_sum

        # Sort out_combo by position canonically to match picked candidates by position
        sorted_out_combo = sorted(out_combo, key=lambda p: p.position.value)
        req_positions = [p.position for p in sorted_out_combo]

        # Quick feasibility check: can budget afford cheapest candidates?
        if sum(min_price[pos] for pos in req_positions) > max_budget:
            continue

        temp_team_counts = dict(base_team_counts)
        for p in out_combo:
            temp_team_counts[p.team_id] -= 1

        out_xp = sum(p.expected_points for p in out_combo)
        out_floor = sum(p.xp_floor for p in out_combo)
        out_ceil = sum(p.xp_ceiling for p in out_combo)
        out_pts = sum(p.total_points for p in out_combo)
        out_fdr_sum = sum(fdr_map.get(p.team_short, 3.0) for p in out_combo)
        out_fdr_avg = out_fdr_sum / num_transfers

        out_baseline = out_floor if risk_profile == "floor" else (out_ceil if risk_profile == "ceiling" else out_xp)

        def dfs(
            slot: int,
            start_idx: int,
            curr_price: int,
            curr_xp: float,
            curr_floor: float,
            curr_ceil: float,
            curr_pts: int,
            curr_fdr_sum: float,
            picked: list[Any],
        ) -> None:
            if slot == num_transfers:
                in_fdr_avg = curr_fdr_sum / num_transfers
                fdr_delta = round(out_fdr_avg - in_fdr_avg, 2)
                points_delta = curr_pts - out_pts
                xp_delta = round(curr_xp - out_xp, 2)
                floor_delta = round(curr_floor - out_floor, 2)
                ceil_delta = round(curr_ceil - out_ceil, 2)

                if risk_profile == "floor":
                    rank_metric = floor_delta - transfer_hits
                elif risk_profile == "ceiling":
                    rank_metric = ceil_delta - transfer_hits
                else:
                    rank_metric = xp_delta - transfer_hits

                score = round(rank_metric + 0.1 * fdr_delta, 2)
                bank_after = max_budget - curr_price

                add_result(score, fdr_delta, points_delta, {
                    "type": f"{num_transfers}-transfer",
                    "outgoing": [
                        {
                            "id": p.id,
                            "name": p.name,
                            "position": p.position.name,
                            "team": p.team_short,
                            "selling_price_fmt": f"£{selling_prices[p.id] / 10:.1f}m",
                            "xp": p.expected_points,
                            "floor": p.xp_floor,
                            "ceiling": p.xp_ceiling,
                            "expected_minutes": p.expected_minutes,
                        }
                        for p in sorted_out_combo
                    ],
                    "incoming": [
                        {
                            "id": p.id,
                            "name": p.name,
                            "position": p.position.name,
                            "team": p.team_short,
                            "price_fmt": f"£{p.price_tenths / 10:.1f}m",
                            "price_tenths": p.price_tenths,
                            "ticker": ticker_map.get(p.team_short, ""),
                            "xp": p.expected_points,
                            "floor": p.xp_floor,
                            "ceiling": p.xp_ceiling,
                            "expected_minutes": p.expected_minutes,
                        }
                        for p in picked
                    ],
                    "bank_after_fmt": f"£{bank_after / 10:.1f}m",
                    "bank_after_tenths": bank_after,
                    "xp_delta": xp_delta,
                    "floor_delta": floor_delta,
                    "ceiling_delta": ceil_delta,
                    "fdr_improvement": fdr_delta,
                    "points_delta": points_delta,
                    "transfer_hits": transfer_hits,
                    "score": score,
                })
                return

            pos = req_positions[slot]
            cands = by_pos[pos]
            rem_min = sum(min_price[req_positions[s]] for s in range(slot + 1, num_transfers))
            rem_max = sum(max_metric[req_positions[s]] for s in range(slot + 1, num_transfers))

            for idx in range(start_idx, len(cands)):
                cand = cands[idx]
                if curr_price + cand.price_tenths + rem_min > max_budget:
                    continue
                if temp_team_counts.get(cand.team_id, 0) >= 3:
                    continue

                # Upper-bound pruning: stop expanding if this branch cannot beat current heap worst
                if len(heap) == max_results:
                    cand_term = cand.xp_floor if risk_profile == "floor" else (cand.xp_ceiling if risk_profile == "ceiling" else cand.expected_points)
                    curr_term = curr_floor if risk_profile == "floor" else (curr_ceil if risk_profile == "ceiling" else curr_xp)
                    est_in_metric = curr_term + cand_term + rem_max
                    est_score = (est_in_metric - out_baseline) - transfer_hits + 0.5
                    if est_score <= heap[0][0]:
                        break

                temp_team_counts[cand.team_id] = temp_team_counts.get(cand.team_id, 0) + 1
                picked.append(cand)

                # Symmetry breaking: if next slot is for the same position, candidate index must be strictly greater
                next_start = idx + 1 if (slot + 1 < num_transfers and req_positions[slot + 1] == pos) else 0

                dfs(
                    slot + 1,
                    next_start,
                    curr_price + cand.price_tenths,
                    curr_xp + cand.expected_points,
                    curr_floor + cand.xp_floor,
                    curr_ceil + cand.xp_ceiling,
                    curr_pts + cand.total_points,
                    curr_fdr_sum + fdr_map.get(cand.team_short, 3.0),
                    picked,
                )

                picked.pop()
                temp_team_counts[cand.team_id] -= 1

        dfs(0, 0, 0, 0.0, 0.0, 0.0, 0, 0.0, [])

    sorted_heap = sorted(heap, reverse=True)
    top_results = [item[4] for item in sorted_heap]
    return top_results, total_evaluated[0]


def solve_wildcard(
    candidate_pool: list[Any],
    budget_tenths: int = 1000,
    risk_profile: str = "neutral",
    bench_weight: float = 0.1,
) -> dict[str, Any]:
    """Select optimal 15-player squad (Wildcard / Free-Hit) under budget and team constraints.

    Uses a three-stage mathematical heuristic:
    1. Feasible Initial Squad: Selects lowest-cost active players across positions (guaranteed budget compliance).
    2. 1-Opt Upgrading: Repeatedly replaces players with highest marginal gain (xP/risk) within available budget.
    3. 2-Opt Local Search: Evaluates pairwise swaps across positions to rebalance budget across the pitch.
    4. Optimal Starting XI & Lineup: Evaluates the 8 legal FPL formations to select the 11 starters,
       captain, vice-captain, and ordered bench.
    """
    active_players = [p for p in candidate_pool if p.status in ("a", "d")]
    by_pos: dict[Position, list[Any]] = {pos: [] for pos in Position}
    for p in active_players:
        by_pos[p.position].append(p)

    def player_value(p: Any) -> float:
        if risk_profile == "floor":
            return p.xp_floor
        elif risk_profile == "ceiling":
            return p.xp_ceiling
        return p.expected_points

    # Stage 1: Build initial cheap valid squad
    squad: list[Any] = []
    t_counts: dict[int, int] = {}
    for pos, req in [
        (Position.GOALKEEPER, 2),
        (Position.DEFENDER, 5),
        (Position.MIDFIELDER, 5),
        (Position.FORWARD, 3),
    ]:
        sorted_cheap = sorted(
            by_pos[pos],
            key=lambda p: (p.price_tenths, t_counts.get(p.team_id, 0), -player_value(p)),
        )
        count = 0
        for p in sorted_cheap:
            if t_counts.get(p.team_id, 0) < 3:
                t_counts[p.team_id] = t_counts.get(p.team_id, 0) + 1
                squad.append(p)
                count += 1
                if count == req:
                    break
        if count < req:
            for p in by_pos[pos]:
                if p not in squad and t_counts.get(p.team_id, 0) < 3:
                    t_counts[p.team_id] = t_counts.get(p.team_id, 0) + 1
                    squad.append(p)
                    count += 1
                    if count == req:
                        break

    if len(squad) != 15:
        raise RuntimeError("Failed to build a valid 15-player initial squad from candidate pool.")

    cost = sum(p.price_tenths for p in squad)
    squad_ids = {p.id for p in squad}

    # Stage 2: 1-opt greedy upgrading
    improved = True
    while improved:
        improved = False
        best_swap = None
        best_gain = 0.0

        for i, curr_p in enumerate(squad):
            curr_val = player_value(curr_p)
            for cand in by_pos[curr_p.position]:
                if cand.id in squad_ids:
                    continue
                delta_cost = cand.price_tenths - curr_p.price_tenths
                if cost + delta_cost > budget_tenths:
                    continue
                if cand.team_id != curr_p.team_id and t_counts.get(cand.team_id, 0) >= 3:
                    continue
                delta_val = player_value(cand) - curr_val
                if delta_val > best_gain:
                    best_gain = delta_val
                    best_swap = (i, curr_p, cand, delta_cost)

        if best_swap:
            i, curr_p, cand, delta_cost = best_swap
            squad_ids.remove(curr_p.id)
            squad_ids.add(cand.id)
            t_counts[curr_p.team_id] -= 1
            t_counts[cand.team_id] = t_counts.get(cand.team_id, 0) + 1
            squad[i] = cand
            cost += delta_cost
            improved = True

    # Stage 3: 2-opt cross-position local search
    cands_pos = {
        pos: sorted(by_pos[pos], key=player_value, reverse=True)[:25]
        for pos in Position
    }

    improved_2opt = True
    rounds = 0
    while improved_2opt and rounds < 10:
        improved_2opt = False
        rounds += 1
        best_2swap = None
        best_2gain = 0.0

        for i in range(len(squad)):
            for j in range(i + 1, len(squad)):
                p1, p2 = squad[i], squad[j]
                t_counts[p1.team_id] -= 1
                t_counts[p2.team_id] -= 1
                base_cost = cost - p1.price_tenths - p2.price_tenths
                base_val = player_value(p1) + player_value(p2)

                for c1 in cands_pos[p1.position]:
                    if c1.id in squad_ids and c1.id not in (p1.id, p2.id):
                        continue
                    if t_counts.get(c1.team_id, 0) >= 3:
                        continue
                    t_counts[c1.team_id] = t_counts.get(c1.team_id, 0) + 1

                    for c2 in cands_pos[p2.position]:
                        if c2.id in squad_ids and c2.id not in (p1.id, p2.id):
                            continue
                        if c1.id == c2.id:
                            continue
                        if t_counts.get(c2.team_id, 0) >= 3:
                            continue
                        new_cost = base_cost + c1.price_tenths + c2.price_tenths
                        if new_cost > budget_tenths:
                            continue
                        gain = (player_value(c1) + player_value(c2)) - base_val
                        if gain > best_2gain:
                            best_2gain = gain
                            best_2swap = (i, j, p1, p2, c1, c2, new_cost)

                    t_counts[c1.team_id] -= 1

                t_counts[p1.team_id] += 1
                t_counts[p2.team_id] += 1

        if best_2swap:
            i, j, p1, p2, c1, c2, new_cost = best_2swap
            squad_ids.remove(p1.id)
            squad_ids.remove(p2.id)
            squad_ids.add(c1.id)
            squad_ids.add(c2.id)
            t_counts[p1.team_id] -= 1
            t_counts[p2.team_id] -= 1
            t_counts[c1.team_id] = t_counts.get(c1.team_id, 0) + 1
            t_counts[c2.team_id] = t_counts.get(c2.team_id, 0) + 1
            squad[i] = c1
            squad[j] = c2
            cost = new_cost
            improved_2opt = True

    # Rule verification of the 15-man squad
    squad_rules = [
        Player(
            id=p.id,
            name=p.name,
            position=p.position,
            team_id=p.team_id,
            price_tenths=p.price_tenths,
        )
        for p in squad
    ]
    squad_validation = validate_squad(squad_rules, budget_tenths=budget_tenths)
    if not squad_validation.is_valid:
        raise RuntimeError(f"Optimized squad failed rules: {'; '.join(squad_validation.errors)}")

    # Stage 4: Optimal Lineup & Captain Selection
    squad_by_pos: dict[Position, list[Any]] = {pos: [] for pos in Position}
    for p in squad:
        squad_by_pos[p.position].append(p)

    for pos in squad_by_pos:
        squad_by_pos[pos].sort(key=player_value, reverse=True)

    best_score = -float("inf")
    best_formation = "3-4-3"
    best_starters: list[Any] = []
    best_bench: list[Any] = []

    for n_def, n_mid, n_fwd in LEGAL_FORMATIONS:
        st_gk = squad_by_pos[Position.GOALKEEPER][:1]
        st_def = squad_by_pos[Position.DEFENDER][:n_def]
        st_mid = squad_by_pos[Position.MIDFIELDER][:n_mid]
        st_fwd = squad_by_pos[Position.FORWARD][:n_fwd]
        starters = st_gk + st_def + st_mid + st_fwd
        starters_val = sum(player_value(p) for p in starters)

        cap_p = sorted(starters, key=player_value, reverse=True)[0]
        cap_val = player_value(cap_p)

        bench_gk = squad_by_pos[Position.GOALKEEPER][1:2]
        bench_outfield = (
            squad_by_pos[Position.DEFENDER][n_def:]
            + squad_by_pos[Position.MIDFIELDER][n_mid:]
            + squad_by_pos[Position.FORWARD][n_fwd:]
        )
        bench_outfield.sort(key=player_value, reverse=True)
        bench = bench_gk + bench_outfield
        bench_val = sum(player_value(p) for p in bench)

        lineup_score = starters_val + cap_val + bench_weight * bench_val
        if lineup_score > best_score:
            best_score = lineup_score
            best_formation = f"{n_def}-{n_mid}-{n_fwd}"
            best_starters = starters
            best_bench = bench

    starter_ids = [p.id for p in best_starters]
    lineup_validation = validate_starting_lineup(squad_rules, starter_ids)
    if not lineup_validation.is_valid:
        raise RuntimeError(f"Optimized lineup failed rules: {'; '.join(lineup_validation.errors)}")

    sorted_starters = sorted(best_starters, key=player_value, reverse=True)
    captain = sorted_starters[0]
    vice_captain = sorted_starters[1]

    starters_xp = round(sum(p.expected_points for p in best_starters), 2)
    captain_bonus = round(captain.expected_points, 2)
    total_lineup_xp = round(starters_xp + captain_bonus, 2)
    lineup_floor = round(sum(p.xp_floor for p in best_starters) + captain.xp_floor, 2)
    lineup_ceiling = round(sum(p.xp_ceiling for p in best_starters) + captain.xp_ceiling, 2)

    def serialize_p(p: Any, role: str) -> dict[str, Any]:
        return {
            "id": p.id,
            "name": p.name,
            "position": p.position.name,
            "pos_abbr": {
                Position.GOALKEEPER: "GKP",
                Position.DEFENDER: "DEF",
                Position.MIDFIELDER: "MID",
                Position.FORWARD: "FWD",
            }.get(p.position, "MID"),
            "team": p.team_short,
            "price_fmt": f"£{p.price_tenths / 10:.1f}m",
            "price_tenths": p.price_tenths,
            "status": p.status,
            "role": role,
            "expected_points": p.expected_points,
            "xp_floor": p.xp_floor,
            "xp_ceiling": p.xp_ceiling,
            "expected_minutes": p.expected_minutes,
        }

    starters_serialized = []
    for p in best_starters:
        role = "CAPTAIN" if p.id == captain.id else ("VICE_CAPTAIN" if p.id == vice_captain.id else "STARTER")
        starters_serialized.append(serialize_p(p, role))

    bench_serialized = []
    for idx, p in enumerate(best_bench):
        role = "GK_SUB" if idx == 0 else f"BENCH_{idx}"
        bench_serialized.append(serialize_p(p, role))

    squad_xp = round(sum(p.expected_points for p in squad), 2)
    squad_floor = round(sum(p.xp_floor for p in squad), 2)
    squad_ceiling = round(sum(p.xp_ceiling for p in squad), 2)

    return {
        "formation": best_formation,
        "risk_profile": risk_profile,
        "budget_limit_tenths": budget_tenths,
        "total_cost_tenths": cost,
        "bank_remaining_tenths": budget_tenths - cost,
        "total_cost_fmt": f"£{cost / 10:.1f}m",
        "bank_remaining_fmt": f"£{(budget_tenths - cost) / 10:.1f}m",
        "squad_xp": squad_xp,
        "squad_floor": squad_floor,
        "squad_ceiling": squad_ceiling,
        "lineup_starters_xp": starters_xp,
        "captain_bonus_xp": captain_bonus,
        "total_lineup_xp": total_lineup_xp,
        "lineup_floor": lineup_floor,
        "lineup_ceiling": lineup_ceiling,
        "captain": serialize_p(captain, "CAPTAIN"),
        "vice_captain": serialize_p(vice_captain, "VICE_CAPTAIN"),
        "starters": starters_serialized,
        "bench": bench_serialized,
        "squad": [serialize_p(p, "SQUAD") for p in squad],
    }
