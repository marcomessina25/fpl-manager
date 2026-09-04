"""Automated matchday scores ingestion and retrieval for FPL Manager V0.4.

Retrieves official gameweek player points and statistics from official FPL live endpoints,
caches them into local SQLite database, and supplies them to the evaluation engine.
"""

from contextlib import closing
from pathlib import Path
from typing import Any

from .api import fetch_gameweek_live_data
from .storage import SnapshotStore, utc_timestamp, write_raw_snapshot

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
RAW_DIRECTORY = DATA_DIRECTORY / "raw"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"


def get_or_fetch_gameweek_scores(
    gameweek: int,
    database_path: Path = DATABASE_PATH,
    force_fetch: bool = False,
) -> dict[int, float]:
    """Retrieve actual player scores for a gameweek from SQLite, auto-fetching if not yet cached."""
    store = SnapshotStore(database_path)
    store.initialize()

    if not force_fetch:
        cached_scores = store.get_gameweek_scores(gameweek)
        if cached_scores:
            return cached_scores

    # Attempt fetching from official live FPL API
    try:
        live_payload = fetch_gameweek_live_data(gameweek)
        fetched_at = utc_timestamp()
        write_raw_snapshot(RAW_DIRECTORY, f"event-{gameweek}-live", live_payload, fetched_at)
        store.save_gameweek_scores(gameweek, live_payload, fetched_at)
        return store.get_gameweek_scores(gameweek)
    except Exception:
        # Fallback 1: check if cached scores existed despite force_fetch
        cached_scores = store.get_gameweek_scores(gameweek)
        if cached_scores:
            return cached_scores

        # Fallback 2: check if latest players snapshot has event_points or points for this event
        with closing(store._connect()) as connection:
            snapshot = connection.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
            if snapshot:
                snapshot_id = snapshot[0]
                # Check if this snapshot represents the requested gameweek
                event_row = connection.execute(
                    "SELECT event_id FROM events WHERE snapshot_id = ? AND (is_current = 1 OR finished = 1) ORDER BY event_id DESC LIMIT 1",
                    (snapshot_id,),
                ).fetchone()
                if event_row and event_row[0] == gameweek:
                    # Use points_per_game or event points if available
                    cursor = connection.execute("PRAGMA table_info(players)")
                    cols = {r[1] for r in cursor.fetchall()}
                    if "event_points" in cols:
                        rows = connection.execute(
                            "SELECT player_id, event_points FROM players WHERE snapshot_id = ?",
                            (snapshot_id,),
                        ).fetchall()
                        return {r[0]: float(r[1]) for r in rows}

        return {}


def update_gameweek_scores(
    gameweek: int,
    database_path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    """Explicitly fetch and persist official matchday scores for a gameweek."""
    store = SnapshotStore(database_path)
    store.initialize()

    fetched_at = utc_timestamp()
    live_payload = fetch_gameweek_live_data(gameweek)
    write_raw_snapshot(RAW_DIRECTORY, f"event-{gameweek}-live", live_payload, fetched_at)
    saved_count = store.save_gameweek_scores(gameweek, live_payload, fetched_at)

    return {
        "gameweek": gameweek,
        "players_updated": saved_count,
        "fetched_at": fetched_at,
    }
