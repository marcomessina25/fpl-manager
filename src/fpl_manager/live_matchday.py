"""Live Matchday Points & Rank Tracker for FPL Manager V0.6.

Calculates real-time live matchday points, handles dynamic autosubstitutions
with formation legality enforcement, captaincy auto-promotion, chip impacts
(Triple Captain, Bench Boost), and rank velocity / effective ownership simulations.
"""

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .decision_log import get_gameweek_decision
from .fixtures import get_current_gameweek
from .models import Position
from .ownership import estimate_captaincy_shares, get_player_ownership_map
from .scores import get_detailed_player_gameweek_stats
from .squad_state import CurrentSquadState, load_current_squad
from .storage import SnapshotStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"
REPORTS_DIRECTORY = PROJECT_ROOT / "reports"
LIVE_REPORT_PATH = REPORTS_DIRECTORY / "live_matchday.json"
LIVE_MD_PATH = REPORTS_DIRECTORY / "live_matchday.md"


def get_live_gameweek_matchday_summary(
    gameweek: int | None = None,
    squad_path: Path = DEFAULT_SQUAD_PATH,
    team_id: str = "default",
    season: str = "2026/27",
    database_path: Path = DATABASE_PATH,
    force_fetch: bool = False,
    save_reports: bool = True,
) -> dict[str, Any]:
    """Calculate real-time matchday performance with autosubs, captain multiplier, and rank simulation."""
    store = SnapshotStore(database_path)
    store.initialize()

    state: CurrentSquadState = load_current_squad(squad_path)
    if gameweek is None:
        gameweek = state.gameweek or get_current_gameweek(store)

    # 1. Fetch detailed player live matchday stats
    live_stats = get_detailed_player_gameweek_stats(gameweek, database_path=database_path, force_fetch=force_fetch)

    # 2. Fetch fixture statuses for this gameweek
    finished_teams = set()
    started_teams = set()
    with closing(store._connect()) as conn:
        snap = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        snap_id = snap[0] if snap else 1

        rows = conn.execute(
            """
            SELECT team_h, team_a, finished, kickoff_time
            FROM fixtures
            WHERE snapshot_id = ? AND event = ?
            """,
            (snap_id, gameweek),
        ).fetchall()

        now_iso = datetime.now(timezone.utc).isoformat()
        for th, ta, finished, ko_time in rows:
            is_finished = bool(finished)
            is_started = is_finished or (ko_time is not None and ko_time <= now_iso)
            if is_finished:
                finished_teams.add(th)
                finished_teams.add(ta)
            if is_started:
                started_teams.add(th)
                started_teams.add(ta)

    # 3. Fetch player metadata (web_name, position_id, team_id)
    player_meta = {}
    with closing(store._connect()) as conn:
        rows = conn.execute(
            """
            SELECT p.player_id, p.web_name, p.position_id, t.short_name, p.team_id
            FROM players p
            JOIN teams t ON p.snapshot_id = t.snapshot_id AND p.team_id = t.team_id
            WHERE p.snapshot_id = ?
            """,
            (snap_id,),
        ).fetchall()
        for pid, name, pos_id, team_code, tid in rows:
            pos_enum = Position(pos_id)
            player_meta[pid] = {
                "id": pid,
                "name": name,
                "position": pos_enum,
                "pos_name": pos_enum.name,
                "pos_abbr": {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}.get(pos_id, "MID"),
                "team": team_code,
                "team_id": tid,
            }

    # 4. Resolve lineup decision
    decision = get_gameweek_decision(gameweek, season=season, team_id=team_id, database_path=database_path)
    if decision is not None:
        starting_ids = list(decision.get("starting_player_ids", []))
        bench_ids = list(decision.get("bench_player_ids", []))
        captain_id = decision.get("captain_id")
        vice_captain_id = decision.get("vice_captain_id")
        chip_played = decision.get("chip_played")
        transfer_hits = decision.get("transfer_hits", 0)
    else:
        from .lineup import select_starting_lineup
        lineup_sol = select_starting_lineup(squad_path=squad_path, database_path=database_path, gameweek=gameweek)
        starting_ids = [p["id"] for p in lineup_sol["starters"]]
        bench_ids = [p["id"] for p in lineup_sol["bench"]]
        captain_id = lineup_sol["captain"]["id"]
        vice_captain_id = lineup_sol["vice_captain"]["id"]
        chip_played = None
        transfer_hits = 0

    chip_norm = str(chip_played).lower().strip() if chip_played else None
    is_triple_cap = chip_norm in ("triplecaptain", "triple_captain", "tc", "3xc")
    is_bench_boost = chip_norm in ("benchboost", "bench_boost", "bb")

    # Helper to check player match status
    def _get_player_match_status(pid: int) -> dict[str, Any]:
        meta = player_meta.get(pid, {})
        tid = meta.get("team_id")
        stats = live_stats.get(pid, {
            "total_points": 0, "minutes": 0, "goals_scored": 0, "assists": 0,
            "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 0,
        })
        is_fin = tid in finished_teams if tid else False
        is_start = is_fin or (tid in started_teams if tid else False)
        return {
            **meta,
            **stats,
            "match_finished": is_fin,
            "match_started": is_start,
        }

    starters_info = [_get_player_match_status(pid) for pid in starting_ids]
    bench_info = [_get_player_match_status(pid) for pid in bench_ids]

    # 5. Captaincy Promotion
    # If captain played 0 mins AND match is finished -> promote vice captain!
    cap_info = next((p for p in starters_info if p["id"] == captain_id), None)
    cap_promoted = False
    active_cap_id = captain_id
    if cap_info and cap_info["match_finished"] and cap_info["minutes"] == 0:
        active_cap_id = vice_captain_id
        cap_promoted = True

    cap_multiplier = 3 if is_triple_cap else 2

    # 6. Automatic Substitutions (only relevant if not Bench Boost)
    # Track starters and autosub swaps
    autosubs = []
    active_starters = list(starters_info)
    available_bench = [dict(b) for b in bench_info]

    if not is_bench_boost:
        # Check Goalkeeper first
        gk_starter = next((p for p in active_starters if p["position"] == Position.GOALKEEPER), None)
        if gk_starter and gk_starter["match_finished"] and gk_starter["minutes"] == 0:
            gk_bench = next((b for b in available_bench if b["position"] == Position.GOALKEEPER), None)
            if gk_bench and (gk_bench["minutes"] > 0 or not gk_bench["match_finished"]):
                # Swap GK
                idx = active_starters.index(gk_starter)
                active_starters[idx] = gk_bench
                available_bench.remove(gk_bench)
                autosubs.append({
                    "out": {"id": gk_starter["id"], "name": gk_starter["name"], "position": "GKP"},
                    "in": {"id": gk_bench["id"], "name": gk_bench["name"], "position": "GKP", "points": gk_bench["total_points"]},
                    "reason": "Goalkeeper played 0 minutes and match finished",
                })

        # Check Outfield Starters
        # Count outfield positions
        def _get_formation(starters_list: list[dict[str, Any]]) -> tuple[int, int, int]:
            d = sum(1 for p in starters_list if p["position"] == Position.DEFENDER)
            m = sum(1 for p in starters_list if p["position"] == Position.MIDFIELDER)
            f = sum(1 for p in starters_list if p["position"] == Position.FORWARD)
            return d, m, f

        for s in list(active_starters):
            if s["position"] == Position.GOALKEEPER:
                continue
            if s["match_finished"] and s["minutes"] == 0:
                # Need an outfield sub from available bench in order
                outfield_bench = [b for b in available_bench if b["position"] != Position.GOALKEEPER]
                sub_found = None
                for b in outfield_bench:
                    if b["minutes"] == 0 and b["match_finished"]:
                        continue  # Bench player also didn't play

                    # Test formation legality: minimum 3 DEF, 2 MID, 1 FWD
                    tentative = list(active_starters)
                    idx = tentative.index(s)
                    tentative[idx] = b
                    d, m, f = _get_formation(tentative)
                    if d >= 3 and m >= 2 and f >= 1:
                        sub_found = b
                        break

                if sub_found:
                    idx = active_starters.index(s)
                    active_starters[idx] = sub_found
                    available_bench.remove(sub_found)
                    autosubs.append({
                        "out": {"id": s["id"], "name": s["name"], "position": s["pos_abbr"]},
                        "in": {"id": sub_found["id"], "name": sub_found["name"], "position": sub_found["pos_abbr"], "points": sub_found["total_points"]},
                        "reason": f"{s['pos_abbr']} played 0 minutes and match finished",
                    })

    # 7. Points Calculation
    gross_points = 0
    starters_serialized = []
    subbed_out_ids = set(sub["out"]["id"] for sub in autosubs)
    subbed_in_ids = set(sub["in"]["id"] for sub in autosubs)

    for p in active_starters:
        pid = p["id"]
        mult = cap_multiplier if pid == active_cap_id else 1
        raw_pts = p["total_points"]
        total_pts = raw_pts * mult
        gross_points += total_pts

        role = "STARTER"
        if pid == active_cap_id:
            role = "CAPTAIN (TC)" if is_triple_cap else "CAPTAIN"
        elif pid == vice_captain_id and not cap_promoted:
            role = "VICE_CAPTAIN"

        starters_serialized.append({
            "id": pid,
            "name": p["name"],
            "team": p["team"],
            "position": p["pos_abbr"],
            "role": role,
            "multiplier": mult,
            "raw_points": raw_pts,
            "points": total_pts,
            "minutes": p["minutes"],
            "goals": p["goals_scored"],
            "assists": p["assists"],
            "clean_sheet": p["clean_sheets"],
            "goals_conceded": p["goals_conceded"],
            "bonus": p["bonus"],
            "bps": p["bps"],
            "match_finished": p["match_finished"],
            "subbed_in": pid in subbed_in_ids,
        })

    bench_serialized = []
    for idx, p in enumerate(bench_info, 1):
        pid = p["id"]
        raw_pts = p["total_points"]
        is_subbed_in = pid in subbed_in_ids
        counts = is_bench_boost or is_subbed_in
        if is_bench_boost and not is_subbed_in:
            gross_points += raw_pts

        bench_serialized.append({
            "id": pid,
            "name": p["name"],
            "team": p["team"],
            "position": p["pos_abbr"],
            "order": idx,
            "raw_points": raw_pts,
            "points": raw_pts if counts else 0,
            "counted_in_total": counts,
            "minutes": p["minutes"],
            "goals": p["goals_scored"],
            "assists": p["assists"],
            "clean_sheet": p["clean_sheets"],
            "bonus": p["bonus"],
            "bps": p["bps"],
            "match_finished": p["match_finished"],
            "subbed_in": is_subbed_in,
        })

    hit_cost = transfer_hits * 4
    net_points = gross_points - hit_cost

    # 8. Effective Ownership & Live Rank Momentum Simulation
    ownership_map = get_player_ownership_map(database_path)
    projections = []
    try:
        from .expected_points import project_gameweek
        projections = project_gameweek(gameweek=gameweek, database_path=database_path)
    except Exception:
        pass
    captaincy_map = estimate_captaincy_shares(projections, ownership_map)

    owned_accelerators = []
    for p in starters_serialized:
        pid = p["id"]
        own_pct = ownership_map.get(pid, 0.0)
        cap_pct = captaincy_map.get(pid, 0.0)
        eo_pct = own_pct + cap_pct
        # Positive leverage swing: points scored * (1 - EO/100)
        leverage = p["points"] * (1.0 - (eo_pct / 100.0))
        if p["points"] > 0:
            owned_accelerators.append({
                "name": p["name"],
                "team": p["team"],
                "points": p["points"],
                "eo_pct": round(eo_pct, 1),
                "rank_delta_pts": round(leverage, 2),
            })

    owned_accelerators.sort(key=lambda x: x["rank_delta_pts"], reverse=True)

    summary = {
        "gameweek": gameweek,
        "team_id": team_id,
        "season": season,
        "chip_played": chip_played,
        "transfer_hits": transfer_hits,
        "hit_cost": hit_cost,
        "gross_points": gross_points,
        "net_points": net_points,
        "captain": {
            "id": active_cap_id,
            "name": player_meta.get(active_cap_id, {}).get("name", f"ID {active_cap_id}"),
            "multiplier": cap_multiplier,
            "promoted_from_vice": cap_promoted,
            "points": (cap_info["total_points"] if not cap_promoted and cap_info else (live_stats.get(active_cap_id, {}).get("total_points", 0))) * cap_multiplier,
        },
        "starters": starters_serialized,
        "bench": bench_serialized,
        "autosubs": autosubs,
        "rank_accelerators": owned_accelerators[:5],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    markdown_text = _build_live_matchday_markdown(summary)
    summary["markdown"] = markdown_text

    if save_reports:
        REPORTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
        LIVE_REPORT_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        LIVE_MD_PATH.write_text(markdown_text, encoding="utf-8")

    return summary


def _build_live_matchday_markdown(summary: dict[str, Any]) -> str:
    """Render live matchday points and autosubs into clean formatted Markdown."""
    gw = summary["gameweek"]
    net = summary["net_points"]
    gross = summary["gross_points"]
    hits = summary["hit_cost"]
    cap = summary["captain"]
    chip = summary["chip_played"]
    subs = summary["autosubs"]

    chip_txt = f" · Chip: `{chip.upper()}`" if chip else ""
    hit_txt = f" (Gross: {gross} pts - {hits} hit pts)" if hits > 0 else ""

    lines = [
        f"# Live Matchday Tracker — Gameweek {gw}",
        f"**Live Score**: **{net} pts**{hit_txt}{chip_txt} | **Captain**: {cap['name']} ({cap['multiplier']}x, {cap['points']} pts)",
        "",
        "### Starting XI Live Points",
        "| Pos | Player | Team | Min | G | A | CS | Bonus | Pts | Match Status |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    for p in summary["starters"]:
        fin_txt = "Finished" if p["match_finished"] else "Live / Upcoming"
        role_marker = " (TC)" if "TC" in p["role"] else (" (C)" if p["role"] == "CAPTAIN" else (" (VC)" if p["role"] == "VICE_CAPTAIN" else ""))
        sub_marker = " 🔄" if p["subbed_in"] else ""
        lines.append(
            f"| {p['position']} | **{p['name']}**{role_marker}{sub_marker} | {p['team']} | {p['minutes']}' | "
            f"{p['goals']} | {p['assists']} | {p['clean_sheet']} | {p['bonus']} | **{p['points']}** | {fin_txt} |"
        )

    lines.extend([
        "",
        "### Bench Substitutes",
        "| Pos | Player | Team | Min | Pts | Counted | Status |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :--- |",
    ])
    for p in summary["bench"]:
        fin_txt = "Finished" if p["match_finished"] else "Live / Upcoming"
        counted_txt = "✅ Yes" if p["counted_in_total"] else "No"
        lines.append(
            f"| {p['position']} | {p['name']} | {p['team']} | {p['minutes']}' | {p['raw_points']} | {counted_txt} | {fin_txt} |"
        )

    if subs:
        lines.extend([
            "",
            "### 🔄 Automatic Substitutions Applied",
        ])
        for s in subs:
            lines.append(f"- 🔄 **OUT**: {s['out']['name']} ({s['out']['position']}) ➔ **IN**: **{s['in']['name']}** ({s['in']['position']}, **+{s['in']['points']} pts**): *{s['reason']}*")

    acc = summary.get("rank_accelerators", [])
    if acc:
        lines.extend([
            "",
            "### 🚀 Rank Accelerators (Top Swing Assets)",
        ])
        for a in acc:
            lines.append(f"- ⭐ **{a['name']}** ({a['team']}): **{a['points']} pts** (EO: {a['eo_pct']}%) ➔ **+{a['rank_delta_pts']} pts** rank advantage")

    return "\n".join(lines)
