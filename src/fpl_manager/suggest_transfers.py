"""Transfer suggestion and Wildcard/Free-Hit squad recommendation service (V1.0.1).

Coordinates multi-gameweek expected points projections, fixture difficulty ratings,
and squad selling-price rules with the combinatorial optimizers in `fpl_manager.optimizer`.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .expected_points import (
    MultiGameweekProfile,
    project_multi_gameweek_profiles,
)
from .fixtures import analyze_team_fixtures, get_current_gameweek
from .models import Position
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
            SELECT player_id, web_name, position_id, team_id, price_tenths, status, total_points
            FROM players
            WHERE snapshot_id = ?
            """,
            (snapshot_id,),
        ).fetchall()

    players_map: dict[int, PlayerInfo] = {}
    for p_id, web_name, pos_id, t_id, price, status, pts in players_rows:
        t_short = team_map.get(t_id, f"T{t_id}")
        prof = profiles_map.get(p_id) if profiles_map else None
        if isinstance(prof, MultiGameweekProfile):
            p_xp = prof.expected_points
            p_xm = prof.expected_minutes
            p_floor = prof.xp_floor
            p_ceil = prof.xp_ceiling
            p_std = prof.standard_deviation
        elif isinstance(prof, (int, float)):
            p_xp = float(prof)
            p_xm = 0.0
            p_floor = 0.0
            p_ceil = 0.0
            p_std = 0.0
        else:
            p_xp = 0.0
            p_xm = 0.0
            p_floor = 0.0
            p_ceil = 0.0
            p_std = 0.0

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
) -> dict[str, Any]:
    """Generate legal 1- to 5-transfer move recommendations for the current squad using branch-and-bound optimization."""
    if num_transfers < 1 or num_transfers > 5:
        raise ValueError(
            f"Invalid num_transfers={num_transfers}. Optimizer supports between 1 and 5 transfers."
        )

    risk_profile = validate_risk_profile(risk_profile)

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

    # Only recommend available active players
    candidate_pool = [p for p in players_map.values() if p.id not in squad_set and p.status in ("a", "d")]

    top_results, total_evaluated = solve_transfers(
        num_transfers=num_transfers,
        squad_players=squad_players,
        candidate_pool=candidate_pool,
        bank_tenths=state.bank_tenths,
        free_transfers=state.free_transfers,
        selling_prices=selling_prices,
        fdr_map=fdr_map,
        ticker_map=ticker_map,
        risk_profile=risk_profile,
        max_results=max_results,
    )

    report = {
        "num_transfers": num_transfers,
        "free_transfers_available": state.free_transfers,
        "risk_profile": risk_profile,
        "target_gameweeks": target_gws,
        "evaluation_horizon_gws": num_gameweeks,
        "total_options_evaluated": total_evaluated,
        "top_suggestions": top_results,
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

    candidate_pool = list(players_map.values())
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
        all_cands = generate_strategic_candidates(
            candidate_pool=candidate_pool,
            constraints=effective_constraints,
            mode=mode,
            horizon=h_len,
        )
        res["strategic_candidates"] = {
            strat: cand.to_dict() for strat, cand in all_cands.items()
        }
        res["candidates"] = [cand.to_dict() for cand in all_cands.values()]
    else:
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





