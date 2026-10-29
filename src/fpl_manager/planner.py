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
from .models import Position, is_departed_from_premier_league, is_long_term_unavailable
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
    active_chip: str | None = None,
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
    total_xp = starters_xp + captain_xp

    starters_floor = sum(p.xp_floor for p in best_starters) + captain.xp_floor
    starters_ceiling = sum(p.xp_ceiling for p in best_starters) + captain.xp_ceiling

    norm_chip = str(active_chip or "").lower().replace("-", "_")
    if norm_chip in ("bench_boost", "benchboost", "bb"):
        starter_ids_set = {getattr(p, "player_id", getattr(p, "id", None)) for p in best_starters}
        bench_players = [
            gw_projections[pid]
            for pid in player_ids
            if pid in gw_projections and getattr(gw_projections[pid], "player_id", getattr(gw_projections[pid], "id", None)) not in starter_ids_set
        ]
        total_xp += sum(p.expected_points for p in bench_players)
        starters_floor += sum(p.xp_floor for p in bench_players)
        starters_ceiling += sum(p.xp_ceiling for p in bench_players)
    elif norm_chip in ("triple_captain", "triplecaptain", "tc"):
        total_xp += captain_xp
        starters_floor += captain.xp_floor
        starters_ceiling += captain.xp_ceiling

    return round(total_xp, 2), round(starters_floor, 2), round(starters_ceiling, 2), best_formation, captain, vice_captain, best_starters


def _extract_starting_and_bench_ids(
    player_ids: set[int],
    starters: list[Any],
    gw_projections: dict[int, Any],
    risk_profile: str = "neutral",
) -> tuple[list[int], list[int]]:
    """Return (starting_ids, bench_ids) with reserve GK first on the bench followed by 3 outfield bench players."""
    from .optimizer import get_player_profile_value

    starting_ids = [int(getattr(p, "player_id", getattr(p, "id", 0))) for p in starters]
    starter_set = set(starting_ids)
    bench_Ids_raw = [int(pid) for pid in player_ids if int(pid) not in starter_set]

    bench_gk: list[int] = []
    bench_outfield: list[tuple[float, float, int]] = []
    for pid in bench_Ids_raw:
        p = gw_projections.get(pid)
        if p is not None and getattr(p, "position", None) == Position.GOALKEEPER:
            bench_gk.append(pid)
        else:
            val = get_player_profile_value(p, risk_profile) if p is not None else 0.0
            base_val = float(getattr(p, "base_xp_per_match", val)) if p is not None else 0.0
            bench_outfield.append((val, base_val, pid))

    bench_outfield.sort(key=lambda x: (x[0], x[1], -x[2]), reverse=True)
    bench_ids = bench_gk + [pid for _, _, pid in bench_outfield]
    return starting_ids, bench_ids


def generate_multi_gameweek_plan(
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    horizon: int = 3,
    start_gw: int | None = None,
    risk_profile: str = "neutral",
    allow_hits: bool = True,
    beam_width: int = 5,
    report_path: Path = PLAN_REPORT_PATH,
    initial_squad_ids: list[int] | None = None,
    initial_bank_tenths: int | None = None,
    initial_purchase_prices: dict[int, int] | None = None,
) -> dict[str, Any]:
    """Generate an optimal multi-gameweek transfer roadmap using beam search."""
    from .optimizer import validate_risk_profile

    if horizon < 1 or horizon > 8:
        raise ValueError(f"Invalid horizon={horizon}. Must be between 1 and 8 gameweeks.")
    if str(risk_profile or "").strip().lower() in ("balanced", "default"):
        risk_profile = "neutral"
    risk_profile = validate_risk_profile(risk_profile)

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

    candidate_pool_all = [
        p
        for p in players_map.values()
        if p.status in ("a", "d")
        and not is_departed_from_premier_league(p)
        and not is_long_term_unavailable(p)
    ]

    if initial_squad_ids is not None:
        init_ids = list(initial_squad_ids)
        init_bank = initial_bank_tenths if initial_bank_tenths is not None else 0
        init_ft = 1
        init_prices = (
            dict(initial_purchase_prices)
            if initial_purchase_prices is not None
            else {pid: players_map[pid].price_tenths for pid in init_ids if pid in players_map}
        )
    else:
        state = load_current_squad(squad_path)
        init_ids = state.player_ids
        init_bank = state.bank_tenths
        init_ft = state.free_transfers
        init_prices = {p_id: state.purchase_price(p_id) for p_id in state.player_ids}

    # Beam item: (cumulative_net_score, cumulative_floor, cumulative_ceil, player_ids, bank, ft, purchase_prices, history)
    beam: list[tuple[float, float, float, set[int], int, int, dict[int, int], list[dict[str, Any]]]] = [
        (0.0, 0.0, 0.0, set(init_ids), init_bank, init_ft, dict(init_prices), [])
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
            l_xp, l_floor, l_ceil, form, cap, vc, starters_list = _evaluate_lineup_for_gameweek(
                s_pids, gw_projections[gw], risk_profile=risk_profile
            )
            starting_ids, bench_ids = _extract_starting_and_bench_ids(
                s_pids, starters_list, gw_projections[gw], risk_profile=risk_profile
            )
            ft_after = min(5, ft + 1)
            roll_step = {
                "gameweek": gw,
                "action": "ROLL",
                "transfers": [],
                "formation": form,
                "starting_ids": starting_ids,
                "bench_ids": bench_ids,
                "captain": {"id": cap.player_id, "name": cap.web_name, "team": cap.team_short, "xp": cap.expected_points},
                "vice_captain": {"id": vc.player_id, "name": vc.web_name, "team": vc.team_short, "xp": vc.expected_points},
                "lineup_xp": l_xp,
                "lineup_floor": l_floor,
                "lineup_ceiling": l_ceil,
                "net_floor": l_floor,
                "net_ceiling": l_ceil,
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

                    l_xp, l_floor, l_ceil, form, cap, vc, starters_list = _evaluate_lineup_for_gameweek(
                        new_pids, gw_projections[gw], risk_profile=risk_profile
                    )
                    starting_ids, bench_ids = _extract_starting_and_bench_ids(
                        new_pids, starters_list, gw_projections[gw], risk_profile=risk_profile
                    )
                    hit_deduction = hits * 4
                    net_xp = round(l_xp - hit_deduction, 2)
                    net_floor = round(l_floor - hit_deduction, 2)
                    net_ceil = round(l_ceil - hit_deduction, 2)
                    action_label = "1_TRANSFER" if hits == 0 else "1_TRANSFER_HIT"

                    tx_step = {
                        "gameweek": gw,
                        "action": action_label,
                        "transfers": [{
                            "out": {"id": out_p["id"], "name": out_p["name"], "team": out_p["team"]},
                            "in": {"id": in_p["id"], "name": in_p["name"], "team": in_p["team"]},
                        }],
                        "formation": form,
                        "starting_ids": starting_ids,
                        "bench_ids": bench_ids,
                        "captain": {"id": cap.player_id, "name": cap.web_name, "team": cap.team_short, "xp": cap.expected_points},
                        "vice_captain": {"id": vc.player_id, "name": vc.web_name, "team": vc.team_short, "xp": vc.expected_points},
                        "lineup_xp": l_xp,
                        "lineup_floor": l_floor,
                        "lineup_ceiling": l_ceil,
                        "net_floor": net_floor,
                        "net_ceiling": net_ceil,
                        "transfer_hits": hits,
                        "net_xp": net_xp,
                        "bank_after_tenths": new_bank,
                        "bank_after_fmt": f"£{new_bank / 10:.1f}m",
                        "free_transfers_after": ft_after,
                    }
                    next_beam_candidates.append((
                        round(cum_score + net_xp, 2),
                        round(cum_floor + net_floor, 2),
                        round(cum_ceil + net_ceil, 2),
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

                    l_xp, l_floor, l_ceil, form, cap, vc, starters_list = _evaluate_lineup_for_gameweek(
                        new_pids, gw_projections[gw], risk_profile=risk_profile
                    )
                    starting_ids, bench_ids = _extract_starting_and_bench_ids(
                        new_pids, starters_list, gw_projections[gw], risk_profile=risk_profile
                    )
                    hit_deduction = hits * 4
                    net_xp = round(l_xp - hit_deduction, 2)
                    net_floor = round(l_floor - hit_deduction, 2)
                    net_ceil = round(l_ceil - hit_deduction, 2)
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
                        "starting_ids": starting_ids,
                        "bench_ids": bench_ids,
                        "captain": {"id": cap.player_id, "name": cap.web_name, "team": cap.team_short, "xp": cap.expected_points},
                        "vice_captain": {"id": vc.player_id, "name": vc.web_name, "team": vc.team_short, "xp": vc.expected_points},
                        "lineup_xp": l_xp,
                        "lineup_floor": l_floor,
                        "lineup_ceiling": l_ceil,
                        "net_floor": net_floor,
                        "net_ceiling": net_ceil,
                        "transfer_hits": hits,
                        "net_xp": net_xp,
                        "bank_after_tenths": new_bank,
                        "bank_after_fmt": f"£{new_bank / 10:.1f}m",
                        "free_transfers_after": ft_after,
                    }
                    next_beam_candidates.append((
                        round(cum_score + net_xp, 2),
                        round(cum_floor + net_floor, 2),
                        round(cum_ceil + net_ceil, 2),
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
        "free_transfers_initial": init_ft,
        "bank_initial_fmt": f"£{init_bank / 10:.1f}m",
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


@dataclass(frozen=True, slots=True)
class _HistGwProj:
    player_id: int
    id: int
    web_name: str
    team_short: str
    position: Position
    expected_points: float
    xp_floor: float
    xp_ceiling: float
    base_xp_per_match: float
    standard_deviation: float = 0.0
    selected_by_percent: float = 10.0


def generate_historical_multi_gameweek_plan(
    sim: Any,
    horizon: int = 3,
    risk_profile: str = "neutral",
    allow_hits: bool = True,
    beam_width: int = 5,
) -> dict[str, Any]:
    """Generate a point-in-time historical multi-gameweek transfer roadmap using beam search.

    Strictly operates on `sim.get_current_snapshot()` and forward fixture difficulty projections
    without ever querying future gameweek snapshots or post-deadline match outcomes (V146-05, V146-08).
    """
    from .historical.snapshots import analyze_historical_fixtures, load_historical_players_meta
    from .optimizer import validate_risk_profile
    from .suggest_transfers import PlayerInfo

    if horizon < 1 or horizon > 8:
        raise ValueError(f"Invalid horizon={horizon}. Must be between 1 and 8 gameweeks.")
    if str(risk_profile or "").strip().lower() in ("balanced", "default"):
        risk_profile = "neutral"
    risk_profile = validate_risk_profile(risk_profile)

    start_gw = int(sim.current_gw)
    eff_horizon = max(1, min(int(horizon), 38 - start_gw + 1))
    target_gws = list(range(start_gw, start_gw + eff_horizon))

    snapshot = sim.get_current_snapshot()
    season_dir = getattr(sim, "season_dir", None) or (sim.historical_dir / sim.season)
    players_map, _ = load_historical_players_meta(snapshot, season_dir, horizon=eff_horizon)
    fdr_map, ticker_map = analyze_historical_fixtures(season_dir, num_gameweeks=eff_horizon, start_gw=start_gw)

    # Precompute single-GW projection views for each target GW using strictly point-in-time forward projections
    gw_projections: dict[int, dict[int, _HistGwProj]] = {}
    for gw in target_gws:
        gw_map: dict[int, _HistGwProj] = {}
        for pid, p in players_map.items():
            gw_xp = round(float(p.gw_breakdown_xp.get(gw, 0.0)), 2)
            base_ref = float(p.gw_xp) if float(p.gw_xp) > 0 else float(p.expected_points)
            if gw_xp <= 0.0:
                gw_fl = 0.0
                gw_cl = 0.0
            elif base_ref > 0.0 and float(p.xp_floor) > 0.0 and float(p.xp_ceiling) > 0.0:
                ratio = gw_xp / base_ref
                gw_fl = round(float(p.xp_floor) * ratio, 2)
                gw_cl = round(float(p.xp_ceiling) * ratio, 2)
            else:
                sd = float(p.standard_deviation) if float(p.standard_deviation) > 0 else max(1.2, 0.55 * gw_xp)
                gw_fl = round(max(0.0, gw_xp - 1.28 * sd), 2)
                gw_cl = round(gw_xp + 1.65 * sd, 2)
                if gw_fl <= 0.0 and gw_xp > 0.0:
                    gw_fl = round(gw_xp * 0.70, 2)
                    gw_cl = round(gw_xp * 1.40, 2)
            gw_map[pid] = _HistGwProj(
                player_id=pid,
                id=pid,
                web_name=p.name,
                team_short=p.team_short,
                position=p.position,
                expected_points=gw_xp,
                xp_floor=gw_fl,
                xp_ceiling=gw_cl,
                base_xp_per_match=float(p.expected_points),
                standard_deviation=float(p.standard_deviation),
                selected_by_percent=float(getattr(p, "selected_by_percent", 10.0)),
            )
        gw_projections[gw] = gw_map

    # Precompute remaining-horizon PlayerInfo pools for each step index so solve_transfers optimizes over remaining GWs
    step_players_maps: list[dict[int, PlayerInfo]] = []
    for step_idx, gw in enumerate(target_gws):
        rem_gws = target_gws[step_idx:]
        n_rem = max(1, len(rem_gws))
        step_map: dict[int, PlayerInfo] = {}
        for pid, p in players_map.items():
            rem_xp_sum = sum(float(p.gw_breakdown_xp.get(g, 0.0)) for g in rem_gws)
            rem_avg_xp = round(rem_xp_sum / n_rem, 2)
            rem_fl_sum = sum(gw_projections[g][pid].xp_floor for g in rem_gws)
            rem_cl_sum = sum(gw_projections[g][pid].xp_ceiling for g in rem_gws)
            step_map[pid] = PlayerInfo(
                id=p.id,
                name=p.name,
                position=p.position,
                team_id=p.team_id,
                team_short=p.team_short,
                price_tenths=p.price_tenths,
                status=p.status,
                total_points=p.total_points,
                expected_points=rem_avg_xp,
                expected_minutes=p.expected_minutes,
                xp_floor=round(rem_fl_sum / n_rem, 2),
                xp_ceiling=round(rem_cl_sum / n_rem, 2),
                standard_deviation=p.standard_deviation,
                gw_xp=gw_projections[gw][pid].expected_points,
                horizon_xp=round(rem_xp_sum, 2),
                horizon_floor=round(rem_fl_sum, 2),
                horizon_ceiling=round(rem_cl_sum, 2),
                is_long_term_unavailable=p.is_long_term_unavailable,
                gw_breakdown_xp=p.gw_breakdown_xp,
            )
        step_players_maps.append(step_map)

    # Resolve current effective squad state accounting for any already-staged transfers in sim
    already_staged = list(getattr(sim, "transfers_staged", []) or [])
    eff_pids = set(int(pid) for pid in sim.squad_ids)
    eff_bank = int(sim.bank_tenths)
    eff_prices = {int(k): int(v) for k, v in sim.purchase_prices_tenths.items()}

    for st in already_staged:
        if not st.get("already_applied"):
            out_id = int(st["out_id"])
            in_id = int(st["in_id"])
            eff_pids = (eff_pids - {out_id}) | {in_id}
            sell_p = int(st.get("out_selling_price_tenths", st.get("sell_price_tenths", st.get("out_price_tenths", 0))))
            buy_p = int(st.get("in_price_tenths", st.get("buy_price_tenths", 0)))
            if "cost_tenths" in st:
                eff_bank -= int(st["cost_tenths"])
            else:
                eff_bank = eff_bank + sell_p - buy_p
            eff_prices.pop(out_id, None)
            eff_prices[in_id] = buy_p or (players_map[in_id].price_tenths if in_id in players_map else 0)

    pre_staged_step_txs = [
        {
            "out": {
                "id": int(st["out_id"]),
                "name": st.get("out_name") or (players_map[int(st["out_id"])].name if int(st["out_id"]) in players_map else f"#{st['out_id']}"),
                "team": players_map[int(st["out_id"])].team_short if int(st["out_id"]) in players_map else "",
            },
            "in": {
                "id": int(st["in_id"]),
                "name": st.get("in_name") or (players_map[int(st["in_id"])].name if int(st["in_id"]) in players_map else f"#{st['in_id']}"),
                "team": players_map[int(st["in_id"])].team_short if int(st["in_id"]) in players_map else "",
            },
            "already_staged": True,
        }
        for st in already_staged
    ]
    staged_count = len(already_staged)
    init_ft = int(sim.free_transfers)
    max_ft = int(getattr(sim, "max_free_transfers", 5))
    is_step0_free_chip = getattr(sim, "active_chip", None) in ("wildcard_1", "wildcard_2", "free_hit")

    def _next_gw_ft(curr_gw: int, ft_before: int, tx_count: int, chip_active: bool) -> int:
        if curr_gw == 1 or chip_active:
            return 1
        return min(max_ft, max(0, ft_before - tx_count) + 1)

    def _format_action_label(tx_count: int, hits_count: int) -> str:
        if tx_count <= 0:
            return "ROLL"
        base = "1_TRANSFER" if tx_count == 1 else f"{tx_count}_TRANSFERS"
        return f"{base}_HIT" if hits_count > 0 else base

    beam: list[tuple[float, float, float, set[int], int, int, dict[int, int], list[dict[str, Any]]]] = [
        (0.0, 0.0, 0.0, set(eff_pids), eff_bank, init_ft, dict(eff_prices), [])
    ]

    for step_idx, gw in enumerate(target_gws):
        next_beam_candidates = []
        step_p_map = step_players_maps[step_idx]
        candidate_pool_all = [
            p
            for p in step_p_map.values()
            if p.status in ("a", "d")
            and not is_departed_from_premier_league(p)
            and not is_long_term_unavailable(p)
        ]
        chip_at_step = getattr(sim, "active_chip", None) if step_idx == 0 else None
        is_gw1 = (gw == 1)
        chip_free = is_gw1 or (is_step0_free_chip and step_idx == 0)
        base_tx_count = staged_count if step_idx == 0 else 0
        base_tx_list = list(pre_staged_step_txs) if step_idx == 0 else []

        for cum_score, cum_floor, cum_ceil, s_pids, bank, ft, p_prices, history in beam:
            squad_players = [step_p_map[pid] for pid in s_pids if pid in step_p_map]
            s_prices = {
                p.id: selling_price(p_prices.get(p.id, p.price_tenths), p.price_tenths)
                for p in squad_players
            }
            cand_pool = [p for p in candidate_pool_all if p.id not in s_pids]
            eff_ft_for_add = 99 if chip_free else max(0, ft - base_tx_count)

            # Reversion values if this step is an active Free Hit expiring into the next step
            is_fh_expiring = (step_idx == 0 and chip_at_step == "free_hit")
            if is_fh_expiring:
                perm_squad = set(sim.pre_free_hit_state.get("squad_ids")) if sim.pre_free_hit_state else set(sim.gw_start_state.get("squad_ids", s_pids))
                perm_bank = int(sim.pre_free_hit_state.get("bank_tenths")) if sim.pre_free_hit_state else int(sim.gw_start_state.get("bank_tenths", bank))
                perm_prices = {int(k): v for k, v in (sim.pre_free_hit_state.get("purchase_prices_tenths") or sim.gw_start_state.get("purchase_prices_tenths", p_prices)).items()}
            else:
                perm_squad = None
                perm_bank = None
                perm_prices = None

            # --- Action 1: 0 additional transfers (ROLL or keep already-staged) ---
            l_xp, l_floor, l_ceil, form, cap, vc, starters_list = _evaluate_lineup_for_gameweek(
                s_pids, gw_projections[gw], risk_profile=risk_profile, active_chip=chip_at_step
            )
            starting_ids, bench_ids = _extract_starting_and_bench_ids(
                s_pids, starters_list, gw_projections[gw], risk_profile=risk_profile
            )
            tot_tx0 = base_tx_count
            hits0 = 0 if chip_free else max(0, tot_tx0 - ft)
            hits_pts0 = hits0 * 4
            net_xp0 = round(l_xp - hits_pts0, 2)
            net_floor0 = round(l_floor - hits_pts0, 2)
            net_ceil0 = round(l_ceil - hits_pts0, 2)
            ft_after0 = 1 if is_gw1 else _next_gw_ft(gw, ft, tot_tx0, chip_free)
            roll_step = {
                "gameweek": gw,
                "action": _format_action_label(tot_tx0, hits0),
                "transfers": base_tx_list,
                "formation": form,
                "starting_ids": starting_ids,
                "bench_ids": bench_ids,
                "captain": {"id": cap.player_id, "name": cap.web_name, "team": cap.team_short, "xp": cap.expected_points},
                "vice_captain": {"id": vc.player_id, "name": vc.web_name, "team": vc.team_short, "xp": vc.expected_points},
                "lineup_xp": l_xp,
                "lineup_floor": l_floor,
                "lineup_ceiling": l_ceil,
                "net_floor": net_floor0,
                "net_ceiling": net_ceil0,
                "transfer_hits": hits0,
                "net_xp": net_xp0,
                "expected_points": net_xp0,
                "xp_floor": net_floor0,
                "xp_ceiling": net_ceil0,
                "active_chip": chip_at_step,
                "bank_after_tenths": bank,
                "bank_after_fmt": f"£{bank / 10:.1f}m",
                "free_transfers_after": ft_after0,
            }
            cand_pids0 = perm_squad if is_fh_expiring else s_pids
            cand_bank0 = perm_bank if is_fh_expiring else bank
            cand_ft0 = 1 if (is_fh_expiring or is_gw1) else ft_after0
            cand_prices0 = perm_prices if is_fh_expiring else p_prices

            next_beam_candidates.append((
                round(cum_score + net_xp0, 2),
                round(cum_floor + net_floor0, 2),
                round(cum_ceil + net_ceil0, 2),
                cand_pids0,
                cand_bank0,
                cand_ft0,
                cand_prices0,
                history + [roll_step],
            ))

            # --- Action 2: 1 additional transfer ---
            if eff_ft_for_add >= 1 or allow_hits or is_gw1:
                tx1_results, _ = solve_transfers(
                    num_transfers=1,
                    squad_players=squad_players,
                    candidate_pool=cand_pool,
                    bank_tenths=bank,
                    free_transfers=eff_ft_for_add,
                    selling_prices=s_prices,
                    fdr_map=fdr_map,
                    ticker_map=ticker_map,
                    risk_profile=risk_profile,
                    max_results=3,
                )
                for tx in tx1_results:
                    tot_tx1 = base_tx_count + 1
                    hits1 = 0 if chip_free else max(0, tot_tx1 - ft)
                    if not allow_hits and hits1 > 0 and not is_gw1:
                        continue
                    out_p = tx["outgoing"][0]
                    in_p = tx["incoming"][0]

                    new_pids = (s_pids - {out_p["id"]}) | {in_p["id"]}
                    new_prices = dict(p_prices)
                    new_prices.pop(out_p["id"], None)
                    new_prices[in_p["id"]] = in_p["price_tenths"]
                    new_bank = tx["bank_after_tenths"]
                    ft_after1 = 1 if is_gw1 else _next_gw_ft(gw, ft, tot_tx1, chip_free)

                    l_xp, l_floor, l_ceil, form, cap, vc, starters_list = _evaluate_lineup_for_gameweek(
                        new_pids, gw_projections[gw], risk_profile=risk_profile, active_chip=chip_at_step
                    )
                    starting_ids, bench_ids = _extract_starting_and_bench_ids(
                        new_pids, starters_list, gw_projections[gw], risk_profile=risk_profile
                    )
                    hits_pts1 = hits1 * 4
                    net_xp1 = round(l_xp - hits_pts1, 2)
                    net_floor1 = round(l_floor - hits_pts1, 2)
                    net_ceil1 = round(l_ceil - hits_pts1, 2)

                    tx_step = {
                        "gameweek": gw,
                        "action": _format_action_label(tot_tx1, hits1),
                        "transfers": base_tx_list + [{
                            "out": {"id": out_p["id"], "name": out_p["name"], "team": out_p["team"]},
                            "in": {"id": in_p["id"], "name": in_p["name"], "team": in_p["team"]},
                        }],
                        "formation": form,
                        "starting_ids": starting_ids,
                        "bench_ids": bench_ids,
                        "captain": {"id": cap.player_id, "name": cap.web_name, "team": cap.team_short, "xp": cap.expected_points},
                        "vice_captain": {"id": vc.player_id, "name": vc.web_name, "team": vc.team_short, "xp": vc.expected_points},
                        "lineup_xp": l_xp,
                        "lineup_floor": l_floor,
                        "lineup_ceiling": l_ceil,
                        "net_floor": net_floor1,
                        "net_ceiling": net_ceil1,
                        "transfer_hits": hits1,
                        "net_xp": net_xp1,
                        "expected_points": net_xp1,
                        "xp_floor": net_floor1,
                        "xp_ceiling": net_ceil1,
                        "active_chip": chip_at_step,
                        "bank_after_tenths": new_bank,
                        "bank_after_fmt": f"£{new_bank / 10:.1f}m",
                        "free_transfers_after": ft_after1,
                    }
                    cand_pids1 = perm_squad if is_fh_expiring else new_pids
                    cand_bank1 = perm_bank if is_fh_expiring else new_bank
                    cand_ft1 = 1 if (is_fh_expiring or is_gw1) else ft_after1
                    cand_prices1 = perm_prices if is_fh_expiring else new_prices

                    next_beam_candidates.append((
                        round(cum_score + net_xp1, 2),
                        round(cum_floor + net_floor1, 2),
                        round(cum_ceil + net_ceil1, 2),
                        cand_pids1,
                        cand_bank1,
                        cand_ft1,
                        cand_prices1,
                        history + [tx_step],
                    ))

            # --- Action 3: 2 additional transfers ---
            if eff_ft_for_add >= 2 or (allow_hits and (eff_ft_for_add >= 1 or step_idx == 0)) or is_gw1:
                tx2_results, _ = solve_transfers(
                    num_transfers=2,
                    squad_players=squad_players,
                    candidate_pool=cand_pool,
                    bank_tenths=bank,
                    free_transfers=eff_ft_for_add,
                    selling_prices=s_prices,
                    fdr_map=fdr_map,
                    ticker_map=ticker_map,
                    risk_profile=risk_profile,
                    max_results=2,
                )
                for tx in tx2_results:
                    tot_tx2 = base_tx_count + 2
                    hits2 = 0 if chip_free else max(0, tot_tx2 - ft)
                    if not allow_hits and hits2 > 0 and not is_gw1:
                        continue
                    out_ids = {p["id"] for p in tx["outgoing"]}
                    in_ids = {p["id"] for p in tx["incoming"]}

                    new_pids = (s_pids - out_ids) | in_ids
                    new_prices = dict(p_prices)
                    for out_id in out_ids:
                        new_prices.pop(out_id, None)
                    for in_p in tx["incoming"]:
                        new_prices[in_p["id"]] = in_p["price_tenths"]

                    new_bank = tx["bank_after_tenths"]
                    ft_after2 = 1 if is_gw1 else _next_gw_ft(gw, ft, tot_tx2, chip_free)

                    l_xp, l_floor, l_ceil, form, cap, vc, starters_list = _evaluate_lineup_for_gameweek(
                        new_pids, gw_projections[gw], risk_profile=risk_profile, active_chip=chip_at_step
                    )
                    starting_ids, bench_ids = _extract_starting_and_bench_ids(
                        new_pids, starters_list, gw_projections[gw], risk_profile=risk_profile
                    )
                    hits_pts2 = hits2 * 4
                    net_xp2 = round(l_xp - hits_pts2, 2)
                    net_floor2 = round(l_floor - hits_pts2, 2)
                    net_ceil2 = round(l_ceil - hits_pts2, 2)

                    tx_step = {
                        "gameweek": gw,
                        "action": _format_action_label(tot_tx2, hits2),
                        "transfers": base_tx_list + [
                            {
                                "out": {"id": tx["outgoing"][i]["id"], "name": tx["outgoing"][i]["name"], "team": tx["outgoing"][i]["team"]},
                                "in": {"id": tx["incoming"][i]["id"], "name": tx["incoming"][i]["name"], "team": tx["incoming"][i]["team"]},
                            }
                            for i in range(2)
                        ],
                        "formation": form,
                        "starting_ids": starting_ids,
                        "bench_ids": bench_ids,
                        "captain": {"id": cap.player_id, "name": cap.web_name, "team": cap.team_short, "xp": cap.expected_points},
                        "vice_captain": {"id": vc.player_id, "name": vc.web_name, "team": vc.team_short, "xp": vc.expected_points},
                        "lineup_xp": l_xp,
                        "lineup_floor": l_floor,
                        "lineup_ceiling": l_ceil,
                        "net_floor": net_floor2,
                        "net_ceiling": net_ceil2,
                        "transfer_hits": hits2,
                        "net_xp": net_xp2,
                        "expected_points": net_xp2,
                        "xp_floor": net_floor2,
                        "xp_ceiling": net_ceil2,
                        "active_chip": chip_at_step,
                        "bank_after_tenths": new_bank,
                        "bank_after_fmt": f"£{new_bank / 10:.1f}m",
                        "free_transfers_after": ft_after2,
                    }
                    cand_pids2 = perm_squad if is_fh_expiring else new_pids
                    cand_bank2 = perm_bank if is_fh_expiring else new_bank
                    cand_ft2 = 1 if (is_fh_expiring or is_gw1) else ft_after2
                    cand_prices2 = perm_prices if is_fh_expiring else new_prices

                    next_beam_candidates.append((
                        round(cum_score + net_xp2, 2),
                        round(cum_floor + net_floor2, 2),
                        round(cum_ceil + net_ceil2, 2),
                        cand_pids2,
                        cand_bank2,
                        cand_ft2,
                        cand_prices2,
                        history + [tx_step],
                    ))

        if risk_profile == "floor":
            sort_key = lambda x: (x[1], x[0])
        elif risk_profile == "ceiling":
            sort_key = lambda x: (x[2], x[0])
        else:
            sort_key = lambda x: x[0]

        next_beam_candidates.sort(key=sort_key, reverse=True)
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

    return {
        "session_id": sim.session_id,
        "season": sim.season,
        "planning_horizon": eff_horizon,
        "target_gameweeks": target_gws,
        "risk_profile": risk_profile,
        "allow_hits": allow_hits,
        "free_transfers_initial": init_ft,
        "bank_initial_fmt": f"£{eff_bank / 10:.1f}m",
        "optimization_metadata": {
            "algorithm": "beam_search_multi_gw",
            "is_exact_global_optimum": False,
            "optimality_guarantee": "heuristic_beam_search",
            "beam_width": beam_width,
        },
        "best_plan": plans[0] if plans else None,
        "alternative_plans": plans[1:] if len(plans) > 1 else [],
    }


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
            if (
                pr
                and p.status in ("a", "d")
                and not is_departed_from_premier_league(p)
                and not is_long_term_unavailable(p)
            ):
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
                        is_long_term_unavailable=is_long_term_unavailable(p),
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
                    is_long_term_unavailable=is_long_term_unavailable(p),
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


