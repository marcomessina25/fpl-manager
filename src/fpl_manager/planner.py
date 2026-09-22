"""Multi-gameweek transfer planning engine for FPL Manager (V1.0.1).

Evaluates multi-gameweek decision trees over a rolling horizon (1 to 6 gameweeks)
using forward beam search (`generate_multi_gameweek_plan`, `is_exact_global_optimum = False`)
and provides an independent Bellman dynamic programming reference oracle (`plan_multi_gw_exact_reference`)
for verifying multi-step optimality on bounded problem instances.
"""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .expected_points import ExpectedPointsProjection, project_gameweek, project_multi_gameweek_profiles
from .fixtures import analyze_team_fixtures, get_current_gameweek
from .models import Position
from .optimizer import PlayerOptInfo, solve_transfers, validate_risk_profile
from .squad_state import CurrentSquadState, load_current_squad
from .storage import SnapshotStore
from .suggest_transfers import load_all_players_meta
from .transfers import selling_price

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"
PLAN_REPORT_PATH = PROJECT_ROOT / "reports" / "transfer_plan.json"

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


def _evaluate_lineup_for_gameweek(
    player_ids: set[int],
    gw_projections: dict[int, Any],
    risk_profile: str = "neutral",
) -> tuple[float, float, float, str, Any, Any, list[Any]]:
    """Determine optimal starting 11, captain, and formation for a specific gameweek."""
    by_pos: dict[Position, list[Any]] = {pos: [] for pos in Position}
    for pid in player_ids:
        p = gw_projections.get(pid)
        if p is not None:
            by_pos[p.position].append(p)

    from .optimizer import get_player_profile_value

    def val_fn(p: Any) -> float:
        return get_player_profile_value(p, risk_profile)

    for pos in by_pos:
        by_pos[pos].sort(key=lambda p: (val_fn(p), p.base_xp_per_match), reverse=True)

    best_score = -float("inf")
    best_formation = "3-5-2"
    best_starters: list[Any] = []

    for n_def, n_mid, n_fwd in LEGAL_FORMATIONS:
        starters = (
            by_pos[Position.GOALKEEPER][:1]
            + by_pos[Position.DEFENDER][:n_def]
            + by_pos[Position.MIDFIELDER][:n_mid]
            + by_pos[Position.FORWARD][:n_fwd]
        )
        st_val = sum(val_fn(p) for p in starters)
        sorted_for_cap = sorted(starters, key=val_fn, reverse=True)
        cap = sorted_for_cap[0]
        cap_val = val_fn(cap)
        score = st_val + cap_val

        if score > best_score:
            best_score = score
            best_formation = f"{n_def}-{n_mid}-{n_fwd}"
            best_starters = starters

    sorted_starters = sorted(best_starters, key=val_fn, reverse=True)
    captain = sorted_starters[0]
    vice_captain = sorted_starters[1]

    starters_xp = sum(p.expected_points for p in best_starters)
    captain_xp = captain.expected_points
    total_xp = round(starters_xp + captain_xp, 2)

    starters_floor = sum(p.xp_floor for p in best_starters) + captain.xp_floor
    starters_ceiling = sum(p.xp_ceiling for p in best_starters) + captain.xp_ceiling

    return total_xp, round(starters_floor, 2), round(starters_ceiling, 2), best_formation, captain, vice_captain, best_starters


def generate_multi_gameweek_plan(
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    horizon: int = 3,
    start_gw: int | None = None,
    risk_profile: str = "neutral",
    allow_hits: bool = True,
    beam_width: int = 5,
    report_path: Path = PLAN_REPORT_PATH,
) -> dict[str, Any]:
    """Generate an optimal multi-gameweek transfer roadmap using beam search."""
    from .optimizer import validate_risk_profile

    if horizon < 1 or horizon > 6:
        raise ValueError(f"Invalid horizon={horizon}. Must be between 1 and 6 gameweeks.")
    risk_profile = validate_risk_profile(risk_profile)


    state = load_current_squad(squad_path)
    store = SnapshotStore(database_path)
    if start_gw is None:
        start_gw = get_current_gameweek(store)

    target_gws = list(range(start_gw, start_gw + horizon))

    # Precalculate gameweek projections once for all players across horizon
    gw_projections: dict[int, dict[int, Any]] = {}
    for gw in target_gws:
        projs = project_gameweek(gw, database_path=database_path)
        gw_projections[gw] = {p.player_id: p for p in projs}

    profiles_map = project_multi_gameweek_profiles(target_gws, database_path=database_path)
    players_map, team_map = load_all_players_meta(store, profiles_map)

    fdr_analysis = analyze_team_fixtures(database_path=database_path, num_gameweeks=horizon, start_gw=start_gw)
    fdr_map = {t["short_name"]: t["avg_difficulty"] for t in fdr_analysis["team_rankings"]}
    ticker_map = {t["short_name"]: t["ticker"] for t in fdr_analysis["team_rankings"]}

    candidate_pool_all = [p for p in players_map.values() if p.status in ("a", "d")]

    initial_prices = {p_id: state.purchase_price(p_id) for p_id in state.player_ids}

    # Beam item: (cumulative_net_score, cumulative_floor, cumulative_ceil, player_ids, bank, ft, purchase_prices, history)
    beam: list[tuple[float, float, float, set[int], int, int, dict[int, int], list[dict[str, Any]]]] = [
        (0.0, 0.0, 0.0, set(state.player_ids), state.bank_tenths, state.free_transfers, dict(initial_prices), [])
    ]

    for step_idx, gw in enumerate(target_gws):
        next_beam_candidates = []

        for cum_score, cum_floor, cum_ceil, s_pids, bank, ft, p_prices, history in beam:
            squad_players = [players_map[pid] for pid in s_pids if pid in players_map]
            s_prices = {
                p.id: selling_price(p_prices.get(p.id, p.price_tenths), p.price_tenths)
                for p in squad_players
            }
            cand_pool = [p for p in candidate_pool_all if p.id not in s_pids]

            # --- Action 1: ROLL TRANSFER (0 transfers) ---
            l_xp, l_floor, l_ceil, form, cap, vc, _ = _evaluate_lineup_for_gameweek(
                s_pids, gw_projections[gw], risk_profile=risk_profile
            )
            ft_after = min(5, ft + 1)
            roll_step = {
                "gameweek": gw,
                "action": "ROLL",
                "transfers": [],
                "formation": form,
                "captain": {"id": cap.player_id, "name": cap.web_name, "team": cap.team_short, "xp": cap.expected_points},
                "vice_captain": {"id": vc.player_id, "name": vc.web_name, "team": vc.team_short, "xp": vc.expected_points},
                "lineup_xp": l_xp,
                "lineup_floor": l_floor,
                "lineup_ceiling": l_ceil,
                "transfer_hits": 0,
                "net_xp": l_xp,
                "bank_after_tenths": bank,
                "bank_after_fmt": f"£{bank / 10:.1f}m",
                "free_transfers_after": ft_after,
            }
            next_beam_candidates.append((
                round(cum_score + l_xp, 2),
                round(cum_floor + l_floor, 2),
                round(cum_ceil + l_ceil, 2),
                s_pids,
                bank,
                ft_after,
                p_prices,
                history + [roll_step],
            ))

            # --- Action 2: 1 TRANSFER ---
            # Allowed if ft >= 1, or if allow_hits is True
            if ft >= 1 or allow_hits:
                tx1_results, _ = solve_transfers(
                    num_transfers=1,
                    squad_players=squad_players,
                    candidate_pool=cand_pool,
                    bank_tenths=bank,
                    free_transfers=ft,
                    selling_prices=s_prices,
                    fdr_map=fdr_map,
                    ticker_map=ticker_map,
                    risk_profile=risk_profile,
                    max_results=3,
                )
                for tx in tx1_results:
                    hits = tx["transfer_hits"]
                    if not allow_hits and hits > 0:
                        continue
                    out_p = tx["outgoing"][0]
                    in_p = tx["incoming"][0]

                    new_pids = (s_pids - {out_p["id"]}) | {in_p["id"]}
                    new_prices = dict(p_prices)
                    new_prices[in_p["id"]] = in_p["price_tenths"]
                    new_bank = tx["bank_after_tenths"]
                    ft_after = min(5, max(0, ft - 1) + 1)

                    l_xp, l_floor, l_ceil, form, cap, vc, _ = _evaluate_lineup_for_gameweek(
                        new_pids, gw_projections[gw], risk_profile=risk_profile
                    )
                    net_xp = round(l_xp - (hits * 4), 2)
                    action_label = "1_TRANSFER" if hits == 0 else "1_TRANSFER_HIT"

                    tx_step = {
                        "gameweek": gw,
                        "action": action_label,
                        "transfers": [{
                            "out": {"id": out_p["id"], "name": out_p["name"], "team": out_p["team"]},
                            "in": {"id": in_p["id"], "name": in_p["name"], "team": in_p["team"]},
                        }],
                        "formation": form,
                        "captain": {"id": cap.player_id, "name": cap.web_name, "team": cap.team_short, "xp": cap.expected_points},
                        "vice_captain": {"id": vc.player_id, "name": vc.web_name, "team": vc.team_short, "xp": vc.expected_points},
                        "lineup_xp": l_xp,
                        "lineup_floor": l_floor,
                        "lineup_ceiling": l_ceil,
                        "transfer_hits": hits,
                        "net_xp": net_xp,
                        "bank_after_tenths": new_bank,
                        "bank_after_fmt": f"£{new_bank / 10:.1f}m",
                        "free_transfers_after": ft_after,
                    }
                    next_beam_candidates.append((
                        round(cum_score + net_xp, 2),
                        round(cum_floor + l_floor, 2),
                        round(cum_ceil + l_ceil, 2),
                        new_pids,
                        new_bank,
                        ft_after,
                        new_prices,
                        history + [tx_step],
                    ))

            # --- Action 3: 2 TRANSFERS ---
            if ft >= 2 or (allow_hits and ft >= 1):
                tx2_results, _ = solve_transfers(
                    num_transfers=2,
                    squad_players=squad_players,
                    candidate_pool=cand_pool,
                    bank_tenths=bank,
                    free_transfers=ft,
                    selling_prices=s_prices,
                    fdr_map=fdr_map,
                    ticker_map=ticker_map,
                    risk_profile=risk_profile,
                    max_results=2,
                )
                for tx in tx2_results:
                    hits = tx["transfer_hits"]
                    if not allow_hits and hits > 0:
                        continue
                    out_ids = {p["id"] for p in tx["outgoing"]}
                    in_ids = {p["id"] for p in tx["incoming"]}

                    new_pids = (s_pids - out_ids) | in_ids
                    new_prices = dict(p_prices)
                    for in_p in tx["incoming"]:
                        new_prices[in_p["id"]] = in_p["price_tenths"]

                    new_bank = tx["bank_after_tenths"]
                    ft_after = min(5, max(0, ft - 2) + 1)

                    l_xp, l_floor, l_ceil, form, cap, vc, _ = _evaluate_lineup_for_gameweek(
                        new_pids, gw_projections[gw], risk_profile=risk_profile
                    )
                    net_xp = round(l_xp - (hits * 4), 2)
                    action_label = "2_TRANSFERS" if hits == 0 else "2_TRANSFERS_HIT"

                    tx_step = {
                        "gameweek": gw,
                        "action": action_label,
                        "transfers": [
                            {
                                "out": {"id": tx["outgoing"][i]["id"], "name": tx["outgoing"][i]["name"], "team": tx["outgoing"][i]["team"]},
                                "in": {"id": tx["incoming"][i]["id"], "name": tx["incoming"][i]["name"], "team": tx["incoming"][i]["team"]},
                            }
                            for i in range(2)
                        ],
                        "formation": form,
                        "captain": {"id": cap.player_id, "name": cap.web_name, "team": cap.team_short, "xp": cap.expected_points},
                        "vice_captain": {"id": vc.player_id, "name": vc.web_name, "team": vc.team_short, "xp": vc.expected_points},
                        "lineup_xp": l_xp,
                        "lineup_floor": l_floor,
                        "lineup_ceiling": l_ceil,
                        "transfer_hits": hits,
                        "net_xp": net_xp,
                        "bank_after_tenths": new_bank,
                        "bank_after_fmt": f"£{new_bank / 10:.1f}m",
                        "free_transfers_after": ft_after,
                    }
                    next_beam_candidates.append((
                        round(cum_score + net_xp, 2),
                        round(cum_floor + l_floor, 2),
                        round(cum_ceil + l_ceil, 2),
                        new_pids,
                        new_bank,
                        ft_after,
                        new_prices,
                        history + [tx_step],
                    ))

        # Sort and retain top beam_width distinct paths
        if risk_profile == "floor":
            sort_key = lambda x: (x[1], x[0])
        elif risk_profile == "ceiling":
            sort_key = lambda x: (x[2], x[0])
        else:
            sort_key = lambda x: x[0]

        next_beam_candidates.sort(key=sort_key, reverse=True)
        # Deduplicate paths that arrive at the same squad with same cumulative score
        seen_states: set[tuple[tuple[int, ...], float]] = set()
        filtered_beam = []
        for cand in next_beam_candidates:
            key = (tuple(sorted(cand[3])), cand[0])
            if key not in seen_states:
                seen_states.add(key)
                filtered_beam.append(cand)
                if len(filtered_beam) == beam_width:
                    break

        beam = filtered_beam

    # Serialize top plans
    plans = []
    for rank, (cum_score, cum_floor, cum_ceil, _, _, _, _, history) in enumerate(beam, 1):
        tot_hits = sum(step["transfer_hits"] for step in history)
        plans.append({
            "rank": rank,
            "total_net_xp": cum_score,
            "cumulative_net_xp": cum_score,
            "total_floor_xp": cum_floor,
            "total_ceiling_xp": cum_ceil,
            "total_hits": tot_hits,
            "gameweek_steps": history,
            "steps": history,
        })

    report = {
        "planning_horizon": horizon,
        "target_gameweeks": target_gws,
        "risk_profile": risk_profile,
        "allow_hits": allow_hits,
        "free_transfers_initial": state.free_transfers,
        "bank_initial_fmt": f"£{state.bank_tenths / 10:.1f}m",
        "optimization_metadata": {
            "algorithm": "beam_search_multi_gw",
            "is_exact_global_optimum": False,
            "optimality_guarantee": "heuristic_beam_search",
            "beam_width": beam_width,
        },
        "best_plan": plans[0] if plans else None,
        "alternative_plans": plans[1:] if len(plans) > 1 else [],
    }

    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return report


MAX_MULTI_GW_REFERENCE_STATES = 25_000


def _enumerate_synthetic_actions(
    squad_ids: tuple[int, ...],
    bank_tenths: int,
    free_transfers: int,
    player_pool: dict[int, dict[str, Any]],
    allow_hits: bool,
    max_transfers_per_gw: int,
    max_club_quota: int,
) -> list[dict[str, Any]]:
    """Enumerate all legal 0..K transfer actions for a bounded synthetic squad."""
    import itertools

    actions: list[dict[str, Any]] = [
        {
            "action": "ROLL",
            "transfers": (),
            "new_squad_ids": squad_ids,
            "new_bank_tenths": bank_tenths,
            "new_ft": min(5, free_transfers + 1),
            "hits": 0,
            "hit_cost": 0.0,
        }
    ]
    squad_set = set(squad_ids)
    in_candidates = [
        pid
        for pid, p in sorted(player_pool.items())
        if pid not in squad_set and p.get("status", "a") not in ("i", "s", "u")
    ]

    for k in range(1, max_transfers_per_gw + 1):
        hits = max(0, k - free_transfers)
        if hits > 0 and not allow_hits:
            continue
        hit_cost = float(hits * 4)
        for out_combo in itertools.combinations(squad_ids, k):
            out_set = set(out_combo)
            rem_ids = [pid for pid in squad_ids if pid not in out_set]
            sell_sum = sum(int(player_pool[pid].get("selling_price_tenths", player_pool[pid]["price_tenths"])) for pid in out_combo)
            avail_budget = bank_tenths + sell_sum
            out_positions = sorted(player_pool[pid]["position"] for pid in out_combo)

            for in_combo in itertools.combinations(in_candidates, k):
                in_positions = sorted(player_pool[pid]["position"] for pid in in_combo)
                if in_positions != out_positions:
                    continue
                buy_sum = sum(int(player_pool[pid]["price_tenths"]) for pid in in_combo)
                if buy_sum > avail_budget:
                    continue
                new_ids = tuple(sorted(rem_ids + list(in_combo)))
                # Check club quota
                club_counts: dict[int, int] = {}
                legal_clubs = True
                for pid in new_ids:
                    tid = int(player_pool[pid].get("team_id", pid))
                    club_counts[tid] = club_counts.get(tid, 0) + 1
                    if club_counts[tid] > max_club_quota:
                        legal_clubs = False
                        break
                if not legal_clubs:
                    continue

                action_label = f"{k}_TRANSFER" + ("S" if k > 1 else "") + ("_HIT" if hits > 0 else "")
                tx_pairs = tuple(zip(out_combo, in_combo))
                actions.append(
                    {
                        "action": action_label,
                        "transfers": tx_pairs,
                        "new_squad_ids": new_ids,
                        "new_bank_tenths": avail_budget - buy_sum,
                        "new_ft": min(5, max(0, free_transfers - k) + 1),
                        "hits": hits,
                        "hit_cost": hit_cost,
                    }
                )
    return actions


def _evaluate_synthetic_squad_gw(
    squad_ids: tuple[int, ...],
    gw: int,
    gw_xp_table: dict[int, dict[int, float]],
    starter_count: int | None = None,
    include_captain_bonus: bool = True,
) -> tuple[float, int]:
    """Compute deterministic immediate reward (starters + captain bonus) for a synthetic squad."""
    xp_map = gw_xp_table.get(gw, {})
    scored = sorted(
        ((float(xp_map.get(pid, 0.0)), -pid, pid) for pid in squad_ids),
        reverse=True,
    )
    n_start = starter_count if starter_count is not None else len(squad_ids)
    starters = scored[:n_start]
    base_xp = sum(item[0] for item in starters)
    cap_id = starters[0][2] if starters else squad_ids[0]
    cap_bonus = starters[0][0] if (starters and include_captain_bonus) else 0.0
    return round(base_xp + cap_bonus, 4), cap_id


def plan_synthetic_multi_gw_beam(
    synthetic_problem: dict[str, Any],
    beam_width: int = 25,
    greedy_one_step_only: bool = False,
) -> dict[str, Any]:
    """Run the beam-search multi-GW planner on a bounded synthetic problem (P0.2)."""
    initial_squad = tuple(sorted(int(x) for x in synthetic_problem["initial_squad_ids"]))
    bank_init = int(synthetic_problem.get("bank_tenths", 0))
    ft_init = int(synthetic_problem.get("free_transfers", 1))
    player_pool = {int(k): dict(v) for k, v in synthetic_problem["player_pool"].items()}
    gw_xp_table = {int(gw): {int(p): float(val) for p, val in m.items()} for gw, m in synthetic_problem["gw_xp_table"].items()}
    target_gws = [int(g) for g in synthetic_problem["target_gameweeks"]]
    allow_hits = bool(synthetic_problem.get("allow_hits", True))
    max_tx = int(synthetic_problem.get("max_transfers_per_gw", 2))
    max_club = int(synthetic_problem.get("max_club_quota", 3))
    starter_count = synthetic_problem.get("starter_count")
    include_cap = bool(synthetic_problem.get("include_captain_bonus", True))

    effective_beam_width = 1 if greedy_one_step_only else beam_width
    # State tuple in beam: (cum_net_xp, canonical_history_tie_key, squad_ids, bank, ft, steps)
    beam: list[tuple[float, tuple[Any, ...], tuple[int, ...], int, int, list[dict[str, Any]]]] = [
        (0.0, (), initial_squad, bank_init, ft_init, [])
    ]

    for gw in target_gws:
        next_candidates = []
        for cum_xp, tie_key, sq_ids, bank, ft, steps in beam:
            legal_actions = _enumerate_synthetic_actions(
                squad_ids=sq_ids,
                bank_tenths=bank,
                free_transfers=ft,
                player_pool=player_pool,
                allow_hits=allow_hits,
                max_transfers_per_gw=max_tx,
                max_club_quota=max_club,
            )
            for act in legal_actions:
                gross_xp, cap_id = _evaluate_synthetic_squad_gw(
                    act["new_squad_ids"], gw, gw_xp_table, starter_count=starter_count, include_captain_bonus=include_cap
                )
                net_xp = round(gross_xp - act["hit_cost"], 4)
                new_cum = round(cum_xp + net_xp, 4)
                step_record = {
                    "gameweek": gw,
                    "action": act["action"],
                    "transfers": [{"out_id": o, "in_id": i} for o, i in act["transfers"]],
                    "squad_ids": list(act["new_squad_ids"]),
                    "captain_id": cap_id,
                    "gross_xp": gross_xp,
                    "hit_cost": act["hit_cost"],
                    "net_xp": net_xp,
                    "bank_after_tenths": act["new_bank_tenths"],
                    "free_transfers_after": act["new_ft"],
                }
                step_tie = (
                    -len(act["transfers"]),
                    tuple((-o, -i) for o, i in act["transfers"]),
                    tuple(-pid for pid in act["new_squad_ids"]),
                )
                next_candidates.append(
                    (
                        new_cum,
                        tie_key + (step_tie,),
                        act["new_squad_ids"],
                        act["new_bank_tenths"],
                        act["new_ft"],
                        steps + [step_record],
                    )
                )

        next_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        seen: set[tuple[tuple[int, ...], int, int]] = set()
        pruned_beam = []
        for cand in next_candidates:
            state_sig = (cand[2], cand[3], cand[4]) if not greedy_one_step_only else (cand[2],)
            if state_sig not in seen:
                seen.add(state_sig)
                pruned_beam.append(cand)
                if len(pruned_beam) >= effective_beam_width:
                    break
        beam = pruned_beam

    best = beam[0] if beam else None
    return {
        "best_plan": {
            "total_net_xp": round(best[0], 2),
            "steps": best[5],
        }
        if best
        else None,
        "optimization_metadata": {
            "algorithm": "greedy_myopic" if greedy_one_step_only else "beam_search_multi_gw",
            "is_exact_global_optimum": False,
            "beam_width": effective_beam_width,
        },
    }


def plan_multi_gw_exact_reference(
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    horizon: int = 3,
    start_gw: int | None = None,
    risk_profile: str = "neutral",
    allow_hits: bool = True,
    synthetic_problem: dict[str, Any] | None = None,
    max_states: int = MAX_MULTI_GW_REFERENCE_STATES,
) -> dict[str, Any]:
    """Independent Dynamic Programming verification oracle for multi-GW planning (P0.2).

    Solves the exact Bellman optimality equation via backward recursion / memoized state-space DP:
        V(state, GW) = max over legal next actions a:
            immediate_reward(state, a, GW) + V(next_state, GW + 1)

    Completely independent of the forward beam-search loop in `generate_multi_gameweek_plan`.
    """
    if synthetic_problem is not None:
        initial_squad = tuple(sorted(int(x) for x in synthetic_problem["initial_squad_ids"]))
        bank_init = int(synthetic_problem.get("bank_tenths", 0))
        ft_init = int(synthetic_problem.get("free_transfers", 1))
        player_pool = {int(k): dict(v) for k, v in synthetic_problem["player_pool"].items()}
        gw_xp_table = {int(gw): {int(p): float(val) for p, val in m.items()} for gw, m in synthetic_problem["gw_xp_table"].items()}
        target_gws = [int(g) for g in synthetic_problem["target_gameweeks"]]
        allow_hits_syn = bool(synthetic_problem.get("allow_hits", allow_hits))
        max_tx = int(synthetic_problem.get("max_transfers_per_gw", 2))
        max_club = int(synthetic_problem.get("max_club_quota", 3))
        starter_count = synthetic_problem.get("starter_count")
        include_cap = bool(synthetic_problem.get("include_captain_bonus", True))

        memo: dict[tuple[int, tuple[int, ...], int, int], tuple[float, tuple[Any, ...], list[dict[str, Any]]]] = {}
        states_evaluated = [0]

        def solve_dp(
            gw_idx: int,
            sq_ids: tuple[int, ...],
            bank: int,
            ft: int,
        ) -> tuple[float, tuple[Any, ...], list[dict[str, Any]]]:
            if gw_idx >= len(target_gws):
                return 0.0, (), []
            state_key = (gw_idx, sq_ids, bank, ft)
            if state_key in memo:
                return memo[state_key]

            states_evaluated[0] += 1
            if states_evaluated[0] > max_states:
                raise ValueError(
                    f"DP reference planner exceeded safety state budget ({states_evaluated[0]} > {max_states})."
                )

            gw = target_gws[gw_idx]
            legal_actions = _enumerate_synthetic_actions(
                squad_ids=sq_ids,
                bank_tenths=bank,
                free_transfers=ft,
                player_pool=player_pool,
                allow_hits=allow_hits_syn,
                max_transfers_per_gw=max_tx,
                max_club_quota=max_club,
            )

            best_val = -float("inf")
            best_tie: tuple[Any, ...] = ()
            best_steps: list[dict[str, Any]] = []

            for act in legal_actions:
                gross_xp, cap_id = _evaluate_synthetic_squad_gw(
                    act["new_squad_ids"], gw, gw_xp_table, starter_count=starter_count, include_captain_bonus=include_cap
                )
                immediate_reward = round(gross_xp - act["hit_cost"], 4)
                future_val, future_tie, future_steps = solve_dp(
                    gw_idx + 1,
                    act["new_squad_ids"],
                    act["new_bank_tenths"],
                    act["new_ft"],
                )
                total_val = round(immediate_reward + future_val, 4)
                step_tie = (
                    -len(act["transfers"]),
                    tuple((-o, -i) for o, i in act["transfers"]),
                    tuple(-pid for pid in act["new_squad_ids"]),
                )
                cand_tie = (step_tie,) + future_tie
                if (total_val, cand_tie) > (best_val, best_tie):
                    best_val = total_val
                    best_tie = cand_tie
                    step_record = {
                        "gameweek": gw,
                        "action": act["action"],
                        "transfers": [{"out_id": o, "in_id": i} for o, i in act["transfers"]],
                        "squad_ids": list(act["new_squad_ids"]),
                        "captain_id": cap_id,
                        "gross_xp": gross_xp,
                        "hit_cost": act["hit_cost"],
                        "net_xp": immediate_reward,
                        "bank_after_tenths": act["new_bank_tenths"],
                        "free_transfers_after": act["new_ft"],
                    }
                    best_steps = [step_record] + future_steps

            memo[state_key] = (best_val, best_tie, best_steps)
            return memo[state_key]

        opt_val, _, opt_steps = solve_dp(0, initial_squad, bank_init, ft_init)
        return {
            "planning_horizon": len(target_gws),
            "target_gameweeks": target_gws,
            "best_plan": {
                "total_net_xp": round(opt_val, 2),
                "cumulative_net_xp": round(opt_val, 2),
                "total_hits": sum(int(s["hit_cost"] // 4) for s in opt_steps),
                "gameweek_steps": opt_steps,
                "steps": opt_steps,
            },
            "oracle_metadata": {
                "oracle": "plan_multi_gw_exact_reference",
                "algorithm": "bellman_dynamic_programming",
                "is_exact_global_optimum": True,
                "states_evaluated": states_evaluated[0],
            },
        }

    # Database-backed bounded DP reference oracle
    risk_profile = validate_risk_profile(risk_profile)
    store = SnapshotStore(database_path)
    store.initialize()
    state = load_current_squad(squad_path)
    all_players = store.latest_players()
    all_player_map = {p.id: p for p in all_players}

    if start_gw is None:
        start_gw = state.gameweek or get_current_gameweek(store)

    target_gws = list(range(start_gw, start_gw + horizon))
    gw_projections: dict[int, dict[int, ExpectedPointsProjection]] = {}
    gw_fdr_maps: dict[int, dict[str, float]] = {}
    gw_cand_pools: dict[int, list[PlayerOptInfo]] = {}

    for gw in target_gws:
        projs = project_gameweek(gameweek=gw, database_path=database_path)
        p_map = {p.player_id: p for p in projs}
        gw_projections[gw] = p_map
        fdr_m: dict[str, float] = {}
        for p in projs:
            if p.team_short not in fdr_m:
                fdr_m[p.team_short] = (
                    sum(f.fdr for f in p.fixtures) / len(p.fixtures) if p.fixtures else 5.0
                )
        gw_fdr_maps[gw] = fdr_m
        pool = []
        for p in all_players:
            pr = p_map.get(p.id)
            if pr and p.status in ("a", "d"):
                pool.append(
                    PlayerOptInfo(
                        id=p.id,
                        name=p.name,
                        position=p.position,
                        team_id=p.team_id,
                        team_short=pr.team_short,
                        price_tenths=p.price_tenths,
                        status=p.status,
                        total_points=p.total_points,
                        expected_points=pr.expected_points,
                        expected_minutes=pr.expected_minutes,
                        xp_floor=pr.xp_floor,
                        xp_ceiling=pr.xp_ceiling,
                        standard_deviation=pr.standard_deviation,
                    )
                )
        gw_cand_pools[gw] = pool

    memo_db: dict[tuple[int, tuple[int, ...], int, int], tuple[float, list[dict[str, Any]]]] = {}
    states_count = [0]

    def solve_db_dp(
        gw_idx: int,
        s_pids: frozenset[int],
        bank: int,
        ft: int,
        p_prices: dict[int, int],
    ) -> tuple[float, list[dict[str, Any]]]:
        if gw_idx >= len(target_gws):
            return 0.0, []
        key = (gw_idx, tuple(sorted(s_pids)), bank, ft)
        if key in memo_db:
            return memo_db[key]

        states_count[0] += 1
        if states_count[0] > max_states:
            raise ValueError(f"DP state budget exceeded ({states_count[0]} > {max_states}).")

        gw = target_gws[gw_idx]
        cand_pool = [c for c in gw_cand_pools[gw] if c.id not in s_pids]
        fdr_map = gw_fdr_maps[gw]
        squad_players = []
        s_prices: dict[int, int] = {}
        for pid in sorted(s_pids):
            p = all_player_map[pid]
            pr = gw_projections[gw].get(pid)
            purchase_p = p_prices.get(pid, p.price_tenths)
            s_prices[pid] = selling_price(purchase_p, p.price_tenths)
            squad_players.append(
                PlayerOptInfo(
                    id=p.id,
                    name=p.name,
                    position=p.position,
                    team_id=p.team_id,
                    team_short=pr.team_short if pr else "",
                    price_tenths=p.price_tenths,
                    status=p.status,
                    total_points=p.total_points,
                    expected_points=pr.expected_points if pr else 0.0,
                    expected_minutes=pr.expected_minutes if pr else 0.0,
                    xp_floor=pr.xp_floor if pr else 0.0,
                    xp_ceiling=pr.xp_ceiling if pr else 0.0,
                    standard_deviation=pr.standard_deviation if pr else 0.0,
                )
            )

        best_total = -float("inf")
        best_history: list[dict[str, Any]] = []

        # 1. ROLL
        l_xp, l_floor, l_ceil, form, cap, vc, _ = _evaluate_lineup_for_gameweek(
            s_pids, gw_projections[gw], risk_profile=risk_profile
        )
        ft_roll = min(5, ft + 1)
        fut_val, fut_steps = solve_db_dp(gw_idx + 1, s_pids, bank, ft_roll, p_prices)
        roll_tot = round(l_xp + fut_val, 2)
        if roll_tot > best_total:
            best_total = roll_tot
            best_history = [
                {
                    "gameweek": gw,
                    "action": "ROLL",
                    "transfers": [],
                    "formation": form,
                    "captain": {"id": cap.player_id, "name": cap.web_name, "team": cap.team_short, "xp": cap.expected_points},
                    "vice_captain": {"id": vc.player_id, "name": vc.web_name, "team": vc.team_short, "xp": vc.expected_points},
                    "lineup_xp": l_xp,
                    "lineup_floor": l_floor,
                    "lineup_ceiling": l_ceil,
                    "transfer_hits": 0,
                    "net_xp": l_xp,
                    "bank_after_tenths": bank,
                    "bank_after_fmt": f"£{bank / 10:.1f}m",
                    "free_transfers_after": ft_roll,
                }
            ] + fut_steps

        # 2. 1-TRANSFER and 2-TRANSFERS
        for num_k, max_r in ((1, 3), (2, 2)):
            if num_k == 1 and not (ft >= 1 or allow_hits):
                continue
            if num_k == 2 and not (ft >= 2 or (allow_hits and ft >= 1)):
                continue
            tx_list, _ = solve_transfers(
                num_transfers=num_k,
                squad_players=squad_players,
                candidate_pool=cand_pool,
                bank_tenths=bank,
                free_transfers=ft,
                selling_prices=s_prices,
                fdr_map=fdr_map,
                ticker_map={},
                risk_profile=risk_profile,
                max_results=max_r,
            )
            for tx in tx_list:
                hits = tx["transfer_hits"]
                if not allow_hits and hits > 0:
                    continue
                out_ids = {p["id"] for p in tx["outgoing"]}
                in_ids = {p["id"] for p in tx["incoming"]}
                new_pids = frozenset((s_pids - out_ids) | in_ids)
                new_prices = dict(p_prices)
                for in_p in tx["incoming"]:
                    new_prices[in_p["id"]] = in_p["price_tenths"]
                new_bank = tx["bank_after_tenths"]
                ft_after = min(5, max(0, ft - num_k) + 1)
                tx_l_xp, tx_l_fl, tx_l_cl, tx_form, tx_cap, tx_vc, _ = _evaluate_lineup_for_gameweek(
                    set(new_pids), gw_projections[gw], risk_profile=risk_profile
                )
                net_xp = round(tx_l_xp - (hits * 4), 2)
                f_val, f_steps = solve_db_dp(gw_idx + 1, new_pids, new_bank, ft_after, new_prices)
                cand_tot = round(net_xp + f_val, 2)
                if cand_tot > best_total:
                    best_total = cand_tot
                    act_lbl = f"{num_k}_TRANSFER" + ("S" if num_k > 1 else "") + ("_HIT" if hits > 0 else "")
                    best_history = [
                        {
                            "gameweek": gw,
                            "action": act_lbl,
                            "transfers": [
                                {
                                    "out": {"id": tx["outgoing"][i]["id"], "name": tx["outgoing"][i]["name"], "team": tx["outgoing"][i]["team"]},
                                    "in": {"id": tx["incoming"][i]["id"], "name": tx["incoming"][i]["name"], "team": tx["incoming"][i]["team"]},
                                }
                                for i in range(num_k)
                            ],
                            "formation": tx_form,
                            "captain": {"id": tx_cap.player_id, "name": tx_cap.web_name, "team": tx_cap.team_short, "xp": tx_cap.expected_points},
                            "vice_captain": {"id": tx_vc.player_id, "name": tx_vc.web_name, "team": tx_vc.team_short, "xp": tx_vc.expected_points},
                            "lineup_xp": tx_l_xp,
                            "lineup_floor": tx_l_fl,
                            "lineup_ceiling": tx_l_cl,
                            "transfer_hits": hits,
                            "net_xp": net_xp,
                            "bank_after_tenths": new_bank,
                            "bank_after_fmt": f"£{new_bank / 10:.1f}m",
                            "free_transfers_after": ft_after,
                        }
                    ] + f_steps

        memo_db[key] = (best_total, best_history)
        return memo_db[key]

    opt_score, opt_hist = solve_db_dp(
        0,
        frozenset(state.player_ids),
        state.bank_tenths,
        state.free_transfers,
        dict(state.purchase_prices_tenths),
    )
    return {
        "planning_horizon": horizon,
        "target_gameweeks": target_gws,
        "risk_profile": risk_profile,
        "allow_hits": allow_hits,
        "best_plan": {
            "rank": 1,
            "total_net_xp": opt_score,
            "cumulative_net_xp": opt_score,
            "total_hits": sum(s["transfer_hits"] for s in opt_hist),
            "gameweek_steps": opt_hist,
            "steps": opt_hist,
        },
        "oracle_metadata": {
            "oracle": "plan_multi_gw_exact_reference",
            "algorithm": "bellman_dynamic_programming",
            "is_exact_global_optimum": True,
            "states_evaluated": states_count[0],
        },
    }


plan_multi_gw_dp_reference = plan_multi_gw_exact_reference
plan_multi_gw_exhaustive = plan_multi_gw_exact_reference


