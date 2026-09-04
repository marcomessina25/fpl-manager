"""SQLite persistence for reproducible FPL API snapshots."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import Player, Position


def utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _safe_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


class SnapshotStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY,
                    fetched_at TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS teams (
                    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
                    team_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    short_name TEXT NOT NULL,
                    PRIMARY KEY (snapshot_id, team_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
                    event_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    deadline_time TEXT,
                    is_current INTEGER NOT NULL DEFAULT 0,
                    is_next INTEGER NOT NULL DEFAULT 0,
                    finished INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (snapshot_id, event_id)
                );
                CREATE TABLE IF NOT EXISTS players (
                    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
                    player_id INTEGER NOT NULL,
                    web_name TEXT NOT NULL,
                    team_id INTEGER NOT NULL,
                    position_id INTEGER NOT NULL,
                    price_tenths INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    total_points INTEGER NOT NULL,
                    minutes INTEGER NOT NULL DEFAULT 0,
                    starts INTEGER NOT NULL DEFAULT 0,
                    chance_of_playing_next_round INTEGER,
                    chance_of_playing_this_round INTEGER,
                    expected_goals REAL NOT NULL DEFAULT 0.0,
                    expected_assists REAL NOT NULL DEFAULT 0.0,
                    expected_goal_involvements REAL NOT NULL DEFAULT 0.0,
                    expected_goals_conceded REAL NOT NULL DEFAULT 0.0,
                    expected_goals_per_90 REAL NOT NULL DEFAULT 0.0,
                    expected_assists_per_90 REAL NOT NULL DEFAULT 0.0,
                    expected_goals_conceded_per_90 REAL NOT NULL DEFAULT 0.0,
                    clean_sheets_per_90 REAL NOT NULL DEFAULT 0.0,
                    bps INTEGER NOT NULL DEFAULT 0,
                    ict_index REAL NOT NULL DEFAULT 0.0,
                    form REAL NOT NULL DEFAULT 0.0,
                    points_per_game REAL NOT NULL DEFAULT 0.0,
                    selected_by_percent REAL NOT NULL DEFAULT 0.0,
                    news TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (snapshot_id, player_id)
                );
                CREATE TABLE IF NOT EXISTS fixtures (
                    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
                    fixture_id INTEGER NOT NULL,
                    event INTEGER,
                    team_h INTEGER NOT NULL,
                    team_a INTEGER NOT NULL,
                    team_h_difficulty INTEGER,
                    team_a_difficulty INTEGER,
                    kickoff_time TEXT,
                    finished INTEGER NOT NULL,
                    PRIMARY KEY (snapshot_id, fixture_id)
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    team_id TEXT NOT NULL DEFAULT 'default',
                    season TEXT NOT NULL,
                    gameweek INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    chip_played TEXT,
                    transfer_hits INTEGER NOT NULL DEFAULT 0,
                    transfers_json TEXT NOT NULL DEFAULT '[]',
                    starting_ids_json TEXT NOT NULL,
                    bench_ids_json TEXT NOT NULL,
                    captain_id INTEGER NOT NULL,
                    vice_captain_id INTEGER NOT NULL,
                    predicted_lineup_xp REAL,
                    predicted_floor_xp REAL,
                    predicted_ceiling_xp REAL,
                    actual_points INTEGER,
                    notes TEXT,
                    UNIQUE(team_id, season, gameweek)
                );
                CREATE TABLE IF NOT EXISTS decision_recommendations (
                    decision_id INTEGER PRIMARY KEY REFERENCES decisions(id),
                    recommended_lineup_json TEXT,
                    recommended_transfers_json TEXT,
                    recommended_plan_json TEXT
                );
                CREATE TABLE IF NOT EXISTS player_gameweek_scores (
                    event_id INTEGER NOT NULL,
                    player_id INTEGER NOT NULL,
                    total_points INTEGER NOT NULL,
                    minutes INTEGER NOT NULL DEFAULT 0,
                    goals_scored INTEGER NOT NULL DEFAULT 0,
                    assists INTEGER NOT NULL DEFAULT 0,
                    clean_sheets INTEGER NOT NULL DEFAULT 0,
                    goals_conceded INTEGER NOT NULL DEFAULT 0,
                    bonus INTEGER NOT NULL DEFAULT 0,
                    bps INTEGER NOT NULL DEFAULT 0,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY (event_id, player_id)
                );
                """
            )
            # Fixtures migration check
            cursor = connection.execute("PRAGMA table_info(fixtures)")
            columns = [row[1] for row in cursor.fetchall()]
            if "team_h_difficulty" not in columns:
                connection.execute("ALTER TABLE fixtures ADD COLUMN team_h_difficulty INTEGER DEFAULT 3")
            if "team_a_difficulty" not in columns:
                connection.execute("ALTER TABLE fixtures ADD COLUMN team_a_difficulty INTEGER DEFAULT 3")
            connection.execute("UPDATE fixtures SET team_h_difficulty = 3 WHERE typeof(team_h_difficulty) = 'text'")
            connection.execute("UPDATE fixtures SET team_a_difficulty = 3 WHERE typeof(team_a_difficulty) = 'text'")

            # Players migration check for existing databases
            cursor = connection.execute("PRAGMA table_info(players)")
            player_columns = {row[1] for row in cursor.fetchall()}
            player_migrations = [
                ("minutes", "INTEGER NOT NULL DEFAULT 0"),
                ("starts", "INTEGER NOT NULL DEFAULT 0"),
                ("chance_of_playing_next_round", "INTEGER"),
                ("chance_of_playing_this_round", "INTEGER"),
                ("expected_goals", "REAL NOT NULL DEFAULT 0.0"),
                ("expected_assists", "REAL NOT NULL DEFAULT 0.0"),
                ("expected_goal_involvements", "REAL NOT NULL DEFAULT 0.0"),
                ("expected_goals_conceded", "REAL NOT NULL DEFAULT 0.0"),
                ("expected_goals_per_90", "REAL NOT NULL DEFAULT 0.0"),
                ("expected_assists_per_90", "REAL NOT NULL DEFAULT 0.0"),
                ("expected_goals_conceded_per_90", "REAL NOT NULL DEFAULT 0.0"),
                ("clean_sheets_per_90", "REAL NOT NULL DEFAULT 0.0"),
                ("bps", "INTEGER NOT NULL DEFAULT 0"),
                ("ict_index", "REAL NOT NULL DEFAULT 0.0"),
                ("form", "REAL NOT NULL DEFAULT 0.0"),
                ("points_per_game", "REAL NOT NULL DEFAULT 0.0"),
                ("selected_by_percent", "REAL NOT NULL DEFAULT 0.0"),
                ("news", "TEXT NOT NULL DEFAULT ''"),
            ]
            for col_name, col_type in player_migrations:
                if col_name not in player_columns:
                    connection.execute(f"ALTER TABLE players ADD COLUMN {col_name} {col_type}")

            # Decisions migration check for team_id column
            cursor = connection.execute("PRAGMA table_info(decisions)")
            decisions_columns = {row[1] for row in cursor.fetchall()}
            if "team_id" not in decisions_columns:
                connection.executescript(
                    """
                    CREATE TABLE decisions_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        team_id TEXT NOT NULL DEFAULT 'default',
                        season TEXT NOT NULL,
                        gameweek INTEGER NOT NULL,
                        timestamp TEXT NOT NULL,
                        chip_played TEXT,
                        transfer_hits INTEGER NOT NULL DEFAULT 0,
                        transfers_json TEXT NOT NULL DEFAULT '[]',
                        starting_ids_json TEXT NOT NULL,
                        bench_ids_json TEXT NOT NULL,
                        captain_id INTEGER NOT NULL,
                        vice_captain_id INTEGER NOT NULL,
                        predicted_lineup_xp REAL,
                        predicted_floor_xp REAL,
                        predicted_ceiling_xp REAL,
                        actual_points INTEGER,
                        notes TEXT,
                        UNIQUE(team_id, season, gameweek)
                    );
                    INSERT INTO decisions_new (
                        id, team_id, season, gameweek, timestamp, chip_played,
                        transfer_hits, transfers_json, starting_ids_json, bench_ids_json,
                        captain_id, vice_captain_id, predicted_lineup_xp, predicted_floor_xp,
                        predicted_ceiling_xp, actual_points, notes
                    )
                    SELECT
                        id, 'default', season, gameweek, timestamp, chip_played,
                        transfer_hits, transfers_json, starting_ids_json, bench_ids_json,
                        captain_id, vice_captain_id, predicted_lineup_xp, predicted_floor_xp,
                        predicted_ceiling_xp, actual_points, notes
                    FROM decisions;
                    DROP TABLE decisions;
                    ALTER TABLE decisions_new RENAME TO decisions;
                    """
                )

    def save_snapshot(self, bootstrap: dict[str, Any], fixtures: list[dict[str, Any]], fetched_at: str) -> int:
        self.initialize()
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute("INSERT INTO snapshots (fetched_at) VALUES (?)", (fetched_at,))
            snapshot_id = int(cursor.lastrowid)
            connection.executemany(
                "INSERT INTO teams VALUES (?, ?, ?, ?)",
                [(snapshot_id, team["id"], team["name"], team["short_name"]) for team in bootstrap["teams"]],
            )
            if "events" in bootstrap and bootstrap["events"]:
                connection.executemany(
                    """
                    INSERT INTO events (snapshot_id, event_id, name, deadline_time, is_current, is_next, finished)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            snapshot_id,
                            event["id"],
                            event["name"],
                            event.get("deadline_time"),
                            int(bool(event.get("is_current"))),
                            int(bool(event.get("is_next"))),
                            int(bool(event.get("finished"))),
                        )
                        for event in bootstrap["events"]
                    ],
                )
            connection.executemany(
                """
                INSERT INTO players (
                    snapshot_id, player_id, web_name, team_id, position_id, price_tenths, status, total_points,
                    minutes, starts, chance_of_playing_next_round, chance_of_playing_this_round,
                    expected_goals, expected_assists, expected_goal_involvements, expected_goals_conceded,
                    expected_goals_per_90, expected_assists_per_90, expected_goals_conceded_per_90, clean_sheets_per_90,
                    bps, ict_index, form, points_per_game, selected_by_percent, news
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot_id,
                        player["id"],
                        player["web_name"],
                        player["team"],
                        player["element_type"],
                        player["now_cost"],
                        player.get("status", "a"),
                        _safe_int(player.get("total_points"), 0),
                        _safe_int(player.get("minutes"), 0),
                        _safe_int(player.get("starts"), 0),
                        _safe_optional_int(player.get("chance_of_playing_next_round")),
                        _safe_optional_int(player.get("chance_of_playing_this_round")),
                        _safe_float(player.get("expected_goals"), 0.0),
                        _safe_float(player.get("expected_assists"), 0.0),
                        _safe_float(player.get("expected_goal_involvements"), 0.0),
                        _safe_float(player.get("expected_goals_conceded"), 0.0),
                        _safe_float(player.get("expected_goals_per_90"), 0.0),
                        _safe_float(player.get("expected_assists_per_90"), 0.0),
                        _safe_float(player.get("expected_goals_conceded_per_90"), 0.0),
                        _safe_float(player.get("clean_sheets_per_90"), 0.0),
                        _safe_int(player.get("bps"), 0),
                        _safe_float(player.get("ict_index"), 0.0),
                        _safe_float(player.get("form"), 0.0),
                        _safe_float(player.get("points_per_game"), 0.0),
                        _safe_float(player.get("selected_by_percent"), 0.0),
                        str(player.get("news") or ""),
                    )
                    for player in bootstrap["elements"]
                ],
            )
            connection.executemany(
                """
                INSERT INTO fixtures (snapshot_id, fixture_id, event, team_h, team_a, team_h_difficulty, team_a_difficulty, kickoff_time, finished)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot_id,
                        fixture["id"],
                        fixture.get("event"),
                        fixture["team_h"],
                        fixture["team_a"],
                        fixture.get("team_h_difficulty", 3),
                        fixture.get("team_a_difficulty", 3),
                        fixture.get("kickoff_time"),
                        int(fixture["finished"]),
                    )
                    for fixture in fixtures
                ],
            )
        return snapshot_id

    def latest_summary(self) -> dict[str, Any] | None:
        self.initialize()
        with closing(self._connect()) as connection, connection:
            snapshot = connection.execute(
                "SELECT id, fetched_at FROM snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if snapshot is None:
                return None
            snapshot_id, fetched_at = snapshot
            players = connection.execute("SELECT COUNT(*) FROM players WHERE snapshot_id = ?", (snapshot_id,)).fetchone()[0]
            teams = connection.execute("SELECT COUNT(*) FROM teams WHERE snapshot_id = ?", (snapshot_id,)).fetchone()[0]
            fixtures = connection.execute("SELECT COUNT(*) FROM fixtures WHERE snapshot_id = ?", (snapshot_id,)).fetchone()[0]
            events_count = connection.execute("SELECT COUNT(*) FROM events WHERE snapshot_id = ?", (snapshot_id,)).fetchone()[0]
        summary: dict[str, Any] = {
            "snapshot_id": snapshot_id,
            "fetched_at": fetched_at,
            "players": players,
            "teams": teams,
            "fixtures": fixtures,
        }
        if events_count > 0:
            summary["events"] = events_count
        return summary

    def latest_players(self) -> list[Player]:
        """Return players from the newest persisted snapshot."""
        self.initialize()
        with closing(self._connect()) as connection, connection:
            snapshot = connection.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
            if snapshot is None:
                raise RuntimeError("No FPL data found. Run `fpl update` first.")
            rows = connection.execute(
                """
                SELECT player_id, web_name, position_id, team_id, price_tenths, status, total_points,
                       minutes, starts, chance_of_playing_next_round, chance_of_playing_this_round,
                       expected_goals, expected_assists, expected_goal_involvements, expected_goals_conceded,
                       expected_goals_per_90, expected_assists_per_90, expected_goals_conceded_per_90, clean_sheets_per_90,
                       bps, ict_index, form, points_per_game, selected_by_percent, news
                FROM players WHERE snapshot_id = ?
                """,
                (snapshot[0],),
            ).fetchall()
        return [
            Player(
                id=row[0],
                name=row[1],
                position=Position(row[2]),
                team_id=row[3],
                price_tenths=row[4],
                status=row[5],
                total_points=row[6],
                minutes=row[7],
                starts=row[8],
                chance_of_playing_next_round=row[9],
                chance_of_playing_this_round=row[10],
                expected_goals=row[11],
                expected_assists=row[12],
                expected_goal_involvements=row[13],
                expected_goals_conceded=row[14],
                expected_goals_per_90=row[15],
                expected_assists_per_90=row[16],
                expected_goals_conceded_per_90=row[17],
                clean_sheets_per_90=row[18],
                bps=row[19],
                ict_index=row[20],
                form=row[21],
                points_per_game=row[22],
                selected_by_percent=row[23],
                news=row[24],
            )
            for row in rows
        ]

    def latest_events(self) -> list[dict[str, Any]]:
        """Return gameweek events from the newest persisted snapshot."""
        self.initialize()
        with closing(self._connect()) as connection, connection:
            snapshot = connection.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
            if snapshot is None:
                raise RuntimeError("No FPL data found. Run `fpl update` first.")
            rows = connection.execute(
                """
                SELECT event_id, name, deadline_time, is_current, is_next, finished
                FROM events WHERE snapshot_id = ?
                ORDER BY event_id ASC
                """,
                (snapshot[0],),
            ).fetchall()
        return [
            {
                "id": row[0],
                "name": row[1],
                "deadline_time": row[2],
                "is_current": bool(row[3]),
                "is_next": bool(row[4]),
                "finished": bool(row[5]),
            }
            for row in rows
        ]


    def save_gameweek_scores(self, event_id: int, live_data: dict[str, Any], fetched_at: str) -> int:
        """Save live matchday player scores for a gameweek into persistent SQLite table."""
        self.initialize()
        elements = live_data.get("elements", [])
        records = []
        for el in elements:
            pid = el["id"]
            stats = el.get("stats", {})
            records.append((
                event_id,
                pid,
                _safe_int(stats.get("total_points"), 0),
                _safe_int(stats.get("minutes"), 0),
                _safe_int(stats.get("goals_scored"), 0),
                _safe_int(stats.get("assists"), 0),
                _safe_int(stats.get("clean_sheets"), 0),
                _safe_int(stats.get("goals_conceded"), 0),
                _safe_int(stats.get("bonus"), 0),
                _safe_int(stats.get("bps"), 0),
                fetched_at,
            ))

        with closing(self._connect()) as connection, connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO player_gameweek_scores (
                    event_id, player_id, total_points, minutes, goals_scored, assists,
                    clean_sheets, goals_conceded, bonus, bps, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
        return len(records)

    def get_gameweek_scores(self, event_id: int) -> dict[int, float]:
        """Retrieve cached gameweek player scores from SQLite as {player_id: total_points}."""
        self.initialize()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT player_id, total_points FROM player_gameweek_scores WHERE event_id = ?",
                (event_id,),
            ).fetchall()
        return {r[0]: float(r[1]) for r in rows}

    def search_latest_players(self, query: str) -> list[dict[str, Any]]:
        """Find players by name in the newest snapshot for manual configuration."""
        self.initialize()
        with closing(self._connect()) as connection, connection:
            snapshot = connection.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
            if snapshot is None:
                raise RuntimeError("No FPL data found. Run `fpl update` first.")
            rows = connection.execute(
                """
                SELECT players.player_id, players.web_name, teams.short_name, players.price_tenths, players.position_id
                FROM players JOIN teams
                  ON teams.snapshot_id = players.snapshot_id AND teams.team_id = players.team_id
                WHERE players.snapshot_id = ? AND LOWER(players.web_name) LIKE ?
                ORDER BY players.web_name
                """,
                (snapshot[0], f"%{query.lower()}%"),
            ).fetchall()
        pos_names = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
        return [
            {
                "id": player_id,
                "name": name,
                "team": team,
                "price_tenths": price,
                "price_fmt": f"£{price / 10:.1f}m",
                "position": pos_names.get(pos_id, "MID"),
            }
            for player_id, name, team, price, pos_id in rows
        ]

    def get_player_details(self, player_id: int, gameweek: int | None = None) -> dict[str, Any]:
        """Fetch complete statistics, metrics, projections, and upcoming fixtures for a player."""
        self.initialize()
        with closing(self._connect()) as connection:
            snapshot = connection.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
            if snapshot is None:
                raise RuntimeError("No FPL data found. Run `fpl update` first.")
            snapshot_id = snapshot[0]

            row = connection.execute(
                """
                SELECT players.player_id, players.web_name, teams.name, teams.short_name, players.position_id,
                       players.price_tenths, players.status, players.total_points, players.minutes, players.starts,
                       players.chance_of_playing_next_round, players.chance_of_playing_this_round,
                       players.expected_goals, players.expected_assists, players.expected_goal_involvements,
                       players.expected_goals_conceded, players.expected_goals_per_90, players.expected_assists_per_90,
                       players.expected_goals_conceded_per_90, players.clean_sheets_per_90, players.bps, players.ict_index,
                       players.form, players.points_per_game, players.selected_by_percent, players.news, players.team_id
                FROM players JOIN teams
                  ON teams.snapshot_id = players.snapshot_id AND teams.team_id = players.team_id
                WHERE players.snapshot_id = ? AND players.player_id = ?
                """,
                (snapshot_id, player_id),
            ).fetchone()

            if row is None:
                raise ValueError(f"Player ID {player_id} not found.")

            team_id = row[26]

            # Fixtures (next 5 unfinished fixtures)
            fix_rows = connection.execute(
                """
                SELECT f.event, f.team_h, f.team_a, f.team_h_difficulty, f.team_a_difficulty,
                       th.short_name, ta.short_name
                FROM fixtures f
                JOIN teams th ON th.snapshot_id = f.snapshot_id AND th.team_id = f.team_h
                JOIN teams ta ON ta.snapshot_id = f.snapshot_id AND ta.team_id = f.team_a
                WHERE f.snapshot_id = ? AND (f.team_h = ? OR f.team_a = ?) AND f.finished = 0
                ORDER BY f.event ASC LIMIT 5
                """,
                (snapshot_id, team_id, team_id),
            ).fetchall()

        fixtures = []
        for f in fix_rows:
            is_home = (f[1] == team_id)
            opp_name = f[6] if is_home else f[5]
            diff = f[3] if is_home else f[4]
            loc = "H" if is_home else "A"
            fixtures.append({
                "gameweek": f[0],
                "opponent": opp_name,
                "is_home": is_home,
                "difficulty": diff,
                "summary": f"{opp_name} ({loc})",
            })

        proj_xp = None
        xp_floor = None
        xp_ceiling = None
        start_prob = None
        exp_min = None
        if gameweek is not None:
            try:
                from .expected_points import project_gameweek
                projs = project_gameweek(gameweek=gameweek, player_ids=[player_id], database_path=self.database_path)
                if projs:
                    p_proj = projs[0]
                    proj_xp = round(p_proj.expected_points, 2)
                    xp_floor = round(p_proj.xp_floor, 2)
                    xp_ceiling = round(p_proj.xp_ceiling, 2)
                    start_prob = round(p_proj.start_probability * 100) if p_proj.start_probability <= 1.0 else round(p_proj.start_probability)
                    exp_min = round(p_proj.expected_minutes)
            except Exception:
                pass

        own_pct = float(row[24])
        eo_pct = own_pct
        strat_cat = "CORE"
        try:
            from .ownership import get_player_ownership_map
            own_map = get_player_ownership_map(self.database_path)
            if player_id in own_map:
                own_pct = round(own_map[player_id], 1)
                eo_pct = own_pct
                if eo_pct >= 40.0 or own_pct >= 35.0:
                    strat_cat = "SHIELD"
                elif eo_pct < 15.0 or own_pct < 10.0:
                    strat_cat = "SWORD"
        except Exception:
            pass

        pos_names = {1: "Goalkeeper", 2: "Defender", 3: "Midfielder", 4: "Forward"}
        pos_abbrs = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

        return {
            "id": row[0],
            "name": row[1],
            "team_name": row[2],
            "team_short": row[3],
            "position": pos_names.get(row[4], "Midfielder"),
            "pos_abbr": pos_abbrs.get(row[4], "MID"),
            "price_tenths": row[5],
            "price_fmt": f"£{row[5] / 10:.1f}m",
            "status": row[6],
            "total_points": row[7],
            "minutes": row[8],
            "starts": row[9],
            "chance_playing_next": row[10],
            "chance_playing_this": row[11],
            "expected_goals": round(row[12], 2),
            "expected_assists": round(row[13], 2),
            "expected_goal_involvements": round(row[14], 2),
            "expected_goals_conceded": round(row[15], 2),
            "expected_goals_per_90": round(row[16], 2),
            "expected_assists_per_90": round(row[17], 2),
            "expected_goals_conceded_per_90": round(row[18], 2),
            "clean_sheets_per_90": round(row[19], 2),
            "bps": row[20],
            "ict_index": round(row[21], 1),
            "form": round(row[22], 1),
            "points_per_game": round(row[23], 1),
            "selected_by_percent": own_pct,
            "effective_ownership_pct": eo_pct,
            "strategic_category": strat_cat,
            "news": row[25] or "",
            "gameweek": gameweek,
            "expected_points": proj_xp,
            "xp_floor": xp_floor,
            "xp_ceiling": xp_ceiling,
            "start_probability": start_prob,
            "expected_minutes": exp_min,
            "fixtures": fixtures,
        }

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)


def write_raw_snapshot(raw_directory: Path, name: str, data: Any, fetched_at: str) -> Path:
    raw_directory.mkdir(parents=True, exist_ok=True)
    safe_timestamp = fetched_at.replace(":", "-").replace("+", "_")
    path = raw_directory / f"{safe_timestamp}_{name}.json"
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return path
