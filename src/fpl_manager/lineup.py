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
        gameweek = get_current_gameweek(store)

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

    def serialize_player(proj: ExpectedPointsProjection, role: str) -> dict[str, Any]:
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
            "ownership_pct": own,
            "effective_ownership_pct": eo,
            "strategic_category": cat,
            "net_exposure_pct": net_exposure,
            "fixtures_summary": _format_fixture_summary(proj),
            "role": role,
        }

    starters_serialized = []
    for p in best_starters:
        role = "STARTER"
        if p.player_id == captain.player_id:
            role = "CAPTAIN"
        elif p.player_id == vice_captain.player_id:
            role = "VICE_CAPTAIN"
        starters_serialized.append(serialize_player(p, role))

    bench_serialized = []
    for idx, p in enumerate(best_bench):
        bench_role = "GK_SUB" if idx == 0 else f"SUB_{idx}"
        bench_serialized.append(serialize_player(p, bench_role))

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
        "captain": serialize_player(captain, "CAPTAIN"),
        "vice_captain": serialize_player(vice_captain, "VICE_CAPTAIN"),
        "starters": starters_serialized,
        "bench": bench_serialized,
        "all_squad": [serialize_player(p, "SQUAD") for p in projections],
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return report
