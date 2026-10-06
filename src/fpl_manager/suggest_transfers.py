"""Transfer suggestion and Wildcard/Free-Hit squad recommendation service (V1.0.1).

Coordinates multi-gameweek expected points projections, fixture difficulty ratings,
and squad selling-price rules with the combinatorial optimizers in `fpl_manager.optimizer`.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .expected_points import (
    MultiGameweekProfile,
    project_gameweek,
    project_multi_gameweek_profiles,
)
from .fixtures import analyze_team_fixtures, get_current_gameweek
from .models import (
    Position,
    evaluate_long_term_unavailable,
    is_departed_from_premier_league,
    is_long_term_unavailable,
)
from .optimizer import solve_transfers, solve_wildcard, validate_risk_profile
from .squad_state import load_current_squad
from .storage import SnapshotStore
from .strategic_squad import (
    StrategicConstraints,
    generate_strategic_candidates,
    solve_strategic_squad,
)
from .transfers import selling_price

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"
TRANSFERS_REPORT_PATH = PROJECT_ROOT / "reports" / "transfer_suggestions.json"
WILDCARD_REPORT_PATH = PROJECT_ROOT / "reports" / "wildcard_squad.json"
INITIAL_SQUAD_REPORT_PATH = PROJECT_ROOT / "reports" / "initial_squad.json"
STRATEGIC_SQUAD_REPORT_PATH = PROJECT_ROOT / "reports" / "strategic_squad.json"


@dataclass(frozen=True, slots=True)
class PlayerInfo:
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
    gw_xp: float = 0.0
    horizon_xp: float = 0.0
    horizon_floor: float = 0.0
    horizon_ceiling: float = 0.0
    is_long_term_unavailable: bool = False


def load_all_players_meta(
    store: SnapshotStore,
    profiles_map: dict[int, Any] | None = None,
) -> tuple[dict[int, PlayerInfo], dict[int, str]]:
    """Load all players and team short names from the latest snapshot with projected xP and profiles."""
    store.initialize()
    with store._connect() as connection:
        snapshot = connection.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        if snapshot is None:
            raise RuntimeError("No FPL data found. Run `fpl update` first.")
        snapshot_id = snapshot[0]

        teams_rows = connection.execute(
            "SELECT team_id, short_name FROM teams WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchall()
        team_map = {row[0]: row[1] for row in teams_rows}

        players_rows = connection.execute(
            """
            SELECT player_id, web_name, position_id, team_id, price_tenths, status, total_points,
                   news, chance_of_playing_next_round, chance_of_playing_this_round
            FROM players
            WHERE snapshot_id = ?
            """,
            (snapshot_id,),
        ).fetchall()

    players_map: dict[int, PlayerInfo] = {}
    for p_id, web_name, pos_id, t_id, price, status, pts, news, chance_next, chance_this in players_rows:
        t_short = team_map.get(t_id, f"T{t_id}")
        prof = profiles_map.get(p_id) if profiles_map else None
        if isinstance(prof, MultiGameweekProfile):
            p_horizon_xp = float(prof.expected_points)
            f_count = max(1, prof.fixtures_count)
            p_gw_xp = round(p_horizon_xp / f_count, 2)
            p_xp = p_gw_xp
            p_xm = round(prof.expected_minutes / f_count, 1)
            p_floor = round(prof.xp_floor / f_count, 2)
            p_ceil = round(prof.xp_ceiling / f_count, 2)
            p_std = prof.standard_deviation
            p_horizon_floor = float(prof.xp_floor)
            p_horizon_ceil = float(prof.xp_ceiling)
        elif isinstance(prof, (int, float)):
            p_xp = float(prof)
            p_gw_xp = p_xp
            p_horizon_xp = p_xp * 5.0
            p_xm = 0.0
            p_floor = 0.0
            p_ceil = 0.0
            p_std = 0.0
            p_horizon_floor = 0.0
            p_horizon_ceil = 0.0
        else:
            p_xp = 0.0
            p_gw_xp = 0.0
            p_horizon_xp = 0.0
            p_xm = 0.0
            p_floor = 0.0
            p_ceil = 0.0
            p_std = 0.0
            p_horizon_floor = 0.0
            p_horizon_ceil = 0.0

        players_map[p_id] = PlayerInfo(
            id=p_id,
            name=web_name,
            position=Position(pos_id),
            team_id=t_id,
            team_short=t_short,
            price_tenths=price,
            status=status,
            total_points=pts,
            expected_points=p_xp,
            expected_minutes=p_xm,
            xp_floor=p_floor,
            xp_ceiling=p_ceil,
            standard_deviation=p_std,
            gw_xp=p_gw_xp,
            horizon_xp=p_horizon_xp,
            horizon_floor=p_horizon_floor,
            horizon_ceiling=p_horizon_ceil,
            is_long_term_unavailable=evaluate_long_term_unavailable(
                status, news, chance_this, chance_next, datetime.now(timezone.utc)
            ),
        )

    return players_map, team_map



def suggest_transfers(
    num_transfers: int = 1,
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    max_results: int = 15,
    num_gameweeks: int = 5,
    risk_profile: str = "neutral",
    report_path: Path = TRANSFERS_REPORT_PATH,
    gameweek: int | None = None,
    dead_capital_weight: float = 3.0,
    engine: str = "v1.3.5",
    gamma: float = 0.75,
    horizon: int = 3,
) -> dict[str, Any]:
    """Generate legal 1- to 5-transfer move recommendations for the current squad.

    Supports V1.3.5/V1.4 Hardened Baseline Lineup-Aware Evaluation with rolling discounted horizon,
    pruned candidate search pool, goalkeeper churn suppression, and reason breakdown tracking, with optional
    fallback to V1.2.5 or legacy unweighted squad optimization.
    """
    if num_transfers < 1 or num_transfers > 5:
        raise ValueError(
            f"Invalid num_transfers={num_transfers}. Optimizer supports between 1 and 5 transfers."
        )

    risk_profile = validate_risk_profile(risk_profile)
    clean_engine = str(engine).lower().strip()
    is_legacy = clean_engine in ("legacy", "v1.0", "v1.0.1", "v10", "v101")
    is_v12 = clean_engine in ("v1.2", "v12")
    is_v125 = clean_engine in ("v1.2.5", "v125")
    is_v135 = clean_engine in ("v1.3.5", "v1.4", "v135", "v14", "default") or (not is_legacy and not is_v12 and not is_v125)
    engine_name = "v1.3.5" if is_v135 else ("v1.2.5" if is_v125 else ("v1.2" if is_v12 else "legacy"))

    state = load_current_squad(squad_path)
    store = SnapshotStore(database_path)
    if gameweek is not None:
        start_gw = gameweek
    elif state.gameweek is not None:
        start_gw = state.gameweek
    else:
        start_gw = get_current_gameweek(store)
    target_gws = list(range(start_gw, start_gw + num_gameweeks))
    profiles_map = project_multi_gameweek_profiles(target_gws, database_path=database_path)
    players_map, team_map = load_all_players_meta(store, profiles_map)
    fdr_analysis = analyze_team_fixtures(database_path=database_path, num_gameweeks=num_gameweeks, start_gw=start_gw)
    fdr_map = {t["short_name"]: t["avg_difficulty"] for t in fdr_analysis["team_rankings"]}
    ticker_map = {t["short_name"]: t["ticker"] for t in fdr_analysis["team_rankings"]}

    squad_set = set(state.player_ids)
    squad_players = [players_map[p_id] for p_id in state.player_ids if p_id in players_map]

    # Calculate selling prices for current squad
    selling_prices = {
        p_id: selling_price(state.purchase_price(p_id), players_map[p_id].price_tenths)
        for p_id in state.player_ids if p_id in players_map
    }

    # Only recommend available active players (strictly excluding departed players)
    candidate_pool = [
        p
        for p in players_map.values()
        if p.id not in squad_set
        and p.status in ("a", "d")
        and not is_departed_from_premier_league(p)
        and not is_long_term_unavailable(p)
    ]

    # Candidate pool expansion vs pruning: V1.3.5/V1.4 uses pruned candidate pool (size 5) to mitigate regret tail
    if is_v135:
        cand_search_max = max(max_results, 5)
    elif not is_legacy:
        cand_search_max = max(max_results * 2, 25)
    else:
        cand_search_max = max_results
    raw_results, total_evaluated = solve_transfers(
        num_transfers=num_transfers,
        squad_players=squad_players,
        candidate_pool=candidate_pool,
        bank_tenths=state.bank_tenths,
        free_transfers=state.free_transfers,
        selling_prices=selling_prices,
        fdr_map=fdr_map,
        ticker_map=ticker_map,
        risk_profile=risk_profile,
        max_results=cand_search_max,
        dead_capital_weight=dead_capital_weight,
    )

    if is_legacy:
        top_results = raw_results[:max_results]
        report = {
            "num_transfers": num_transfers,
            "free_transfers_available": state.free_transfers,
            "risk_profile": risk_profile,
            "engine": "legacy",
            "target_gameweeks": target_gws,
            "evaluation_horizon_gws": num_gameweeks,
            "total_options_evaluated": total_evaluated,
            "top_suggestions": top_results,
        }
    else:
        from .backtest.decision_engine import _evaluate_squad_multi_horizon_lineup_xp

        eff_horizon = 1 if is_v12 else min(num_gameweeks, horizon)
        eff_gamma = 1.0 if is_v12 else gamma

        # Build projections across the rolling horizon
        projections_by_gw: dict[int, dict[int, float]] = {}
        for gw_idx, gw in enumerate(target_gws[:eff_horizon]):
            if gw_idx == 0:
                projections_by_gw[gw] = {p.id: p.expected_points for p in players_map.values()}
            else:
                try:
                    projs = project_gameweek(gw, database_path=database_path)
                    projections_by_gw[gw] = {p.player_id: p.expected_points for p in projs}
                except Exception:
                    projections_by_gw[gw] = {p.id: p.expected_points for p in players_map.values()}

        curr_lineup_xp = _evaluate_squad_multi_horizon_lineup_xp(
            squad_players, projections_by_gw, horizon=eff_horizon, gamma=eff_gamma, bench_w=0.15
        )
        curr_single_lineup_xp = _evaluate_squad_multi_horizon_lineup_xp(
            squad_players, projections_by_gw, horizon=1, gamma=1.0, bench_w=0.15
        )

        rescored_results: list[dict[str, Any]] = []
        for idx, rec in enumerate(raw_results):
            out_ids = [p["id"] for p in rec.get("outgoing", [])]
            in_ids = [p["id"] for p in rec.get("incoming", [])]
            out_set = set(out_ids)

            if len(squad_players) == 15:
                new_squad = [p for p in squad_players if p.id not in out_set] + [
                    players_map[pid] for pid in in_ids if pid in players_map
                ]
                new_lineup_xp = _evaluate_squad_multi_horizon_lineup_xp(
                    new_squad, projections_by_gw, horizon=eff_horizon, gamma=eff_gamma, bench_w=0.15
                )
                lineup_delta = round(new_lineup_xp - curr_lineup_xp, 2)

                if eff_horizon > 1:
                    new_single_lineup_xp = _evaluate_squad_multi_horizon_lineup_xp(
                        new_squad, projections_by_gw, horizon=1, gamma=1.0, bench_w=0.15
                    )
                    single_delta = round(new_single_lineup_xp - curr_single_lineup_xp, 2)
                    multi_horizon_gain = round(lineup_delta - single_delta, 2)
                else:
                    multi_horizon_gain = 0.0

                hits = rec.get("transfer_hits", 0)
                hit_pts = hits * 4
                fdr_gain = rec.get("fdr_improvement", 0.0)
                dead_cap_gain = rec.get("dead_capital_bonus", 0.0)
                v125_net_gain = round(lineup_delta - hit_pts + 0.1 * fdr_gain + dead_cap_gain, 2)
            else:
                lineup_delta = rec.get("xp_delta", 0.0)
                v125_net_gain = rec.get("score", 0.0)
                multi_horizon_gain = 0.0

            # Role-Specific Transfer Hurdle & GK Playing Security Invariant (Pillar 2)
            has_gk = any(
                p.get("position") in ("GKP", 1, Position.GOALKEEPER)
                or getattr(players_map.get(p["id"]), "position", None) == Position.GOALKEEPER
                for p in rec.get("outgoing", [])
            )
            if has_gk:
                incumbent_insecure = False
                for p in rec.get("outgoing", []):
                    p_meta = players_map.get(p["id"])
                    if p_meta and getattr(p_meta, "position", None) == Position.GOALKEEPER:
                        if getattr(p_meta, "status", "a") != "a" or getattr(p_meta, "play_probability", 1.0) < 0.50:
                            incumbent_insecure = True
                            break
                if incumbent_insecure:
                    hurdle = 0.50
                    gk_status = "approved_incumbent_insecure"
                else:
                    hurdle = 3.00 if eff_horizon >= 3 else 1.50
                    gk_status = "approved_hurdle_met" if v125_net_gain >= hurdle else "suppressed_high_hurdle"
            else:
                hurdle = 0.50
                gk_status = "n/a"

            hurdle_passed = bool(v125_net_gain >= hurdle)
            pool_expansion_surfaced = bool(idx >= 5)

            if has_gk and gk_status == "suppressed_high_hurdle":
                summary = f"GK swap (+{v125_net_gain:.2f} xP) suppressed below {hurdle:.2f} hurdle"
            elif pool_expansion_surfaced:
                summary = f"Pool expansion surfaced Starting XI upgrade (+{lineup_delta:.2f} xP)"
            elif multi_horizon_gain > 0.5:
                summary = f"Multi-GW fixture horizon elevated asset (+{multi_horizon_gain:.2f} xP over 1-GW)"
            else:
                summary = f"Lineup-optimized Starting XI move (+{lineup_delta:.2f} xP)"

            rec_copy = dict(rec)
            rec_copy["lineup_xp_delta"] = lineup_delta
            rec_copy["v125_net_gain"] = v125_net_gain
            rec_copy["hurdle"] = hurdle
            rec_copy["hurdle_passed"] = hurdle_passed
            rec_copy["score"] = v125_net_gain
            rec_copy["net_xp_gain"] = v125_net_gain
            rec_copy["reason_breakdown"] = {
                "pool_expansion_surfaced": pool_expansion_surfaced,
                "gk_suppression": gk_status,
                "multi_horizon_gain": multi_horizon_gain,
                "hurdle": hurdle,
                "hurdle_passed": hurdle_passed,
                "summary": summary,
            }
            rescored_results.append(rec_copy)

        rescored_results.sort(
            key=lambda r: (r.get("hurdle_passed", True), r.get("v125_net_gain", r.get("score", 0.0))),
            reverse=True,
        )
        top_results = rescored_results[:max_results]

        report = {
            "num_transfers": num_transfers,
            "free_transfers_available": state.free_transfers,
            "risk_profile": risk_profile,
            "engine": engine_name,
            "target_gameweeks": target_gws,
            "evaluation_horizon_gws": eff_horizon,
            "gamma": eff_gamma,
            "total_options_evaluated": total_evaluated,
            "top_suggestions": top_results,
            "transfer_reason_breakdown": {
                "engine": engine_name,
                "pool_expansion_candidates": sum(
                    1 for r in top_results if r.get("reason_breakdown", {}).get("pool_expansion_surfaced")
                ),
                "gk_suppression_active": any(
                    r.get("reason_breakdown", {}).get("gk_suppression") not in ("n/a", "approved_hurdle_met")
                    for r in top_results
                ),
            },
        }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return report


def suggest_wildcard(
    budget_millions: float | None = None,
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    num_gameweeks: int = 5,
    risk_profile: str = "neutral",
    locked_player_ids: list[int] | set[int] | None = None,
    excluded_player_ids: list[int] | set[int] | None = None,
    preferred_player_ids: list[int] | set[int] | None = None,
    strategic_engine: bool = False,
    report_path: Path = WILDCARD_REPORT_PATH,
) -> dict[str, Any]:
    """Generate 15-player squad (Wildcard) under budget and club limits with V1.1 strategic support."""
    if strategic_engine or locked_player_ids or excluded_player_ids or preferred_player_ids:
        return suggest_strategic_squad(
            mode="wildcard",
            budget_millions=budget_millions,
            squad_path=squad_path,
            database_path=database_path,
            num_gameweeks=num_gameweeks,
            strategy=risk_profile if risk_profile in ("maximum_ev", "balanced", "floor", "ceiling", "flexibility", "defend_lead", "chase") else "balanced",
            locked_player_ids=locked_player_ids,
            excluded_player_ids=excluded_player_ids,
            preferred_player_ids=preferred_player_ids,
            report_path=report_path,
        )

    risk_profile = validate_risk_profile(risk_profile)

    state = load_current_squad(squad_path)
    store = SnapshotStore(database_path)
    start_gw = get_current_gameweek(store)
    target_gws = list(range(start_gw, start_gw + num_gameweeks))
    profiles_map = project_multi_gameweek_profiles(target_gws, database_path=database_path)
    players_map, team_map = load_all_players_meta(store, profiles_map)

    # Determine budget: if not specified, sum current squad selling values + bank
    if budget_millions is not None:
        budget_tenths = int(round(budget_millions * 10))
    else:
        squad_selling_value = sum(
            selling_price(state.purchase_price(p_id), players_map[p_id].price_tenths)
            for p_id in state.player_ids
            if p_id in players_map
        )
        budget_tenths = state.bank_tenths + squad_selling_value

    candidate_pool = [
        p
        for p in players_map.values()
        if p.status in ("a", "d")
        and not is_departed_from_premier_league(p)
        and not is_long_term_unavailable(p)
    ]
    result = solve_wildcard(
        candidate_pool=candidate_pool,
        budget_tenths=budget_tenths,
        risk_profile=risk_profile,
    )
    result["target_gameweeks"] = target_gws
    result["evaluation_horizon_gws"] = num_gameweeks

    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return result


def suggest_strategic_squad(
    mode: str = "initial",
    budget_millions: float | None = None,
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    num_gameweeks: int = 5,
    strategy: str = "balanced",
    constraints: StrategicConstraints | None = None,
    locked_player_ids: list[int] | set[int] | None = None,
    excluded_player_ids: list[int] | set[int] | None = None,
    preferred_player_ids: list[int] | set[int] | None = None,
    previous_result: dict[str, Any] | None = None,
    generate_all_candidates: bool = True,
    report_path: Path | None = None,
) -> dict[str, Any]:
    """Generate strategic squad solution(s) under explicit constraints and strategic objectives (V1.1)."""
    store = SnapshotStore(database_path)
    start_gw = get_current_gameweek(store)
    if mode == "free_hit":
        h_len = 1
    else:
        h_len = max(1, min(8, num_gameweeks))

    target_gws = list(range(start_gw, start_gw + h_len))
    profiles_map = project_multi_gameweek_profiles(target_gws, database_path=database_path)
    players_map, team_map = load_all_players_meta(store, profiles_map)

    # Calculate budget
    if budget_millions is not None:
        budget_tenths = int(round(budget_millions * 10))
    elif constraints is not None and constraints.budget_tenths:
        budget_tenths = constraints.budget_tenths
    elif mode == "initial":
        budget_tenths = 1000  # Default £100.0m for season start
    else:
        try:
            state = load_current_squad(squad_path)
            squad_selling_value = sum(
                selling_price(state.purchase_price(p_id), players_map[p_id].price_tenths)
                for p_id in state.player_ids
                if p_id in players_map
            )
            budget_tenths = state.bank_tenths + squad_selling_value
        except Exception:
            budget_tenths = 1000

    if constraints is not None:
        effective_constraints = StrategicConstraints(
            budget_tenths=budget_tenths,
            locked_player_ids=set(constraints.locked_player_ids) | set(locked_player_ids or ()),
            excluded_player_ids=set(constraints.excluded_player_ids) | set(excluded_player_ids or ()),
            preferred_player_ids=set(constraints.preferred_player_ids) | set(preferred_player_ids or ()),
            max_players_per_club=constraints.max_players_per_club,
            position_quotas=constraints.position_quotas,
            min_bank_tenths=constraints.min_bank_tenths,
            soft_preference_weight=constraints.soft_preference_weight,
            target_gameweeks=tuple(target_gws),
        )
    else:
        effective_constraints = StrategicConstraints(
            budget_tenths=budget_tenths,
            locked_player_ids=set(locked_player_ids or ()),
            excluded_player_ids=set(excluded_player_ids or ()),
            preferred_player_ids=set(preferred_player_ids or ()),
            target_gameweeks=tuple(target_gws),
        )

    candidate_pool = list(players_map.values())
    primary_candidate = solve_strategic_squad(
        candidate_pool=candidate_pool,
        constraints=effective_constraints,
        strategy=strategy,
        mode=mode,
        horizon=h_len,
    )
    res = primary_candidate.to_dict()
    res["selected_candidate"] = primary_candidate.to_dict()
    res["mode"] = mode
    res["strategy"] = strategy
    res["horizon"] = h_len
    res["budget_millions"] = budget_tenths / 10.0
    res["bank_remaining_tenths"] = primary_candidate.bank_remaining_tenths

    if generate_all_candidates:
        failed_profiles_map: dict[str, str] = {}
        all_cands = generate_strategic_candidates(
            candidate_pool=candidate_pool,
            constraints=effective_constraints,
            mode=mode,
            horizon=h_len,
            failed_profiles=failed_profiles_map,
        )
        res["requested_profiles"] = getattr(all_cands, "requested_profiles", list(all_cands.keys()))
        res["successful_profiles"] = getattr(all_cands, "successful_profiles", list(all_cands.keys()))
        res["failed_profiles"] = failed_profiles_map
        res["strategic_candidates"] = {
            strat: cand.to_dict() for strat, cand in all_cands.items()
        }
        res["candidates"] = [cand.to_dict() for cand in all_cands.values()]
    else:
        res["requested_profiles"] = [strategy]
        res["successful_profiles"] = [strategy]
        res["failed_profiles"] = {}
        res["candidates"] = [primary_candidate.to_dict()]

    if previous_result:
        from .strategic_squad import analyze_constraint_impact
        prev_cand_dict = previous_result.get("selected_candidate") or previous_result
        try:
            res["constraint_impact"] = analyze_constraint_impact(prev_cand_dict, primary_candidate)
        except Exception:
            res["constraint_impact"] = None
    else:
        res["constraint_impact"] = None

    out_path = report_path or (
        INITIAL_SQUAD_REPORT_PATH
        if mode == "initial"
        else (WILDCARD_REPORT_PATH if mode == "wildcard" else STRATEGIC_SQUAD_REPORT_PATH)
    )
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return res


def suggest_initial_squad(
    budget_millions: float = 100.0,
    database_path: Path = DATABASE_PATH,
    num_gameweeks: int = 5,
    strategy: str = "balanced",
    locked_player_ids: list[int] | set[int] | None = None,
    excluded_player_ids: list[int] | set[int] | None = None,
    preferred_player_ids: list[int] | set[int] | None = None,
    generate_all_candidates: bool = True,
    report_path: Path = INITIAL_SQUAD_REPORT_PATH,
) -> dict[str, Any]:
    """Generate strategic starting squad for Gameweek 1 over an initial planning horizon (V1.1)."""
    return suggest_strategic_squad(
        mode="initial",
        budget_millions=budget_millions,
        database_path=database_path,
        num_gameweeks=num_gameweeks,
        strategy=strategy,
        locked_player_ids=locked_player_ids,
        excluded_player_ids=excluded_player_ids,
        preferred_player_ids=preferred_player_ids,
        generate_all_candidates=generate_all_candidates,
        report_path=report_path,
    )


def suggest_free_hit(
    budget_millions: float | None = None,
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    strategy: str = "maximum_ev",
    locked_player_ids: list[int] | set[int] | None = None,
    excluded_player_ids: list[int] | set[int] | None = None,
    preferred_player_ids: list[int] | set[int] | None = None,
    report_path: Path | None = None,
) -> dict[str, Any]:
    """Generate 1-Gameweek optimal temporary squad for Free Hit (V1.1)."""
    return suggest_strategic_squad(
        mode="free_hit",
        budget_millions=budget_millions,
        squad_path=squad_path,
        database_path=database_path,
        num_gameweeks=1,
        strategy=strategy,
        locked_player_ids=locked_player_ids,
        excluded_player_ids=excluded_player_ids,
        preferred_player_ids=preferred_player_ids,
        generate_all_candidates=True,
        report_path=report_path,
    )





