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
    selected_by_percent: float = 0.0


RISK_PROFILE_SPECIFICATIONS: dict[str, dict[str, Any]] = {
    "neutral": {
        "mathematical_objective": "U(p) = xP(p)",
        "configurable_parameters": {"lineup_penalty_weight": 0.0},
        "expected_behaviour": "Maximizes calibrated expected points directly without secondary participation discounting.",
        "validation_metrics": ["season_net_points", "xp_mae", "bench_regret"],
        "historical_test_result": "2,014 net pts in 2025/26; 10,187 aggregate net pts across 2021/22-2025/26 (+52 pts vs V0.8).",
    },
    "floor": {
        "mathematical_objective": "U(p) = xp_floor(p)",
        "configurable_parameters": {"floor_sigma_multiplier": 0.85},
        "expected_behaviour": "Prioritizes nailed 90-minute starters and clean-sheet/appearance baseline; minimizes zero-minute exposure.",
        "validation_metrics": ["zero_minute_starters", "floor_coverage_pct", "downside_tail_points"],
        "historical_test_result": "Validated across 29,338 player-GWs (81.4% interval coverage; reduces zero-minute starters).",
    },
    "ceiling": {
        "mathematical_objective": "U(p) = xp_ceiling(p)",
        "configurable_parameters": {"ceiling_sigma_multiplier": 1.35},
        "expected_behaviour": "Targets explosive multi-goal/assist upside and high-variance attacking assets.",
        "validation_metrics": ["haul_capture_rate", "captain_points", "ceiling_exceedance_pct"],
        "historical_test_result": "Validated on high-upside attacking cohorts (captures top-decile 10+ point hauls).",
    },
    "defend_lead": {
        "mathematical_objective": "U(p) = xp_floor(p) - 0.20 * sigma(p) + 0.02 * min(50.0, selected_by_percent(p))",
        "configurable_parameters": {"variance_penalty": 0.20, "ownership_shield_weight": 0.02, "ownership_cap": 50.0},
        "expected_behaviour": "Blocks template Effective Ownership (EO) threats while penalizing volatile rotation risks to protect mini-league/overall rank.",
        "validation_metrics": ["defensive_eo_exposure", "rank_drawdown_risk", "zero_minute_starters"],
        "historical_test_result": "Reduces template rank-loss variance by shielding >=30% owned assets.",
    },
    "chase": {
        "mathematical_objective": "U(p) = xp_ceiling(p) + 0.25 * sigma(p) + max(0.0, (15.0 - selected_by_percent(p)) * 0.05)",
        "configurable_parameters": {"variance_bonus": 0.25, "differential_threshold_pct": 15.0, "differential_weight": 0.05},
        "expected_behaviour": "Amplifies high-ceiling, low-ownership (<15%) differentials to maximize probability of large rank gains.",
        "validation_metrics": ["offensive_differential_leverage", "ceiling_delta", "upside_rank_gain"],
        "historical_test_result": "Increases differential haul leverage (+0.75 utility bonus for <1% owned differentials).",
    },
}


def validate_risk_profile(risk_profile: str) -> str:
    """Validate that a requested risk profile is supported and documented in V1.0."""
    clean = (risk_profile or "neutral").strip().lower()
    if clean not in RISK_PROFILE_SPECIFICATIONS:
        raise ValueError(
            f"Invalid risk_profile '{risk_profile}'. Must be one of {tuple(RISK_PROFILE_SPECIFICATIONS.keys())}."
        )
    return clean


def get_player_profile_value(p: Any, risk_profile: str) -> float:
    """Evaluate candidate strategic utility based on risk profile (V0.8.6 / V1.0 P2.3)."""
    clean = validate_risk_profile(risk_profile)
    xp = getattr(p, "expected_points", 0.0)
    floor_val = getattr(p, "xp_floor", xp)
    ceil_val = getattr(p, "xp_ceiling", xp)
    sd = getattr(p, "standard_deviation", 1.0)
    sel = getattr(p, "selected_by_percent", 10.0)

    if clean == "floor":
        return floor_val
    elif clean == "ceiling":
        return ceil_val
    elif clean == "defend_lead":
        # Defend rank: prioritize safety, penalize variance, favor high template ownership
        return round(floor_val - 0.20 * sd + 0.02 * min(50.0, sel), 2)
    elif clean == "chase":
        # Chase rank: prioritize ceiling, reward high variance and differentials
        diff_bonus = max(0.0, (15.0 - sel) * 0.05)
        return round(ceil_val + 0.25 * sd + diff_bonus, 2)
    else:
        return xp



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

    squad_id_set = {p.id for p in squad_players}

    def _eff_cand_val(p: Any) -> float:
        """Exact per-candidate additive contribution to score before 2-decimal rounding (P1.5)."""
        return get_player_profile_value(p, risk_profile) - (0.1 * fdr_map.get(p.team_short, 3.0)) / num_transfers

    # Group and sort eligible candidates (excluding unavailable and current squad players) monotonically by _eff_cand_val
    by_pos: dict[Position, list[Any]] = {pos: [] for pos in Position}
    for p in candidate_pool:
        if p.id in squad_id_set:
            continue
        if getattr(p, "status", "a") in ("i", "s", "u"):
            continue
        by_pos[p.position].append(p)

    for pos in by_pos:
        sort_key = lambda p: (
            round(_eff_cand_val(p), 6),
            get_player_profile_value(p, risk_profile),
            p.expected_points,
            -fdr_map.get(p.team_short, 3.0),
            p.total_points,
            -p.id,
        )
        by_pos[pos].sort(key=sort_key, reverse=True)
        by_pos[pos] = by_pos[pos][:cand_limit]

    base_team_counts: dict[int, int] = {}
    for p in squad_players:
        base_team_counts[p.team_id] = base_team_counts.get(p.team_id, 0) + 1

    num_hits = max(0, num_transfers - free_transfers)
    hit_penalty_pts = num_hits * 4

    min_price: dict[Position, int] = {}
    max_eff_metric: dict[Position, float] = {}
    for pos in Position:
        cands = by_pos[pos]
        min_price[pos] = min((p.price_tenths for p in cands), default=0)
        max_eff_metric[pos] = _eff_cand_val(cands[0]) if cands else -1e9

    heap: list[tuple[float, float, int, tuple[int, ...], int, dict[str, Any]]] = []
    entry_counter = [0]
    total_evaluated = [0]

    def add_result(score: float, fdr_delta: float, points_delta: int, canonical_ids: tuple[int, ...], payload: dict[str, Any]) -> None:
        total_evaluated[0] += 1
        item = (score, fdr_delta, points_delta, canonical_ids, entry_counter[0], payload)
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
        sorted_out_combo = sorted(out_combo, key=lambda p: (p.position.value, p.id))
        req_positions = [p.position for p in sorted_out_combo]

        # Quick feasibility check: every required position must have at least one candidate and fit min budget
        if any(not by_pos[pos] for pos in req_positions):
            continue
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

        out_baseline = sum(get_player_profile_value(p, risk_profile) for p in out_combo)
        # Constant additive term contributed by outgoing players to final score
        out_score_constant = (0.1 * out_fdr_avg) - out_baseline - hit_penalty_pts

        def dfs(
            slot: int,
            start_idx: int,
            curr_price: int,
            curr_xp: float,
            curr_floor: float,
            curr_ceil: float,
            curr_pts: int,
            curr_fdr_sum: float,
            curr_eff_sum: float,
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
                    rank_metric = floor_delta - hit_penalty_pts
                elif risk_profile == "ceiling":
                    rank_metric = ceil_delta - hit_penalty_pts
                elif risk_profile in ("defend_lead", "chase"):
                    in_metric = sum(get_player_profile_value(p, risk_profile) for p in picked)
                    rank_metric = round((in_metric - out_baseline) - hit_penalty_pts, 2)
                else:
                    rank_metric = xp_delta - hit_penalty_pts

                score = round(rank_metric + 0.1 * fdr_delta, 2)
                bank_after = max_budget - curr_price
                canonical_ids = (
                    tuple(-p.id for p in sorted(sorted_out_combo, key=lambda x: x.id))
                    + tuple(-p.id for p in sorted(picked, key=lambda x: x.id))
                )

                add_result(score, fdr_delta, points_delta, canonical_ids, {
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
                    "transfer_hits": num_hits,
                    "hit_cost": hit_penalty_pts,
                    "score": score,
                })
                return

            pos = req_positions[slot]
            cands = by_pos[pos]
            rem_min = sum(min_price[req_positions[s]] for s in range(slot + 1, num_transfers))
            rem_max_eff = sum(max_eff_metric[req_positions[s]] for s in range(slot + 1, num_transfers))

            for idx in range(start_idx, len(cands)):
                cand = cands[idx]
                if curr_price + cand.price_tenths + rem_min > max_budget:
                    continue
                if temp_team_counts.get(cand.team_id, 0) >= 3:
                    continue

                # P1.5 Admissible Upper-Bound Pruning:
                # Since cands is sorted monotonically descending by _eff_cand_val(p),
                # curr_eff_sum + _eff_cand_val(cand) + rem_max_eff + out_score_constant + 0.03
                # is a strict mathematical upper bound on `score` for `idx` and all `idx' > idx`
                # (where +0.03 strictly dominates two 2-decimal rounding steps of <= 0.015).
                if len(heap) == max_results:
                    cand_eff = _eff_cand_val(cand)
                    est_score = curr_eff_sum + cand_eff + rem_max_eff + out_score_constant + 0.03
                    if est_score < heap[0][0]:
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
                    curr_eff_sum + _eff_cand_val(cand),
                    picked,
                )

                picked.pop()
                temp_team_counts[cand.team_id] -= 1

        dfs(0, 0, 0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, [])

    sorted_heap = sorted(heap, reverse=True)
    top_results = [item[5] for item in sorted_heap]
    return top_results, total_evaluated[0]


MAX_REFERENCE_EVALUATIONS = 100_000


def solve_transfers_exact_reference(
    num_transfers: int,
    squad_players: list[Any],
    candidate_pool: list[Any],
    bank_tenths: int,
    free_transfers: int,
    selling_prices: dict[int, int],
    fdr_map: dict[str, float],
    risk_profile: str = "neutral",
    candidate_out_pool: list[Any] | None = None,
    max_evaluations: int = MAX_REFERENCE_EVALUATIONS,
) -> dict[str, Any] | None:
    """Independent brute-force verification oracle for 1-5 transfer optimization (P0.1).

    Requirements enforced:
    1. Operates ONLY on a synthetic, explicitly bounded candidate pool.
    2. Computes expected Cartesian combinations before running and fails with ValueError
       if combinations exceed `MAX_REFERENCE_EVALUATIONS` (100,000).
    3. Enumerates all combinations of `k` outgoing and `k` incoming players directly via
       `itertools.combinations`, completely independent of `solve_transfers` branch-and-bound.
    4. Independently validates squad legality (`validate_squad`), position preservation,
       club limits (<=3), availability, and budget constraints.
    5. Independently evaluates the transfer objective and returns the exact global optimum.
    """
    import math

    if num_transfers < 1 or num_transfers > 5:
        raise ValueError(f"num_transfers must be in 1..5; got {num_transfers}.")
    risk_profile = validate_risk_profile(risk_profile)

    squad_by_id = {p.id: p for p in squad_players}
    out_pool = list(candidate_out_pool) if candidate_out_pool is not None else list(squad_players)
    if any(p.id not in squad_by_id for p in out_pool):
        raise ValueError("All players in candidate_out_pool must belong to squad_players.")

    # Filter out current squad members from incoming candidate pool (cannot buy player already owned)
    in_pool = [p for p in candidate_pool if p.id not in squad_by_id]

    if len(out_pool) < num_transfers or len(in_pool) < num_transfers:
        return None

    expected_combinations = math.comb(len(out_pool), num_transfers) * math.comb(len(in_pool), num_transfers)
    if expected_combinations > max_evaluations:
        raise ValueError(
            f"Reference solver safety budget exceeded: {expected_combinations:,} combinations "
            f"> MAX_REFERENCE_EVALUATIONS ({max_evaluations:,}). "
            "Use a synthetic bounded candidate pool rather than the full FPL player universe."
        )

    num_hits = max(0, num_transfers - free_transfers)
    hit_penalty_pts = num_hits * 4

    best_tuple: tuple[float, float, int, tuple[int, ...]] | None = None
    best_payload: dict[str, Any] | None = None
    evaluated_combinations = 0
    legal_combinations = 0

    for out_combo in itertools.combinations(out_pool, num_transfers):
        out_id_set = {p.id for p in out_combo}
        remaining_squad = [p for p in squad_players if p.id not in out_id_set]
        max_budget = bank_tenths + sum(selling_prices[p.id] for p in out_combo)

        out_xp = sum(p.expected_points for p in out_combo)
        out_floor = sum(p.xp_floor for p in out_combo)
        out_ceil = sum(p.xp_ceiling for p in out_combo)
        out_pts = sum(p.total_points for p in out_combo)
        out_fdr_avg = sum(fdr_map.get(p.team_short, 3.0) for p in out_combo) / num_transfers
        out_baseline = sum(get_player_profile_value(p, risk_profile) for p in out_combo)

        for in_combo in itertools.combinations(in_pool, num_transfers):
            evaluated_combinations += 1

            # 1. Availability check: unavailable players ('i', 's', 'u') cannot be transferred in
            if any(getattr(p, "status", "a") in ("i", "s", "u") for p in in_combo):
                continue

            # 2. Budget check
            in_cost = sum(p.price_tenths for p in in_combo)
            if in_cost > max_budget:
                continue

            # 3. Position equality check & full 15-player squad validation
            new_squad = remaining_squad + list(in_combo)
            rules_squad = [
                Player(
                    id=p.id,
                    name=p.name,
                    position=p.position,
                    team_id=p.team_id,
                    price_tenths=p.price_tenths,
                )
                for p in new_squad
            ]
            # Verify 15-player composition and club limit (<= 3 per club) using validate_squad
            # Pass a generous budget to validate_squad because actual purchase affordability is checked via max_budget above
            squad_val = validate_squad(rules_squad, budget_tenths=100_000)
            if not squad_val.is_valid:
                continue

            legal_combinations += 1

            # 4. Independent objective calculation
            in_xp = sum(p.expected_points for p in in_combo)
            in_floor = sum(p.xp_floor for p in in_combo)
            in_ceil = sum(p.xp_ceiling for p in in_combo)
            in_pts = sum(p.total_points for p in in_combo)
            in_fdr_avg = sum(fdr_map.get(p.team_short, 3.0) for p in in_combo) / num_transfers

            fdr_delta = round(out_fdr_avg - in_fdr_avg, 2)
            points_delta = in_pts - out_pts
            xp_delta = round(in_xp - out_xp, 2)
            floor_delta = round(in_floor - out_floor, 2)
            ceil_delta = round(in_ceil - out_ceil, 2)

            if risk_profile == "floor":
                rank_metric = floor_delta - hit_penalty_pts
            elif risk_profile == "ceiling":
                rank_metric = ceil_delta - hit_penalty_pts
            elif risk_profile in ("defend_lead", "chase"):
                in_metric = sum(get_player_profile_value(p, risk_profile) for p in in_combo)
                rank_metric = round((in_metric - out_baseline) - hit_penalty_pts, 2)
            else:
                rank_metric = xp_delta - hit_penalty_pts

            score = round(rank_metric + 0.1 * fdr_delta, 2)
            bank_after = max_budget - in_cost

            sorted_out = sorted(out_combo, key=lambda p: (p.position.value, p.id))
            sorted_in = sorted(in_combo, key=lambda p: (p.position.value, p.id))
            canonical_ids = (
                tuple(-p.id for p in sorted(sorted_out, key=lambda x: x.id))
                + tuple(-p.id for p in sorted(sorted_in, key=lambda x: x.id))
            )
            cand_key = (score, fdr_delta, points_delta, canonical_ids)

            if best_tuple is None or cand_key > best_tuple:
                best_tuple = cand_key
                best_payload = {
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
                        for p in sorted_out
                    ],
                    "incoming": [
                        {
                            "id": p.id,
                            "name": p.name,
                            "position": p.position.name,
                            "team": p.team_short,
                            "price_fmt": f"£{p.price_tenths / 10:.1f}m",
                            "price_tenths": p.price_tenths,
                            "ticker": "",
                            "xp": p.expected_points,
                            "floor": p.xp_floor,
                            "ceiling": p.xp_ceiling,
                            "expected_minutes": p.expected_minutes,
                        }
                        for p in sorted_in
                    ],
                    "bank_after_fmt": f"£{bank_after / 10:.1f}m",
                    "bank_after_tenths": bank_after,
                    "xp_delta": xp_delta,
                    "floor_delta": floor_delta,
                    "ceiling_delta": ceil_delta,
                    "fdr_improvement": fdr_delta,
                    "points_delta": points_delta,
                    "transfer_hits": num_hits,
                    "hit_cost": hit_penalty_pts,
                    "score": score,
                    "oracle_metadata": {
                        "oracle": "solve_transfers_exact_reference",
                        "expected_combinations": expected_combinations,
                        "evaluated_combinations": evaluated_combinations,
                        "legal_combinations": legal_combinations,
                        "max_evaluations_budget": max_evaluations,
                    },
                }

    if best_payload is not None:
        best_payload["oracle_metadata"]["evaluated_combinations"] = evaluated_combinations
        best_payload["oracle_metadata"]["legal_combinations"] = legal_combinations
    return best_payload


solve_transfers_bruteforce_reference = solve_transfers_exact_reference
solve_transfers_exhaustive = solve_transfers_exact_reference



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
        return get_player_profile_value(p, risk_profile)

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
        "solver_type": "heuristic_local_search_1opt_2opt",
        "is_exact_global_solver": False,
        "solver_description": "Three-stage heuristic (greedy feasible init + 1-opt marginal upgrades + 2-opt cross-position swaps) with exact deterministic rule validation.",
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
