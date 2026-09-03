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
                CREATE TABLE IF NOT EXISTS players (
                    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
                    player_id INTEGER NOT NULL,
                    web_name TEXT NOT NULL,
                    team_id INTEGER NOT NULL,
                    position_id INTEGER NOT NULL,
                    price_tenths INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    total_points INTEGER NOT NULL,
                    PRIMARY KEY (snapshot_id, player_id)
                );
                CREATE TABLE IF NOT EXISTS fixtures (
                    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
                    fixture_id INTEGER NOT NULL,
                    event INTEGER,
                    team_h INTEGER NOT NULL,
                    team_a INTEGER NOT NULL,
                    kickoff_time TEXT,
                    finished INTEGER NOT NULL,
                    PRIMARY KEY (snapshot_id, fixture_id)
                );
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
            connection.executemany(
                "INSERT INTO players VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        snapshot_id,
                        player["id"],
                        player["web_name"],
                        player["team"],
                        player["element_type"],
                        player["now_cost"],
                        player["status"],
                        player["total_points"],
                    )
                    for player in bootstrap["elements"]
                ],
            )
            connection.executemany(
                "INSERT INTO fixtures VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        snapshot_id,
                        fixture["id"],
                        fixture.get("event"),
                        fixture["team_h"],
                        fixture["team_a"],
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
        return {"snapshot_id": snapshot_id, "fetched_at": fetched_at, "players": players, "teams": teams, "fixtures": fixtures}

    def latest_players(self) -> list[Player]:
        """Return players from the newest persisted snapshot."""
        self.initialize()
        with closing(self._connect()) as connection, connection:
            snapshot = connection.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
            if snapshot is None:
                raise RuntimeError("No FPL data found. Run `fpl update` first.")
            rows = connection.execute(
                "SELECT player_id, web_name, position_id, team_id, price_tenths FROM players WHERE snapshot_id = ?",
                (snapshot[0],),
            ).fetchall()
        return [Player(player_id, name, Position(position_id), team_id, price) for player_id, name, position_id, team_id, price in rows]

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)


def write_raw_snapshot(raw_directory: Path, name: str, data: Any, fetched_at: str) -> Path:
    raw_directory.mkdir(parents=True, exist_ok=True)
    safe_timestamp = fetched_at.replace(":", "-").replace("+", "_")
    path = raw_directory / f"{safe_timestamp}_{name}.json"
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return path
