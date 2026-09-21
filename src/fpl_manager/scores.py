"""Automated matchday scores ingestion and retrieval for FPL Manager V0.4.

Retrieves official gameweek player points and statistics from official FPL live endpoints,
caches them into local SQLite database, and supplies them to the evaluation engine.
"""

from contextlib import closing
from pathlib import Path
from typing import Any

from .api import fetch_gameweek_live_data
from .rules import is_free_transfers_chip
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


def get_detailed_player_gameweek_stats(
    gameweek: int,
    database_path: Path = DATABASE_PATH,
    force_fetch: bool = False,
) -> dict[int, dict[str, Any]]:
    """Retrieve detailed player statistics for a gameweek (minutes, goals, assists, bps, bonus, points)."""
    store = SnapshotStore(database_path)
    store.initialize()

    if force_fetch:
        try:
            update_gameweek_scores(gameweek, database_path=database_path)
        except Exception:
            pass

    with closing(store._connect()) as conn:
        rows = conn.execute(
            """
            SELECT player_id, total_points, minutes, goals_scored, assists, clean_sheets, goals_conceded, bonus, bps
            FROM player_gameweek_scores
            WHERE event_id = ?
            """,
            (gameweek,),
        ).fetchall()

        if not rows and not force_fetch:
            try:
                update_gameweek_scores(gameweek, database_path=database_path)
                rows = conn.execute(
                    """
                    SELECT player_id, total_points, minutes, goals_scored, assists, clean_sheets, goals_conceded, bonus, bps
                    FROM player_gameweek_scores
                    WHERE event_id = ?
                    """,
                    (gameweek,),
                ).fetchall()
            except Exception:
                pass

        res = {}
        for r in rows:
            res[r[0]] = {
                "total_points": int(r[1]),
                "minutes": int(r[2]),
                "goals_scored": int(r[3]),
                "assists": int(r[4]),
                "clean_sheets": int(r[5]),
                "goals_conceded": int(r[6]),
                "bonus": int(r[7]),
                "bps": int(r[8]),
            }
        return res


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
    finalized_count = finalize_completed_gameweek_scores(gameweek, database_path=database_path)

    return {
        "gameweek": gameweek,
        "players_updated": saved_count,
        "finalized_decisions": finalized_count,
        "fetched_at": fetched_at,
    }


def is_gameweek_completed(
    gameweek: int,
    database_path: Path = DATABASE_PATH,
) -> bool:
    """Check if all scheduled fixtures for a gameweek are completed.

    A gameweek is only considered completed when:
    1. At least one fixture is scheduled for this gameweek (COUNT(*) > 0).
    2. Every scheduled fixture has finished == 1.
    If any fixture is pending (finished == 0), ongoing, postponed without being played,
    or if the gameweek has no fixtures, the gameweek is NOT completed.
    In double gameweeks, all fixtures assigned to that gameweek must be finished.
    """
    store = SnapshotStore(database_path)
    store.initialize()

    with closing(store._connect()) as conn:
        snap = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        if not snap:
            return False
        snap_id = snap[0]

        row = conn.execute(
            """
            SELECT COUNT(*), SUM(CASE WHEN finished = 1 THEN 1 ELSE 0 END)
            FROM fixtures
            WHERE snapshot_id = ? AND event = ?
            """,
            (snap_id, gameweek),
        ).fetchone()

        if not row or row[0] == 0:
            return False
        total_fixtures, finished_fixtures = row[0], row[1] or 0
        return total_fixtures == finished_fixtures


def finalize_completed_gameweek_scores(
    gameweek: int | None = None,
    database_path: Path = DATABASE_PATH,
) -> int:
    """Auto-finalize actual scores for completed gameweeks across all decisions in SQLite."""
    import json
    store = SnapshotStore(database_path)
    store.initialize()

    with closing(store._connect()) as conn:
        snap = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        snap_id = snap[0] if snap else 1

        if gameweek is not None:
            completed_gws = [gameweek] if is_gameweek_completed(gameweek, database_path=database_path) else []
        else:
            rows = conn.execute(
                """
                SELECT event, COUNT(*), SUM(CASE WHEN finished = 1 THEN 1 ELSE 0 END)
                FROM fixtures
                WHERE snapshot_id = ? AND event IS NOT NULL
                GROUP BY event
                HAVING COUNT(*) = SUM(CASE WHEN finished = 1 THEN 1 ELSE 0 END) AND COUNT(*) > 0
                ORDER BY event
                """,
                (snap_id,),
            ).fetchall()
            completed_gws = [r[0] for r in rows]

        if not completed_gws:
            return 0

        placeholders = ",".join("?" for _ in completed_gws)
        dec_rows = conn.execute(
            f"""
            SELECT id, team_id, season, gameweek, actual_points, starting_ids_json, bench_ids_json,
                   captain_id, vice_captain_id, chip_played, transfer_hits, transfers_json
            FROM decisions
            WHERE gameweek IN ({placeholders})
            """,
            (*completed_gws,),
        ).fetchall()

    if not dec_rows:
        return 0

    from .live_matchday import compute_matchday_lineup_performance
    from .decision_log import get_gameweek_decision, record_actual_gameweek_score, reconcile_squad_transfers

    updated_count = 0
    for row in dec_rows:
        dec_id, tid, season, gw, act_pts, start_json, bench_json, cap_id, vc_id, chip, hits, tx_json = row
        starters = json.loads(start_json) if start_json else []
        bench = json.loads(bench_json) if bench_json else []
        effective_hits = hits or 0
        if is_free_transfers_chip(chip):
            effective_hits = 0
            if hits and hits > 0:
                with closing(store._connect()) as repair_conn, repair_conn:
                    repair_conn.execute("UPDATE decisions SET transfer_hits = 0 WHERE id = ?", (dec_id,))

        if gw > 1:
            try:
                curr_tx = json.loads(tx_json) if tx_json else []
            except Exception:
                curr_tx = []
            if not curr_tx:
                prev_dec = get_gameweek_decision(gw - 1, season=season, team_id=tid, database_path=database_path)
                if prev_dec:
                    prev_squad = list(prev_dec.get("squad_player_ids") or (prev_dec.get("starting_player_ids", []) + prev_dec.get("bench_player_ids", [])))
                    curr_squad = starters + bench
                    if set(prev_squad) != set(curr_squad):
                        reconciled = reconcile_squad_transfers(prev_squad, curr_squad, store)
                        if reconciled:
                            with closing(store._connect()) as repair_conn, repair_conn:
                                repair_conn.execute("UPDATE decisions SET transfers_json = ? WHERE id = ?", (json.dumps(reconciled), dec_id))

        try:
            perf = compute_matchday_lineup_performance(
                gameweek=gw,
                starting_ids=starters,
                bench_ids=bench,
                captain_id=cap_id,
                vice_captain_id=vc_id,
                chip_played=chip,
                transfer_hits=effective_hits,
                database_path=database_path,
            )
            if perf.get("has_match_data"):
                correct_pts = perf["net_points"]
                if act_pts != correct_pts:
                    record_actual_gameweek_score(
                        gameweek=gw,
                        actual_points=correct_pts,
                        team_id=tid,
                        season=season,
                        database_path=database_path,
                    )
                    updated_count += 1
        except Exception:
            continue

    return updated_count
