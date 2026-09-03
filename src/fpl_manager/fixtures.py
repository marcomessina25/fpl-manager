"""Fixture analysis and Fixture Difficulty Rating (FDR) utilities for FPL Manager V0.2."""

import json
from pathlib import Path
from typing import Any

from .squad_state import load_current_squad
from .storage import SnapshotStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"
FIXTURES_REPORT_PATH = PROJECT_ROOT / "reports" / "fixtures_report.json"


def get_current_gameweek(store: SnapshotStore) -> int:
    """Find the next/current unfinished gameweek in the database."""
    store.initialize()
    with store._connect() as connection:
        snapshot = connection.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        if snapshot is None:
            raise RuntimeError("No FPL data found. Run `fpl update` first.")

        row = connection.execute(
            "SELECT MIN(event) FROM fixtures WHERE snapshot_id = ? AND finished = 0 AND event IS NOT NULL",
            (snapshot[0],),
        ).fetchone()
        if row and row[0] is not None:
            return int(row[0])

        max_row = connection.execute(
            "SELECT MAX(event) FROM fixtures WHERE snapshot_id = ? AND event IS NOT NULL",
            (snapshot[0],),
        ).fetchone()
        return int(max_row[0]) if max_row and max_row[0] is not None else 1


def _safe_int(value: Any, default: int = 3) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def analyze_team_fixtures(
    database_path: Path = DATABASE_PATH,
    num_gameweeks: int = 5,
    start_gw: int | None = None,
) -> dict[str, Any]:
    """Analyze upcoming fixtures and FDR for all 20 Premier League teams."""
    store = SnapshotStore(database_path)
    store.initialize()

    if start_gw is None:
        start_gw = get_current_gameweek(store)

    target_gws = list(range(start_gw, start_gw + num_gameweeks))

    with store._connect() as connection:
        snapshot = connection.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        if snapshot is None:
            raise RuntimeError("No FPL data found. Run `fpl update` first.")
        snapshot_id = snapshot[0]

        teams_rows = connection.execute(
            "SELECT team_id, name, short_name FROM teams WHERE snapshot_id = ? ORDER BY team_id",
            (snapshot_id,),
        ).fetchall()
        teams_map = {row[0]: {"name": row[1], "short_name": row[2]} for row in teams_rows}

        placeholders = ",".join("?" for _ in target_gws)
        fixtures_rows = connection.execute(
            f"""
            SELECT fixture_id, event, team_h, team_a, team_h_difficulty, team_a_difficulty, kickoff_time, finished
            FROM fixtures
            WHERE snapshot_id = ? AND event IN ({placeholders})
            ORDER BY event, kickoff_time
            """,
            (snapshot_id, *target_gws),
        ).fetchall()

    team_schedules: dict[int, list[dict[str, Any]]] = {t_id: [] for t_id in teams_map}

    for f_id, event, team_h, team_a, h_diff, a_diff, kickoff, finished in fixtures_rows:
        h_diff = _safe_int(h_diff, 3)
        a_diff = _safe_int(a_diff, 3)

        # Home team perspective
        if team_h in team_schedules:
            opp_short = teams_map.get(team_a, {}).get("short_name", f"T{team_a}")
            team_schedules[team_h].append({
                "event": event,
                "opponent": opp_short,
                "is_home": True,
                "venue": "H",
                "difficulty": h_diff,
            })

        # Away team perspective
        if team_a in team_schedules:
            opp_short = teams_map.get(team_h, {}).get("short_name", f"T{team_h}")
            team_schedules[team_a].append({
                "event": event,
                "opponent": opp_short,
                "is_home": False,
                "venue": "A",
                "difficulty": a_diff,
            })

    results: list[dict[str, Any]] = []

    for team_id, team_info in teams_map.items():
        schedule = team_schedules.get(team_id, [])
        diff_sum = sum(fix["difficulty"] for fix in schedule)
        avg_diff = round(diff_sum / len(schedule), 2) if schedule else 9.0

        ticker_parts = [f"{fix['opponent']}({fix['venue']},{fix['difficulty']})" for fix in schedule]
        ticker_str = " ".join(ticker_parts)

        results.append({
            "team_id": team_id,
            "team_name": team_info["name"],
            "short_name": team_info["short_name"],
            "num_fixtures": len(schedule),
            "avg_difficulty": avg_diff,
            "total_difficulty": diff_sum,
            "ticker": ticker_str,
            "fixtures": schedule,
        })

    # Sort by avg_difficulty ascending (easiest fixtures first)
    results.sort(key=lambda x: (x["avg_difficulty"], x["short_name"]))

    report = {
        "start_gw": start_gw,
        "end_gw": start_gw + num_gameweeks - 1,
        "num_gameweeks": num_gameweeks,
        "team_rankings": results,
    }

    FIXTURES_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURES_REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return report


def analyze_squad_fixtures(
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    num_gameweeks: int = 5,
    start_gw: int | None = None,
) -> dict[str, Any]:
    """Analyze upcoming fixtures specifically for players in the manager's current squad."""
    state = load_current_squad(squad_path)
    all_team_analysis = analyze_team_fixtures(database_path, num_gameweeks, start_gw)
    team_dict = {t["short_name"]: t for t in all_team_analysis["team_rankings"]}

    store = SnapshotStore(database_path)
    store.initialize()

    with store._connect() as connection:
        snapshot = connection.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        snapshot_id = snapshot[0]

        placeholders = ",".join("?" for _ in state.player_ids)
        rows = connection.execute(
            f"""
            SELECT players.player_id, players.web_name, teams.short_name, players.position_id
            FROM players JOIN teams ON teams.snapshot_id = players.snapshot_id AND teams.team_id = players.team_id
            WHERE players.snapshot_id = ? AND players.player_id IN ({placeholders})
            """,
            (snapshot_id, *state.player_ids),
        ).fetchall()

    player_meta = {row[0]: {"name": row[1], "team": row[2], "position_id": row[3]} for row in rows}

    squad_player_fixtures: list[dict[str, Any]] = []

    for player_id in state.player_ids:
        meta = player_meta.get(player_id)
        if meta is None:
            continue
        team_info = team_dict.get(meta["team"], {})
        squad_player_fixtures.append({
            "player_id": player_id,
            "name": meta["name"],
            "team": meta["team"],
            "avg_difficulty": team_info.get("avg_difficulty", 0.0),
            "ticker": team_info.get("ticker", ""),
            "fixtures": team_info.get("fixtures", []),
        })

    return {
        "start_gw": all_team_analysis["start_gw"],
        "end_gw": all_team_analysis["end_gw"],
        "num_gameweeks": num_gameweeks,
        "squad_players": squad_player_fixtures,
    }
