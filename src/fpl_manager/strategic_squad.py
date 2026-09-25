"""Strategic squad optimization engine for FPL Manager (V1.1).

Provides pure-Python strategic combinatorial solvers for:
1. Initial Squad Construction (Season Start, GW1): Multi-Gameweek strategic horizon,
   budget allocation, flexibility, and structure without pre-existing squad constraints.
2. Strategic Wildcard Construction: Multi-Gameweek horizon, squad reset, fixture swings,
   and strategic transition from current squad.
3. Generalized Free-Hit Construction: 1-Gameweek strategic optimization preserving
   regression safety with V1.0.
4. Hard constraints (locked players, excluded players, club limits <= 3, budget, formation)
   and soft preferences (player bonuses, differential targets, flexibility).
5. Multiple strategic candidates (Maximum EV, Balanced, Floor, Ceiling, Flexibility, Defend Lead, Chase).
6. Deterministic re-optimization and constraint impact analysis (opportunity cost, player diffs).
7. Independent exact reference solver for bounded synthetic cases (`solve_strategic_squad_exact_reference`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import itertools
import math
from typing import Any

from .models import Position
from .optimizer import LEGAL_FORMATIONS, PlayerOptInfo, get_player_profile_value, validate_risk_profile
from .rules import Player, validate_squad, validate_starting_lineup

STRATEGIC_PROFILES: tuple[str, ...] = (
    "maximum_ev",
    "balanced",
    "floor",
    "ceiling",
    "flexibility",
    "defend_lead",
    "chase",
)

STRATEGIC_MODES: tuple[str, ...] = (
    "initial",
    "wildcard",
    "free_hit",
)


@dataclass
class StrategicConstraints:
    """Hard and soft constraints governing strategic squad construction."""

    budget_tenths: int = 1000  # Default £100.0m
    locked_player_ids: set[int] = field(default_factory=set)
    excluded_player_ids: set[int] = field(default_factory=set)
    preferred_player_ids: set[int] = field(default_factory=set)
    soft_preference_weight: float = 1.0
    max_players_per_club: int = 3
    position_quotas: dict[Position, int] = field(
        default_factory=lambda: {
            Position.GOALKEEPER: 2,
            Position.DEFENDER: 5,
            Position.MIDFIELDER: 5,
            Position.FORWARD: 3,
        }
    )
    min_bank_tenths: int = 0
    target_gameweeks: tuple[int, ...] = ()

    def validate(self, candidate_pool: list[Any]) -> list[str]:
        """Validate constraints for feasibility and raise or return errors."""
        errors: list[str] = []

        overlap = set(self.locked_player_ids) & set(self.excluded_player_ids)
        if overlap:
            errors.append(f"Players cannot be simultaneously locked and excluded: {sorted(overlap)}")

        pool_by_id = {p.id: p for p in candidate_pool}
        missing_locked = [pid for pid in self.locked_player_ids if pid not in pool_by_id]
        if missing_locked:
            errors.append(f"Locked player IDs not found in candidate pool: {missing_locked}")

        locked_players = [pool_by_id[pid] for pid in self.locked_player_ids if pid in pool_by_id]

        # Positional quotas check for locked players
        locked_by_pos: dict[Position, int] = {}
        for p in locked_players:
            locked_by_pos[p.position] = locked_by_pos.get(p.position, 0) + 1

        for pos, quota in self.position_quotas.items():
            locked_cnt = locked_by_pos.get(pos, 0)
            if locked_cnt > quota:
                errors.append(
                    f"Locked {locked_cnt} players for position {pos.name}, which exceeds position quota of {quota}."
                )

        # Club limits check for locked players
        locked_by_club: dict[int, int] = {}
        for p in locked_players:
            locked_by_club[p.team_id] = locked_by_club.get(p.team_id, 0) + 1

        for team_id, count in locked_by_club.items():
            if count > self.max_players_per_club:
                errors.append(
                    f"Locked {count} players from team ID {team_id}, which exceeds max club limit of {self.max_players_per_club}."
                )

        # Budget check for locked players
        locked_cost = sum(p.price_tenths for p in locked_players)
        rem_slots = 15 - len(locked_players)
        min_rem_cost = rem_slots * 40  # minimum £4.0m per remaining slot
        if locked_cost + min_rem_cost + self.min_bank_tenths > self.budget_tenths:
            errors.append(
                f"Locked players cost £{locked_cost / 10:.1f}m plus minimum remaining squad cost "
                f"£{min_rem_cost / 10:.1f}m exceeds available budget £{self.budget_tenths / 10:.1f}m."
            )

        return errors


@dataclass(frozen=True, slots=True)
class StrategicCandidate:
    """A fully characterized strategic candidate squad solution."""

    candidate_id: str
    mode: str
    strategy: str
    total_objective_value: float
    horizon_gws: list[int]
    horizon_xp: float
    horizon_breakdown: dict[int, float]
    start_gw_lineup_xp: float
    formation: str
    total_cost_tenths: int
    bank_remaining_tenths: int
    total_cost_fmt: str
    bank_remaining_fmt: str
    future_flexibility_score: float
    fixture_ease_score: float
    bench_value_score: float
    captaincy_score: float
    risk_score: float
    starters: list[dict[str, Any]]
    bench: list[dict[str, Any]]
    captain: dict[str, Any]
    vice_captain: dict[str, Any]
    squad: list[dict[str, Any]]
    player_ids: list[int]
    locked_player_ids: list[int]
    excluded_player_ids: list[int]
    preferred_player_ids: list[int]
    is_exact_global_optimum: bool
    algorithm: str
    search_metadata: dict[str, Any]
    provenance: dict[str, Any]

    @property
    def squad_player_ids(self) -> list[int]:
        return self.player_ids

    @property
    def horizon_expected_points(self) -> float:
        return self.horizon_xp

    @property
    def objective_score(self) -> float:
        return self.total_objective_value

    @property
    def flexibility_score(self) -> float:
        return self.future_flexibility_score

    @property
    def bench_value_tenths(self) -> int:
        return sum(p.get("price_tenths", 0) for p in self.bench)

    def to_dict(self) -> dict[str, Any]:
        """Convert candidate to JSON-serializable dictionary."""
        return {
            "candidate_id": self.candidate_id,
            "mode": self.mode,
            "strategy": self.strategy,
            "total_objective_value": self.total_objective_value,
            "horizon_gws": self.horizon_gws,
            "horizon_xp": self.horizon_xp,
            "horizon_breakdown": self.horizon_breakdown,
            "start_gw_lineup_xp": self.start_gw_lineup_xp,
            "formation": self.formation,
            "total_cost_tenths": self.total_cost_tenths,
            "bank_remaining_tenths": self.bank_remaining_tenths,
            "total_cost_fmt": self.total_cost_fmt,
            "bank_remaining_fmt": self.bank_remaining_fmt,
            "future_flexibility_score": self.future_flexibility_score,
            "fixture_ease_score": self.fixture_ease_score,
            "bench_value_score": self.bench_value_score,
            "captaincy_score": self.captaincy_score,
            "risk_score": self.risk_score,
            "starters": self.starters,
            "bench": self.bench,
            "captain": self.captain,
            "vice_captain": self.vice_captain,
            "squad": self.squad,
            "player_ids": self.player_ids,
            "locked_player_ids": self.locked_player_ids,
            "excluded_player_ids": self.excluded_player_ids,
            "preferred_player_ids": self.preferred_player_ids,
            "is_exact_global_optimum": self.is_exact_global_optimum,
            "algorithm": self.algorithm,
            "search_metadata": self.search_metadata,
            "provenance": self.provenance,
        }


def compute_player_strategic_value(
    player: Any,
    strategy: str,
    horizon_len: int = 5,
    preferred_ids: set[int] | None = None,
    fdr_avg: float = 3.0,
) -> float:
    """Calculate single-player strategic value under the selected profile.

    Aggregation Convention (P0.1):
    - player.expected_points or player.gw_xp represents the 1-GW expected points.
    - If player.horizon_xp is explicitly provided (> 0.0), it represents the exact
      sum across the target gameweeks (Σ expected_points(player, GW)), and is used
      directly without multiplying by horizon_len again.
    - If player.horizon_xp is not provided, the 1-GW rate is scaled by horizon_len.
    - Under either representation, the 5-GW expected-point contribution of a player
      projected for [5, 6, 7, 8, 9] is 35.0, NEVER multiplied twice.
    """
    strat = strategy.lower().strip()

    # Detect if player already provides an explicit horizon aggregate
    has_horizon_xp = getattr(player, "horizon_xp", 0.0) != 0.0
    if has_horizon_xp:
        base_xp = float(player.horizon_xp)
        floor_val = float(getattr(player, "horizon_floor", getattr(player, "xp_floor", base_xp)))
        ceil_val = float(getattr(player, "horizon_ceiling", getattr(player, "xp_ceiling", base_xp)))
    else:
        gw_xp = float(getattr(player, "gw_xp", getattr(player, "expected_points", 0.0)))
        base_xp = gw_xp * horizon_len
        floor_val = float(getattr(player, "xp_floor", gw_xp)) * horizon_len
        ceil_val = float(getattr(player, "xp_ceiling", gw_xp)) * horizon_len

    sd = getattr(player, "standard_deviation", 1.0)
    sel = getattr(player, "selected_by_percent", 10.0)

    # Base profile value (all terms calibrated to horizon scale)
    if strat == "maximum_ev":
        val = base_xp
    elif strat == "floor":
        val = (floor_val * 0.85 + base_xp * 0.15) - 0.2 * sd
    elif strat == "ceiling":
        val = (ceil_val * 0.85 + base_xp * 0.15) + 0.3 * sd
    elif strat == "flexibility":
        # Rewards solid xP, favorable fixture run, and standard price brackets
        fixture_bonus = max(0.0, (3.5 - fdr_avg) * 0.6) * horizon_len
        val = base_xp + fixture_bonus
    elif strat == "defend_lead":
        val = floor_val - 0.20 * sd + (0.02 * min(50.0, sel)) * horizon_len
    elif strat == "chase":
        diff_bonus = max(0.0, (15.0 - sel) * 0.05) * horizon_len
        val = ceil_val + 0.25 * sd + diff_bonus
    else:  # balanced
        fixture_bonus = max(0.0, (3.2 - fdr_avg) * 0.4) * horizon_len
        val = base_xp * 0.7 + floor_val * 0.2 + ceil_val * 0.1 + fixture_bonus

    if preferred_ids and player.id in preferred_ids:
        val += 2.5 * (horizon_len / 5.0)

    return round(val, 2)


def compute_future_flexibility(
    squad: list[Any],
    bank_tenths: int,
    club_counts: dict[int, int],
) -> float:
    """Quantify structural future transfer flexibility (0-100 scale).

    Factors:
    1. Bank reserve liquidity: £0.5m-£1.5m reserve allows instant 1-transfer upgrades.
    2. Price point distribution: avoiding rigid clusters, having clear tiers in MID/FWD.
    3. Club quota leeway: clubs with 3 players restrict incoming transfers from that club.
    """
    score = 50.0

    # 1. Bank reserve bonus (up to +20)
    if bank_tenths >= 15:  # £1.5m+
        score += 20.0
    elif bank_tenths >= 10:  # £1.0m+
        score += 16.0
    elif bank_tenths >= 5:  # £0.5m+
        score += 12.0
    elif bank_tenths > 0:
        score += 6.0

    # 2. Club saturation penalty (having 3 players from a club costs 4 pts per saturated club)
    saturated_clubs = sum(1 for c in club_counts.values() if c >= 3)
    score -= saturated_clubs * 4.0

    # 3. Price ladder balance
    prices = [p.price_tenths for p in squad]
    premiums = sum(1 for pr in prices if pr >= 100)  # £10.0m+
    mid_tier = sum(1 for pr in prices if 65 <= pr < 100)  # £6.5m - £9.9m
    budget_enablers = sum(1 for pr in prices if pr <= 45)  # £4.0m - £4.5m

    if premiums in (1, 2):
        score += 10.0
    if mid_tier >= 3:
        score += 10.0
    if budget_enablers >= 2:
        score += 10.0

    return max(0.0, min(100.0, round(score, 1)))


def evaluate_strategic_squad_objective(
    squad: list[Any],
    strategy: str,
    horizon_gws: list[int],
    bank_tenths: int,
    preferred_ids: set[int] | None = None,
    bench_weight: float = 0.15,
) -> tuple[float, dict[str, float], dict[str, Any]]:
    """Evaluate the complete strategic objective for a candidate 15-player squad."""
    h_len = max(1, len(horizon_gws))
    by_pos: dict[Position, list[Any]] = {pos: [] for pos in Position}
    for p in squad:
        by_pos[p.position].append(p)

    def p_val(p: Any) -> float:
        return compute_player_strategic_value(p, strategy, horizon_len=h_len, preferred_ids=preferred_ids)

    for pos in by_pos:
        by_pos[pos].sort(key=p_val, reverse=True)

    # Find best formation for lineup
    best_score = -float("inf")
    best_formation = "3-4-3"
    best_starters: list[Any] = []
    best_bench: list[Any] = []
    best_cap: Any = None
    best_vc: Any = None

    for n_def, n_mid, n_fwd in LEGAL_FORMATIONS:
        st_gk = by_pos[Position.GOALKEEPER][:1]
        st_def = by_pos[Position.DEFENDER][:n_def]
        st_mid = by_pos[Position.MIDFIELDER][:n_mid]
        st_fwd = by_pos[Position.FORWARD][:n_fwd]
        starters = st_gk + st_def + st_mid + st_fwd
        starters_val = sum(p_val(p) for p in starters)

        sorted_by_val = sorted(starters, key=p_val, reverse=True)
        cap = sorted_by_val[0]
        vc = sorted_by_val[1] if len(sorted_by_val) > 1 else sorted_by_val[0]
        cap_val = p_val(cap)

        bench_gk = by_pos[Position.GOALKEEPER][1:2]
        bench_outfield = (
            by_pos[Position.DEFENDER][n_def:]
            + by_pos[Position.MIDFIELDER][n_mid:]
            + by_pos[Position.FORWARD][n_fwd:]
        )
        bench_outfield.sort(key=p_val, reverse=True)
        bench = bench_gk + bench_outfield
        bench_val = sum(p_val(p) for p in bench)

        cand_score = starters_val + 0.8 * cap_val + bench_weight * bench_val
        if cand_score > best_score:
            best_score = cand_score
            best_formation = f"{n_def}-{n_mid}-{n_fwd}"
            best_starters = starters
            best_bench = bench
            best_cap = cap
            best_vc = vc

    # Compute component scores
    starters_xp_per_gw = sum(getattr(p, "gw_xp", getattr(p, "expected_points", 0.0)) for p in best_starters)
    cap_bonus_per_gw = getattr(best_cap, "gw_xp", getattr(best_cap, "expected_points", 0.0)) if best_cap else 0.0
    lineup_xp_per_gw = starters_xp_per_gw + cap_bonus_per_gw

    has_horizon = any(getattr(p, "horizon_xp", 0.0) != 0.0 for p in best_starters)
    if has_horizon:
        total_horizon_xp = round(
            sum(getattr(p, "horizon_xp", getattr(p, "expected_points", 0.0) * h_len) for p in best_starters)
            + (getattr(best_cap, "horizon_xp", getattr(best_cap, "expected_points", 0.0) * h_len) if best_cap else 0.0),
            2,
        )
    else:
        total_horizon_xp = round(lineup_xp_per_gw * h_len, 2)

    horizon_breakdown = {gw: round(total_horizon_xp / h_len, 2) for gw in horizon_gws}

    club_counts: dict[int, int] = {}
    for p in squad:
        club_counts[p.team_id] = club_counts.get(p.team_id, 0) + 1

    flexibility_score = compute_future_flexibility(squad, bank_tenths, club_counts)
    bench_val_score = round(
        sum(getattr(p, "horizon_xp", getattr(p, "gw_xp", getattr(p, "expected_points", 0.0)) * h_len) for p in best_bench),
        2,
    )
    cap_score = round((getattr(best_cap, "xp_ceiling", getattr(best_cap, "expected_points", 0.0)) * 2), 2)

    # Risk penalty
    risk_pts = sum(
        3.0 if getattr(p, "status", "a") in ("d", "i", "s") else 0.0
        for p in squad
    )

    # Total composite objective value
    strat_lower = strategy.lower().strip()
    if strat_lower == "maximum_ev":
        total_obj = total_horizon_xp + 0.1 * bench_val_score + 0.05 * cap_score
    elif strat_lower == "flexibility":
        total_obj = total_horizon_xp * 0.85 + (flexibility_score * 0.4) + 0.15 * bench_val_score - risk_pts
    elif strat_lower == "floor":
        if has_horizon:
            floor_sum = sum(getattr(p, "horizon_floor", getattr(p, "xp_floor", getattr(p, "expected_points", 0.0)) * h_len) for p in best_starters)
            total_obj = floor_sum + (flexibility_score * 0.1) - (risk_pts * 2.0)
        else:
            floor_sum = sum(getattr(p, "xp_floor", getattr(p, "expected_points", 0.0)) for p in best_starters)
            total_obj = (floor_sum * h_len) + (flexibility_score * 0.1) - (risk_pts * 2.0)
    elif strat_lower == "ceiling":
        if has_horizon:
            ceil_sum = sum(getattr(p, "horizon_ceiling", getattr(p, "xp_ceiling", getattr(p, "expected_points", 0.0)) * h_len) for p in best_starters)
            total_obj = ceil_sum + cap_score * 0.5 - risk_pts
        else:
            ceil_sum = sum(getattr(p, "xp_ceiling", getattr(p, "expected_points", 0.0)) for p in best_starters)
            total_obj = (ceil_sum * h_len) + cap_score * 0.5 - risk_pts
    else:  # balanced / default
        total_obj = total_horizon_xp + (flexibility_score * 0.2) + (bench_val_score * 0.2) + (cap_score * 0.1) - risk_pts

    if preferred_ids:
        preferred_in_squad = sum(1 for p in squad if p.id in preferred_ids)
        total_obj += preferred_in_squad * 2.0

    scores_breakdown = {
        "horizon_xp": total_horizon_xp,
        "flexibility": flexibility_score,
        "bench_value": bench_val_score,
        "captaincy": cap_score,
        "risk_penalty": round(risk_pts, 2),
    }

    lineup_meta = {
        "formation": best_formation,
        "starters": best_starters,
        "bench": best_bench,
        "captain": best_cap,
        "vice_captain": best_vc,
        "lineup_xp": round(total_horizon_xp / h_len, 2),
        "horizon_breakdown": horizon_breakdown,
    }

    return round(total_obj, 2), scores_breakdown, lineup_meta


def solve_strategic_squad_exact_reference(
    candidate_pool: list[Any],
    constraints: StrategicConstraints,
    strategy: str = "balanced",
    max_evaluations: int = 1_000_000,
) -> StrategicCandidate | None:
    """Independent exact brute-force reference solver for bounded synthetic pools.

    Systematically evaluates all feasible 15-player combinations respecting
    position quotas, club limits, budget, and locked/excluded constraints, returning
    the verified mathematically exact global optimum.
    """
    validation_errors = constraints.validate(candidate_pool)
    if validation_errors:
        raise ValueError(f"Constraint validation failed: {'; '.join(validation_errors)}")

    pool_by_id = {p.id: p for p in candidate_pool}
    excluded_set = set(constraints.excluded_player_ids)
    locked_set = set(constraints.locked_player_ids)

    # Filter out excluded players; pool cannot contain excluded
    # Align feasibility with production solver (P0.5):
    # Unavailable players ('i', 's', 'u') cannot be selected unless locked.
    eligible_pool = [
        p
        for p in candidate_pool
        if p.id not in excluded_set and (p.id in locked_set or getattr(p, "status", "a") in ("a", "d"))
    ]

    # Partition by position
    by_pos: dict[Position, list[Any]] = {pos: [] for pos in Position}
    for p in eligible_pool:
        by_pos[p.position].append(p)

    target_gws = list(constraints.target_gameweeks) or [1, 2, 3, 4, 5]

    # Pre-check combination size
    # For exact solver on bounded pools, we combine position combinations
    c_gkp = list(itertools.combinations(by_pos[Position.GOALKEEPER], constraints.position_quotas[Position.GOALKEEPER]))
    c_def = list(itertools.combinations(by_pos[Position.DEFENDER], constraints.position_quotas[Position.DEFENDER]))
    c_mid = list(itertools.combinations(by_pos[Position.MIDFIELDER], constraints.position_quotas[Position.MIDFIELDER]))
    c_fwd = list(itertools.combinations(by_pos[Position.FORWARD], constraints.position_quotas[Position.FORWARD]))

    total_combos = len(c_gkp) * len(c_def) * len(c_mid) * len(c_fwd)
    if total_combos > max_evaluations:
        raise ValueError(
            f"Reference solver safety budget exceeded: {total_combos:,} combinations > {max_evaluations:,}. "
            "Use bounded candidate pool for exact reference validation."
        )

    best_cand: StrategicCandidate | None = None
    best_obj = -float("inf")
    evaluated = 0
    legal_count = 0

    for gkp_c in c_gkp:
        for def_c in c_def:
            for mid_c in c_mid:
                for fwd_c in c_fwd:
                    evaluated += 1
                    squad = list(gkp_c + def_c + mid_c + fwd_c)
                    squad_ids = {p.id for p in squad}

                    # Must contain all locked players
                    if not locked_set.issubset(squad_ids):
                        continue

                    # Club quota check
                    team_counts: dict[int, int] = {}
                    club_valid = True
                    for p in squad:
                        team_counts[p.team_id] = team_counts.get(p.team_id, 0) + 1
                        if team_counts[p.team_id] > constraints.max_players_per_club:
                            club_valid = False
                            break
                    if not club_valid:
                        continue

                    # Budget check
                    total_cost = sum(p.price_tenths for p in squad)
                    if total_cost + constraints.min_bank_tenths > constraints.budget_tenths:
                        continue

                    legal_count += 1
                    bank_rem = constraints.budget_tenths - total_cost

                    obj_val, scores, lineup_meta = evaluate_strategic_squad_objective(
                        squad=squad,
                        strategy=strategy,
                        horizon_gws=target_gws,
                        bank_tenths=bank_rem,
                        preferred_ids=constraints.preferred_player_ids,
                    )

                    if obj_val > best_obj:
                        best_obj = obj_val

                        def serialize(p: Any, role: str) -> dict[str, Any]:
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
                                "team": getattr(p, "team_short", f"T{p.team_id}"),
                                "team_id": p.team_id,
                                "price_tenths": p.price_tenths,
                                "price_fmt": f"£{p.price_tenths / 10:.1f}m",
                                "status": getattr(p, "status", "a"),
                                "role": role,
                                "expected_points": getattr(p, "expected_points", 0.0),
                                "xp_floor": getattr(p, "xp_floor", 0.0),
                                "xp_ceiling": getattr(p, "xp_ceiling", 0.0),
                                "expected_minutes": getattr(p, "expected_minutes", 0.0),
                                "is_locked": p.id in locked_set,
                                "is_preferred": p.id in constraints.preferred_player_ids,
                            }

                        starters_ser = [
                            serialize(
                                p,
                                "CAPTAIN"
                                if p.id == lineup_meta["captain"].id
                                else (
                                    "VICE_CAPTAIN"
                                    if lineup_meta["vice_captain"] and p.id == lineup_meta["vice_captain"].id
                                    else "STARTER"
                                ),
                            )
                            for p in lineup_meta["starters"]
                        ]
                        bench_ser = [
                            serialize(p, "GK_SUB" if idx == 0 else f"BENCH_{idx}")
                            for idx, p in enumerate(lineup_meta["bench"])
                        ]

                        best_cand = StrategicCandidate(
                            candidate_id=f"exact_{strategy}_{datetime.now(timezone.utc).strftime('%H%M%S')}",
                            mode="initial",
                            strategy=strategy,
                            total_objective_value=obj_val,
                            horizon_gws=target_gws,
                            horizon_xp=scores["horizon_xp"],
                            horizon_breakdown=lineup_meta["horizon_breakdown"],
                            start_gw_lineup_xp=lineup_meta["lineup_xp"],
                            formation=lineup_meta["formation"],
                            total_cost_tenths=total_cost,
                            bank_remaining_tenths=bank_rem,
                            total_cost_fmt=f"£{total_cost / 10:.1f}m",
                            bank_remaining_fmt=f"£{bank_rem / 10:.1f}m",
                            future_flexibility_score=scores["flexibility"],
                            fixture_ease_score=3.2,
                            bench_value_score=scores["bench_value"],
                            captaincy_score=scores["captaincy"],
                            risk_score=scores["risk_penalty"],
                            starters=starters_ser,
                            bench=bench_ser,
                            captain=serialize(lineup_meta["captain"], "CAPTAIN"),
                            vice_captain=serialize(lineup_meta["vice_captain"], "VICE_CAPTAIN"),
                            squad=[serialize(p, "SQUAD") for p in squad],
                            player_ids=[p.id for p in squad],
                            locked_player_ids=sorted(locked_set),
                            excluded_player_ids=sorted(excluded_set),
                            preferred_player_ids=sorted(constraints.preferred_player_ids),
                            is_exact_global_optimum=True,
                            algorithm="solve_strategic_squad_exact_reference",
                            search_metadata={
                                "evaluated_combinations": evaluated,
                                "legal_combinations": legal_count,
                                "max_evaluations_budget": max_evaluations,
                            },
                            provenance={
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "model_version": "v1.1-strategic",
                                "solver": "exact_brute_force",
                            },
                        )

    return best_cand


def solve_strategic_squad(
    candidate_pool: list[Any],
    constraints: StrategicConstraints,
    strategy: str = "balanced",
    mode: str = "initial",
    horizon: int | None = None,
    max_1opt_iterations: int = 50,
    max_2opt_rounds: int = 15,
) -> StrategicCandidate:
    """Production heuristic strategic squad optimizer.

    Stages:
    1. Feasible Initialization: Force-includes locked players, seeds remaining slots
       with valid, budget-compliant players maximizing strategic utility per cost.
    2. 1-Opt Upgrades: Iteratively replaces non-locked squad members with highest
       marginal strategic gain while strictly maintaining positional, club, and budget limits.
    3. 2-Opt Cross-Position Swaps: Evaluates pairwise swaps across positions to rebalance
       pitch budget and uncover global trade-offs.
    4. Lineup & Captain Selection: Evaluates all 8 legal formations to select optimal starting 11,
       captain, vice-captain, and ordered bench.
    5. Structural & Flexibility Scoring: Evaluates future transfer flexibility, bench quality,
       and risk.
    """
    validation_errors = constraints.validate(candidate_pool)
    if validation_errors:
        raise ValueError(f"Constraint validation failed: {'; '.join(validation_errors)}")

    target_gws = (list(range(1, 1 + horizon)) if horizon is not None else list(constraints.target_gameweeks)) or [1, 2, 3, 4, 5]
    h_len = max(1, len(target_gws))

    pool_by_id = {p.id: p for p in candidate_pool}
    excluded_set = set(constraints.excluded_player_ids)
    locked_set = set(constraints.locked_player_ids)
    pref_set = set(constraints.preferred_player_ids)

    # Filter out excluded players; unavailable players ('i', 's', 'u') cannot be newly picked unless locked
    eligible_pool = [
        p
        for p in candidate_pool
        if p.id not in excluded_set and (p.id in locked_set or getattr(p, "status", "a") in ("a", "d"))
    ]

    by_pos: dict[Position, list[Any]] = {pos: [] for pos in Position}
    for p in eligible_pool:
        by_pos[p.position].append(p)

    def p_score(p: Any) -> float:
        return compute_player_strategic_value(p, strategy, horizon_len=h_len, preferred_ids=pref_set)

    # Sort candidates by strategic efficiency (utility / cost) and total utility
    for pos in by_pos:
        by_pos[pos].sort(key=lambda p: (p_score(p) / max(40, p.price_tenths), p_score(p)), reverse=True)

    # Stage 1: Seed locked players and construct initial feasible squad
    squad: list[Any] = [pool_by_id[pid] for pid in locked_set]
    t_counts: dict[int, int] = {}
    for p in squad:
        t_counts[p.team_id] = t_counts.get(p.team_id, 0) + 1

    pos_counts: dict[Position, int] = {}
    for p in squad:
        pos_counts[p.position] = pos_counts.get(p.position, 0) + 1

    # Fill remaining slots by position
    effective_budget = constraints.budget_tenths - constraints.min_bank_tenths

    for pos, quota in constraints.position_quotas.items():
        needed = quota - pos_counts.get(pos, 0)
        if needed <= 0:
            continue

        cands = [p for p in by_pos[pos] if p.id not in locked_set]
        picked = 0

        # Try strategic efficiency first
        for cand in cands:
            if picked >= needed:
                break
            if cand in squad:
                continue
            if t_counts.get(cand.team_id, 0) >= constraints.max_players_per_club:
                continue

            # Check conservative budget feasibility
            current_cost = sum(p.price_tenths for p in squad)
            rem_slots = 15 - len(squad) - 1
            if current_cost + cand.price_tenths + rem_slots * 40 > effective_budget:
                continue

            squad.append(cand)
            t_counts[cand.team_id] = t_counts.get(cand.team_id, 0) + 1
            picked += 1

        # Fallback to cheapest valid candidates if tight budget
        if picked < needed:
            cheapest = sorted(cands, key=lambda p: p.price_tenths)
            for cand in cheapest:
                if picked >= needed:
                    break
                if cand in squad:
                    continue
                if t_counts.get(cand.team_id, 0) >= constraints.max_players_per_club:
                    continue

                squad.append(cand)
                t_counts[cand.team_id] = t_counts.get(cand.team_id, 0) + 1
                picked += 1

        # Fallback if club saturation blocked candidates: swap an earlier selection
        if picked < needed:
            blocked_cands = [c for c in cands if c not in squad and t_counts.get(c.team_id, 0) >= constraints.max_players_per_club]
            for cand in blocked_cands:
                if picked >= needed:
                    break
                swapped = False
                for sel_p in list(squad):
                    if sel_p.id in locked_set or sel_p.team_id != cand.team_id or sel_p.position == pos:
                        continue
                    alt_candidates = sorted(by_pos[sel_p.position], key=lambda p: p.price_tenths)
                    for alt in alt_candidates:
                        if alt in squad or alt.id in locked_set:
                            continue
                        if t_counts.get(alt.team_id, 0) >= constraints.max_players_per_club or alt.team_id == cand.team_id:
                            continue
                        current_cost = sum(p.price_tenths for p in squad)
                        if current_cost - sel_p.price_tenths + alt.price_tenths + cand.price_tenths > effective_budget:
                            continue
                        squad.remove(sel_p)
                        t_counts[sel_p.team_id] -= 1
                        squad.append(alt)
                        t_counts[alt.team_id] = t_counts.get(alt.team_id, 0) + 1
                        squad.append(cand)
                        t_counts[cand.team_id] = t_counts.get(cand.team_id, 0) + 1
                        picked += 1
                        swapped = True
                        break
                    if swapped:
                        break

    if len(squad) != 15:
        raise RuntimeError("Failed to build a valid 15-player squad from candidate pool under constraints.")

    current_cost = sum(p.price_tenths for p in squad)
    squad_ids = {p.id for p in squad}

    # Stage 2: 1-Opt Upgrades (Locked players cannot be replaced)
    improved_1opt = True
    iteration = 0
    while improved_1opt and iteration < max_1opt_iterations:
        improved_1opt = False
        iteration += 1
        best_swap = None
        best_gain = 0.0

        for i, curr_p in enumerate(squad):
            if curr_p.id in locked_set:
                continue  # Never replace a locked player

            curr_val = p_score(curr_p)
            for cand in by_pos[curr_p.position]:
                if cand.id in squad_ids:
                    continue
                delta_cost = cand.price_tenths - curr_p.price_tenths
                if current_cost + delta_cost > effective_budget:
                    continue
                if cand.team_id != curr_p.team_id and t_counts.get(cand.team_id, 0) >= constraints.max_players_per_club:
                    continue
                delta_val = p_score(cand) - curr_val
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
            current_cost += delta_cost
            improved_1opt = True

    # Stage 3: 2-Opt Cross-Position Swaps
    cands_pos = {
        pos: sorted(by_pos[pos], key=p_score, reverse=True)[:30]
        for pos in Position
    }

    improved_2opt = True
    rounds = 0
    while improved_2opt and rounds < max_2opt_rounds:
        improved_2opt = False
        rounds += 1
        best_2swap = None
        best_2gain = 0.0

        for i in range(len(squad)):
            p1 = squad[i]
            if p1.id in locked_set:
                continue

            for j in range(i + 1, len(squad)):
                p2 = squad[j]
                if p2.id in locked_set:
                    continue

                t_counts[p1.team_id] -= 1
                t_counts[p2.team_id] -= 1
                base_cost = current_cost - p1.price_tenths - p2.price_tenths
                base_val = p_score(p1) + p_score(p2)

                for c1 in cands_pos[p1.position]:
                    if c1.id in squad_ids and c1.id not in (p1.id, p2.id):
                        continue
                    if t_counts.get(c1.team_id, 0) >= constraints.max_players_per_club:
                        continue
                    t_counts[c1.team_id] = t_counts.get(c1.team_id, 0) + 1

                    for c2 in cands_pos[p2.position]:
                        if c2.id in squad_ids and c2.id not in (p1.id, p2.id):
                            continue
                        if c1.id == c2.id:
                            continue
                        if t_counts.get(c2.team_id, 0) >= constraints.max_players_per_club:
                            continue
                        new_cost = base_cost + c1.price_tenths + c2.price_tenths
                        if new_cost > effective_budget:
                            continue
                        gain = (p_score(c1) + p_score(c2)) - base_val
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
            current_cost = new_cost
            improved_2opt = True

    # Rule validation of finalized 15-player squad
    rules_squad = [
        Player(
            id=p.id,
            name=p.name,
            position=p.position,
            team_id=p.team_id,
            price_tenths=p.price_tenths,
        )
        for p in squad
    ]
    val = validate_squad(rules_squad, budget_tenths=constraints.budget_tenths)
    if not val.is_valid:
        raise RuntimeError(f"Optimized squad failed FPL rules: {'; '.join(val.errors)}")

    # Objective and Lineup Evaluation
    bank_rem = constraints.budget_tenths - current_cost
    obj_val, scores, lineup_meta = evaluate_strategic_squad_objective(
        squad=squad,
        strategy=strategy,
        horizon_gws=target_gws,
        bank_tenths=bank_rem,
        preferred_ids=pref_set,
    )

    def serialize(p: Any, role: str) -> dict[str, Any]:
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
            "team": getattr(p, "team_short", f"T{p.team_id}"),
            "team_id": p.team_id,
            "price_tenths": p.price_tenths,
            "price_fmt": f"£{p.price_tenths / 10:.1f}m",
            "status": getattr(p, "status", "a"),
            "role": role,
            "expected_points": getattr(p, "expected_points", 0.0),
            "xp_floor": getattr(p, "xp_floor", 0.0),
            "xp_ceiling": getattr(p, "xp_ceiling", 0.0),
            "expected_minutes": getattr(p, "expected_minutes", 0.0),
            "is_locked": p.id in locked_set,
            "is_preferred": p.id in pref_set,
        }

    starters_ser = [
        serialize(
            p,
            "CAPTAIN"
            if p.id == lineup_meta["captain"].id
            else (
                "VICE_CAPTAIN"
                if lineup_meta["vice_captain"] and p.id == lineup_meta["vice_captain"].id
                else "STARTER"
            ),
        )
        for p in lineup_meta["starters"]
    ]
    bench_ser = [
        serialize(p, "GK_SUB" if idx == 0 else f"BENCH_{idx}")
        for idx, p in enumerate(lineup_meta["bench"])
    ]

    timestamp_str = datetime.now(timezone.utc).strftime("%H%M%S")
    cand_id = f"cand_{mode}_{strategy}_{timestamp_str}"

    return StrategicCandidate(
        candidate_id=cand_id,
        mode=mode,
        strategy=strategy,
        total_objective_value=obj_val,
        horizon_gws=target_gws,
        horizon_xp=scores["horizon_xp"],
        horizon_breakdown=lineup_meta["horizon_breakdown"],
        start_gw_lineup_xp=lineup_meta["lineup_xp"],
        formation=lineup_meta["formation"],
        total_cost_tenths=current_cost,
        bank_remaining_tenths=bank_rem,
        total_cost_fmt=f"£{current_cost / 10:.1f}m",
        bank_remaining_fmt=f"£{bank_rem / 10:.1f}m",
        future_flexibility_score=scores["flexibility"],
        fixture_ease_score=3.2,
        bench_value_score=scores["bench_value"],
        captaincy_score=scores["captaincy"],
        risk_score=scores["risk_penalty"],
        starters=starters_ser,
        bench=bench_ser,
        captain=serialize(lineup_meta["captain"], "CAPTAIN"),
        vice_captain=serialize(lineup_meta["vice_captain"], "VICE_CAPTAIN"),
        squad=[serialize(p, "SQUAD") for p in squad],
        player_ids=[p.id for p in squad],
        locked_player_ids=sorted(locked_set),
        excluded_player_ids=sorted(excluded_set),
        preferred_player_ids=sorted(pref_set),
        is_exact_global_optimum=False,
        algorithm="solve_strategic_squad:heuristic_1opt_2opt",
        search_metadata={
            "1opt_iterations": iteration,
            "2opt_rounds": rounds,
            "pool_size": len(candidate_pool),
            "eligible_pool_size": len(eligible_pool),
        },
        provenance={
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model_version": "v1.1-strategic",
            "solver": "local_search_heuristic",
        },
    )


class StrategicCandidateDict(dict):
    """Dictionary of strategic candidates that stores requested, successful, and failed profile metadata (P1.2)."""
    requested_profiles: list[str]
    successful_profiles: list[str]
    failed_profiles: dict[str, str]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.requested_profiles = []
        self.successful_profiles = []
        self.failed_profiles = {}


def generate_strategic_candidates(
    candidate_pool: list[Any],
    constraints: StrategicConstraints,
    strategies: list[str] | None = None,
    mode: str = "initial",
    horizon: int | None = None,
    failed_profiles: dict[str, str] | None = None,
) -> dict[str, StrategicCandidate]:
    """Generate a diversified set of strategic candidate squads across multiple objectives.

    Tracks requested, successful, and failed strategic profiles without silently dropping them (P1.2).
    """
    strats = strategies or ["maximum_ev", "balanced", "floor", "ceiling", "flexibility"]
    candidates = StrategicCandidateDict()
    failures: dict[str, str] = {}

    for strat in strats:
        try:
            cand = solve_strategic_squad(
                candidate_pool=candidate_pool,
                constraints=constraints,
                strategy=strat,
                mode=mode,
                horizon=horizon,
            )
            candidates[strat] = cand
        except Exception as e:
            err_msg = str(e)
            failures[strat] = err_msg
            if failed_profiles is not None:
                failed_profiles[strat] = err_msg

    if not candidates:
        first_err = next(iter(failures.values()), "Unknown failure")
        raise RuntimeError(f"Failed to generate any valid strategic candidate squads: {first_err}")

    candidates.requested_profiles = list(strats)
    candidates.successful_profiles = list(candidates.keys())
    candidates.failed_profiles = failures

    return candidates


def measure_heuristic_optimality_gap(
    candidate_pool: list[Any],
    constraints: StrategicConstraints,
    strategy: str = "maximum_ev",
) -> dict[str, float]:
    """Empirically evaluate the production heuristic's optimality gap against the exact reference oracle (P1.1).

    Reports:
    - exact_optimum: objective value from exact reference solver
    - heuristic_value: objective value from production heuristic solver
    - absolute_gap: exact_optimum - heuristic_value
    - relative_gap: (exact_optimum - heuristic_value) / |exact_optimum| (if non-zero)
    """
    exact_cand = solve_strategic_squad_exact_reference(
        candidate_pool=candidate_pool,
        constraints=constraints,
        strategy=strategy,
    )
    if exact_cand is None:
        raise ValueError("No feasible squad found by exact reference solver.")

    heur_cand = solve_strategic_squad(
        candidate_pool=candidate_pool,
        constraints=constraints,
        strategy=strategy,
    )

    exact_obj = float(exact_cand.total_objective_value)
    heur_obj = float(heur_cand.total_objective_value)
    abs_gap = round(max(0.0, exact_obj - heur_obj), 4)
    rel_gap = round(abs_gap / abs(exact_obj), 4) if exact_obj != 0.0 else 0.0

    return {
        "exact_optimum": exact_obj,
        "heuristic_value": heur_obj,
        "absolute_gap": abs_gap,
        "relative_gap": rel_gap,
    }


def analyze_constraint_impact(
    previous_candidate: StrategicCandidate | dict[str, Any],
    new_candidate: StrategicCandidate | dict[str, Any],
) -> dict[str, Any]:
    """Analyze the strategic trade-offs and opportunity cost of a constraint modification."""
    def _get(cand: Any, attr: str, default: Any = None) -> Any:
        if isinstance(cand, dict):
            return cand.get(attr, default)
        return getattr(cand, attr, default)

    prev_locks = set(_get(previous_candidate, "locked_player_ids", []))
    new_locks = set(_get(new_candidate, "locked_player_ids", []))
    added_locks = list(new_locks - prev_locks)
    removed_locks = list(prev_locks - new_locks)

    prev_excl = set(_get(previous_candidate, "excluded_player_ids", []))
    new_excl = set(_get(new_candidate, "excluded_player_ids", []))
    added_excl = list(new_excl - prev_excl)
    removed_excl = list(prev_excl - new_excl)

    prev_pref = set(_get(previous_candidate, "preferred_player_ids", []))
    new_pref = set(_get(new_candidate, "preferred_player_ids", []))
    added_pref = list(new_pref - prev_pref)
    removed_pref = list(prev_pref - new_pref)

    prev_ids = set(_get(previous_candidate, "player_ids", []))
    new_ids = set(_get(new_candidate, "player_ids", []))
    added_ids = new_ids - prev_ids
    removed_ids = prev_ids - new_ids

    prev_squad = _get(previous_candidate, "squad", [])
    new_squad = _get(new_candidate, "squad", [])
    prev_squad_by_id = {p["id"]: p for p in prev_squad if isinstance(p, dict) and "id" in p}
    new_squad_by_id = {p["id"]: p for p in new_squad if isinstance(p, dict) and "id" in p}

    players_added = [new_squad_by_id[pid] for pid in added_ids if pid in new_squad_by_id]
    players_removed = [prev_squad_by_id[pid] for pid in removed_ids if pid in prev_squad_by_id]

    prev_obj = float(_get(previous_candidate, "total_objective_value", 0.0))
    new_obj = float(_get(new_candidate, "total_objective_value", 0.0))
    objective_delta = round(new_obj - prev_obj, 2)
    opportunity_cost = round(-objective_delta if objective_delta < 0 else 0.0, 2)

    prev_h_xp = float(_get(previous_candidate, "horizon_xp", 0.0))
    new_h_xp = float(_get(new_candidate, "horizon_xp", 0.0))
    horizon_xp_delta = round(new_h_xp - prev_h_xp, 2)

    prev_gw1_xp = float(_get(previous_candidate, "start_gw_lineup_xp", 0.0))
    new_gw1_xp = float(_get(new_candidate, "start_gw_lineup_xp", 0.0))
    lineup_xp_delta = round(new_gw1_xp - prev_gw1_xp, 2)

    prev_bank = int(_get(previous_candidate, "bank_remaining_tenths", 0))
    new_bank = int(_get(new_candidate, "bank_remaining_tenths", 0))
    bank_delta_tenths = new_bank - prev_bank

    prev_flex = float(_get(previous_candidate, "future_flexibility_score", 0.0))
    new_flex = float(_get(new_candidate, "future_flexibility_score", 0.0))
    flexibility_delta = round(new_flex - prev_flex, 1)

    summary_parts = []
    if added_locks:
        summary_parts.append(f"Locked {len(added_locks)} player(s)")
    if added_excl:
        summary_parts.append(f"Excluded {len(added_excl)} player(s)")
    if added_pref:
        summary_parts.append(f"Preferred {len(added_pref)} player(s)")

    desc = ", ".join(summary_parts) if summary_parts else "Modified constraints"
    if opportunity_cost > 0:
        summary = f"{desc} incurred an opportunity cost of {opportunity_cost:.1f} pts (objective changed by {objective_delta:+.1f})."
    else:
        summary = f"{desc} resulted in objective delta of {objective_delta:+.1f} pts."

    return {
        "summary": summary,
        "objective_delta": objective_delta,
        "opportunity_cost": opportunity_cost,
        "horizon_xp_delta": horizon_xp_delta,
        "lineup_xp_delta": lineup_xp_delta,
        "bank_delta_tenths": bank_delta_tenths,
        "bank_delta_fmt": f"{bank_delta_tenths / 10:+.1f}m",
        "flexibility_delta": flexibility_delta,
        "constraints_changed": {
            "added_locks": added_locks,
            "removed_locks": removed_locks,
            "added_exclusions": added_excl,
            "removed_exclusions": removed_excl,
            "added_preferences": added_pref,
            "removed_preferences": removed_pref,
        },
        "players_added": players_added,
        "players_removed": players_removed,
    }


def reoptimize_strategic_squad(
    previous_candidate: StrategicCandidate,
    candidate_pool: list[Any],
    new_constraints: StrategicConstraints,
    strategy: str | None = None,
    horizon: int | None = None,
) -> tuple[StrategicCandidate, dict[str, Any]]:
    """Re-optimize squad under updated constraints and return new candidate with impact analysis."""
    strat = strategy or previous_candidate.strategy
    new_candidate = solve_strategic_squad(
        candidate_pool=candidate_pool,
        constraints=new_constraints,
        strategy=strat,
        mode=previous_candidate.mode,
        horizon=horizon,
    )
    impact = analyze_constraint_impact(previous_candidate, new_candidate)
    return new_candidate, impact
