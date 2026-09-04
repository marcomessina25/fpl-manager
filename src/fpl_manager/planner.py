"""Multi-gameweek transfer planning engine for FPL Manager V0.3.

Evaluates multi-gameweek decision trees over a rolling horizon (e.g. 3 to 5 gameweeks)
using beam search to find optimal transfer trajectories (rolling transfers, single FTs,
multi-FT combinations, or targeted point hits) maximizing cumulative net projected points.
"""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .expected_points import project_gameweek, project_multi_gameweek_profiles
from .fixtures import analyze_team_fixtures, get_current_gameweek
from .models import Position
from .optimizer import solve_transfers
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

    def val_fn(p: Any) -> float:
        if risk_profile == "floor":
            return p.xp_floor
        elif risk_profile == "ceiling":
            return p.xp_ceiling
        return p.expected_points

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
    if horizon < 1 or horizon > 6:
        raise ValueError(f"Invalid horizon={horizon}. Must be between 1 and 6 gameweeks.")
    if risk_profile not in ("neutral", "floor", "ceiling"):
        raise ValueError(f"Invalid risk_profile '{risk_profile}'. Must be 'neutral', 'floor', or 'ceiling'.")

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
                    net_xp = round(l_xp - hits, 2)
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
                    net_xp = round(l_xp - hits, 2)
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
        "best_plan": plans[0] if plans else None,
        "alternative_plans": plans[1:] if len(plans) > 1 else [],
    }

    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return report
