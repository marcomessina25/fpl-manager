"""Starting-XI and captaincy selection optimizer for FPL Manager V0.2.

Selects the legal 11-player starting lineup that maximizes projected expected points (xP),
orders the bench optimally, and selects primary and vice-captain choices.
Every proposed lineup is independently verified against the deterministic formation
rules in `fpl_manager.rules`.
"""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .expected_points import ExpectedPointsProjection, project_gameweek
from .fixtures import get_current_gameweek
from .models import Player, Position
from .rules import validate_starting_lineup
from .squad_state import CurrentSquadState, load_current_squad
from .storage import SnapshotStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"
LINEUP_REPORT_PATH = PROJECT_ROOT / "reports" / "lineup_report.json"

# All legal outfield formation distributions in FPL (DEF, MID, FWD) summing to 10 outfield starters:
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


def _format_fixture_summary(proj: ExpectedPointsProjection) -> str:
    if not proj.fixtures:
        return "BLANK"
    parts = []
    for f in proj.fixtures:
        parts.append(f"{f.opponent_short} ({f.venue}, FDR {f.fdr})")
    return ", ".join(parts)


def select_starting_lineup(
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    gameweek: int | None = None,
    report_path: Path = LINEUP_REPORT_PATH,
) -> dict[str, Any]:
    """Determine optimal legal starting 11, captain, vice-captain, and ordered bench."""
    state: CurrentSquadState = load_current_squad(squad_path)
    store = SnapshotStore(database_path)

    if gameweek is None:
        gameweek = state.gameweek or get_current_gameweek(store)

    projections = project_gameweek(
        gameweek=gameweek,
        player_ids=state.player_ids,
        database_path=database_path,
    )

    proj_map = {p.player_id: p for p in projections}
    if len(proj_map) != 15:
        raise RuntimeError(f"Expected 15 players in squad projections; received {len(proj_map)}.")

    # Group players by position, sorted by projected xP descending
    by_pos: dict[Position, list[ExpectedPointsProjection]] = {pos: [] for pos in Position}
    for p_id in state.player_ids:
        p = proj_map.get(p_id)
        if p is not None:
            by_pos[p.position].append(p)

    for pos in by_pos:
        by_pos[pos].sort(key=lambda p: (p.expected_points, p.base_xp_per_match), reverse=True)

    best_score = -float("inf")
    best_formation_name = "3-4-3"
    best_starters: list[ExpectedPointsProjection] = []
    best_bench: list[ExpectedPointsProjection] = []

    # Evaluate each legal formation
    for n_def, n_mid, n_fwd in LEGAL_FORMATIONS:
        # Starting selections
        starters_gk = by_pos[Position.GOALKEEPER][:1]
        starters_def = by_pos[Position.DEFENDER][:n_def]
        starters_mid = by_pos[Position.MIDFIELDER][:n_mid]
        starters_fwd = by_pos[Position.FORWARD][:n_fwd]

        starters = starters_gk + starters_def + starters_mid + starters_fwd
        starters_xp = sum(p.expected_points for p in starters)

        # Captain bonus (captain scores 2x, so add captain's xP again)
        sorted_for_cap = sorted(starters, key=lambda p: p.expected_points, reverse=True)
        captain_xp = sorted_for_cap[0].expected_points
        total_lineup_xp = round(starters_xp + captain_xp, 2)

        if total_lineup_xp > best_score:
            best_score = total_lineup_xp
            best_formation_name = f"{n_def}-{n_mid}-{n_fwd}"
            best_starters = starters

            # Bench setup: sub GK always in slot 0, then remaining outfield sorted by xP
            sub_gk = by_pos[Position.GOALKEEPER][1:2]
            sub_outfield = (
                by_pos[Position.DEFENDER][n_def:]
                + by_pos[Position.MIDFIELDER][n_mid:]
                + by_pos[Position.FORWARD][n_fwd:]
            )
            sub_outfield.sort(key=lambda p: (p.expected_points, p.base_xp_per_match), reverse=True)
            best_bench = sub_gk + sub_outfield

    # Independent rule verification against rules.py
    rules_squad = [
        Player(
            id=p.player_id,
            name=p.web_name,
            position=p.position,
            team_id=p.team_id,
            price_tenths=p.price_tenths,
        )
        for p in projections
    ]
    starter_ids = [p.player_id for p in best_starters]
    validation = validate_starting_lineup(rules_squad, starter_ids)
    if not validation.is_valid:
        raise RuntimeError(f"Selected starting lineup failed rule validation: {'; '.join(validation.errors)}")

    # Assign Captain and Vice-Captain
    starters_ranked = sorted(best_starters, key=lambda p: (p.expected_points, p.base_xp_per_match), reverse=True)
    captain = starters_ranked[0]
    vice_captain = starters_ranked[1]

    starters_xp = round(sum(p.expected_points for p in best_starters), 2)
    captain_bonus = captain.expected_points
    total_xp = round(starters_xp + captain_bonus, 2)
    total_floor = round(sum(p.xp_floor for p in best_starters) + captain.xp_floor, 2)
    total_ceiling = round(sum(p.xp_ceiling for p in best_starters) + captain.xp_ceiling, 2)

    try:
        from .ownership import (
            categorize_strategic_asset,
            compute_effective_ownership,
            estimate_captaincy_shares,
            get_player_ownership_map,
        )
        ownership_map = get_player_ownership_map(database_path)
        all_league_projs = project_gameweek(gameweek=gameweek, database_path=database_path)
        cap_map = estimate_captaincy_shares(all_league_projs, ownership_map)
    except Exception:
        ownership_map = {}
        cap_map = {}

    try:
        from .scores import get_or_fetch_gameweek_scores
        actual_scores = get_or_fetch_gameweek_scores(gameweek=gameweek, database_path=database_path)
    except Exception:
        actual_scores = {}

    starters_serialized = []
    for p in best_starters:
        role = "STARTER"
        if p.player_id == captain.player_id:
            role = "CAPTAIN"
        elif p.player_id == vice_captain.player_id:
            role = "VICE_CAPTAIN"
        starters_serialized.append(_serialize_lineup_player(p, role, ownership_map, cap_map, actual_scores))

    bench_serialized = []
    for idx, p in enumerate(best_bench):
        bench_role = "GK_SUB" if idx == 0 else f"SUB_{idx}"
        bench_serialized.append(_serialize_lineup_player(p, bench_role, ownership_map, cap_map, actual_scores))

    report = {
        "gameweek": gameweek,
        "formation": best_formation_name,
        "projected_points": {
            "starters_xp": starters_xp,
            "captain_bonus_xp": captain_bonus,
            "total_xp": total_xp,
            "floor_xp": total_floor,
            "ceiling_xp": total_ceiling,
        },
        "captain": _serialize_lineup_player(captain, "CAPTAIN", ownership_map, cap_map, actual_scores),
        "vice_captain": _serialize_lineup_player(vice_captain, "VICE_CAPTAIN", ownership_map, cap_map, actual_scores),
        "starters": starters_serialized,
        "bench": bench_serialized,
        "all_squad": [_serialize_lineup_player(p, "SQUAD", ownership_map, cap_map, actual_scores) for p in projections],
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return report


def _serialize_lineup_player(
    proj: ExpectedPointsProjection,
    role: str,
    ownership_map: dict[int, float],
    cap_map: dict[int, float],
    actual_scores: dict[int, float] | None = None,
    chip_played: str | None = None,
) -> dict[str, Any]:
    """Serialize player projection with tactical, strategic, and matchday scoring attributes."""
    own = ownership_map.get(proj.player_id, 0.0)
    cap_pct = cap_map.get(proj.player_id, 0.0)
    eo = round(own + cap_pct, 1)
    cat = "CORE"
    if eo >= 40.0 or own >= 35.0:
        cat = "SHIELD"
    elif (eo < 15.0 or own < 10.0) and (proj.expected_points >= 4.0 or proj.xp_ceiling >= 7.0):
        cat = "SWORD"
    personal_weight = 200.0 if role == "CAPTAIN" else (100.0 if role in ("STARTER", "VICE_CAPTAIN") else 0.0)
    net_exposure = round(personal_weight - eo, 1)

    raw_actual = actual_scores.get(proj.player_id) if actual_scores else None
    if raw_actual is not None:
        if role == "CAPTAIN":
            multiplier = 3 if chip_played in ("triplecaptain", "triple_captain", "3xc") else 2
            actual_pts = raw_actual * multiplier
        else:
            actual_pts = raw_actual
    else:
        actual_pts = None

    return {
        "id": proj.player_id,
        "name": proj.web_name,
        "position": proj.position.name,
        "pos_abbr": {Position.GOALKEEPER: "GKP", Position.DEFENDER: "DEF", Position.MIDFIELDER: "MID", Position.FORWARD: "FWD"}.get(proj.position, "MID"),
        "team": proj.team_short,
        "price_fmt": f"£{proj.price_tenths / 10:.1f}m",
        "status": proj.status,
        "availability_pct": proj.availability_pct,
        "expected_minutes": proj.expected_minutes,
        "start_probability": proj.start_probability,
        "expected_points": proj.expected_points,
        "xp_floor": proj.xp_floor,
        "xp_ceiling": proj.xp_ceiling,
        "actual_points": actual_pts,
        "raw_actual_points": raw_actual,
        "ownership_pct": own,
        "effective_ownership_pct": eo,
        "strategic_category": cat,
        "net_exposure_pct": net_exposure,
        "fixtures_summary": _format_fixture_summary(proj),
        "role": role,
    }


def build_logged_lineup(
    decision: dict[str, Any],
    database_path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    """Reconstruct complete lineup representation from a logged historical gameweek decision."""
    gameweek = decision["gameweek"]
    starting_ids = list(decision.get("starting_player_ids", []))
    bench_ids = list(decision.get("bench_player_ids", []))
    captain_id = decision.get("captain_id")
    vice_captain_id = decision.get("vice_captain_id")
    chip_played = decision.get("chip_played")
    transfers = decision.get("transfers", [])
    transfer_hits = decision.get("transfer_hits", 0)
    notes = decision.get("notes", "")

    all_ids = starting_ids + bench_ids

    projections = project_gameweek(
        gameweek=gameweek,
        player_ids=all_ids,
        database_path=database_path,
    )
    proj_map = {p.player_id: p for p in projections}

    # Fetch matchday scores if available
    try:
        from .scores import get_or_fetch_gameweek_scores
        actual_scores = get_or_fetch_gameweek_scores(gameweek=gameweek, database_path=database_path)
    except Exception:
        actual_scores = {}

    try:
        from .ownership import (
            estimate_captaincy_shares,
            get_player_ownership_map,
        )
        ownership_map = get_player_ownership_map(database_path)
        all_league_projs = project_gameweek(gameweek=gameweek, database_path=database_path)
        cap_map = estimate_captaincy_shares(all_league_projs, ownership_map)
    except Exception:
        ownership_map = {}
        cap_map = {}

    starting_projs = [proj_map[pid] for pid in starting_ids if pid in proj_map]
    defs = sum(1 for p in starting_projs if p.position == Position.DEFENDER)
    mids = sum(1 for p in starting_projs if p.position == Position.MIDFIELDER)
    fwds = sum(1 for p in starting_projs if p.position == Position.FORWARD)
    formation_name = f"{defs}-{mids}-{fwds}"

    cap_proj = proj_map.get(captain_id)
    vc_proj = proj_map.get(vice_captain_id)

    starters_serialized = []
    for pid in starting_ids:
        p = proj_map.get(pid)
        if not p:
            continue
        role = "STARTER"
        if pid == captain_id:
            role = "CAPTAIN"
        elif pid == vice_captain_id:
            role = "VICE_CAPTAIN"
        starters_serialized.append(
            _serialize_lineup_player(p, role, ownership_map, cap_map, actual_scores, chip_played)
        )

    bench_serialized = []
    gk_found = False
    sub_count = 1
    for pid in bench_ids:
        p = proj_map.get(pid)
        if not p:
            continue
        if p.position == Position.GOALKEEPER and not gk_found:
            bench_role = "GK_SUB"
            gk_found = True
        else:
            bench_role = f"SUB_{sub_count}"
            sub_count += 1
        bench_serialized.append(
            _serialize_lineup_player(p, bench_role, ownership_map, cap_map, actual_scores, chip_played)
        )

    starters_xp = round(sum(p.expected_points for p in starting_projs), 2)
    captain_bonus = round(cap_proj.expected_points if cap_proj else 0.0, 2)
    total_xp = decision.get("predicted_lineup_xp") or round(starters_xp + captain_bonus, 2)
    total_floor = decision.get("predicted_floor_xp") or round(sum(p.xp_floor for p in starting_projs) + (cap_proj.xp_floor if cap_proj else 0.0), 2)
    total_ceiling = decision.get("predicted_ceiling_xp") or round(sum(p.xp_ceiling for p in starting_projs) + (cap_proj.xp_ceiling if cap_proj else 0.0), 2)

    # Actual total points calculation if not stored
    if decision.get("actual_points") is not None:
        total_actual_points = decision["actual_points"]
    elif actual_scores and any(pid in actual_scores for pid in starting_ids):
        cap_mult = 2 if chip_played in ("triplecaptain", "triple_captain", "3xc") else 1
        starters_score = sum(actual_scores.get(pid, 0.0) for pid in starting_ids)
        cap_bonus_pts = actual_scores.get(captain_id, 0.0) * cap_mult
        bench_score = sum(actual_scores.get(pid, 0.0) for pid in bench_ids) if chip_played in ("benchboost", "bench_boost", "bboost") else 0.0
        total_actual_points = round(starters_score + cap_bonus_pts + bench_score - (transfer_hits * 4))
    else:
        total_actual_points = None

    captain_serialized = _serialize_lineup_player(cap_proj, "CAPTAIN", ownership_map, cap_map, actual_scores, chip_played) if cap_proj else None
    vc_serialized = _serialize_lineup_player(vc_proj, "VICE_CAPTAIN", ownership_map, cap_map, actual_scores, chip_played) if vc_proj else None

    return {
        "gameweek": gameweek,
        "team_id": decision.get("team_id", "default"),
        "season": decision.get("season", "2026/27"),
        "is_logged": True,
        "has_logged_decision": True,
        "decision_id": decision.get("decision_id"),
        "formation": formation_name,
        "actual_points": total_actual_points,
        "chip_played": chip_played,
        "transfers": transfers,
        "transfer_hits": transfer_hits,
        "notes": notes,
        "projected_points": {
            "starters_xp": starters_xp,
            "captain_bonus_xp": captain_bonus,
            "total_xp": total_xp,
            "floor_xp": total_floor,
            "ceiling_xp": total_ceiling,
        },
        "captain": captain_serialized,
        "vice_captain": vc_serialized,
        "starters": starters_serialized,
        "bench": bench_serialized,
        "all_squad": starters_serialized + bench_serialized,
    }
