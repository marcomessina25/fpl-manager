"""Decision logging and audit trail system for FPL Manager V0.4.

Maintains an immutable historical record of all pre-deadline manager decisions:
- Selected Starting XI, captain, vice-captain, and ordered bench.
- Transfers executed and transfer hits taken.
- Chips played (Wildcard, Free Hit, Bench Boost, Triple Captain).
- Model baseline recommendations at that exact moment (to track human vs model divergences).
- Post-matchday actual points scored to evaluate decision quality over time.
"""

from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from .expected_points import project_gameweek
from .fixtures import get_current_gameweek
from .models import Player, Position
from .rules import validate_squad, validate_starting_lineup
from .squad_state import CurrentSquadState, load_current_squad
from .storage import SnapshotStore, utc_timestamp

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"


def record_gameweek_decision(
    gameweek: int,
    squad_player_ids: list[int],
    starting_player_ids: list[int],
    bench_player_ids: list[int],
    captain_id: int,
    vice_captain_id: int,
    season: str = "2026/27",
    transfers: list[dict[str, Any]] | None = None,
    transfer_hits: int = 0,
    chip_played: str | None = None,
    notes: str = "",
    database_path: Path = DATABASE_PATH,
    capture_recommendations: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Record and lock in a gameweek decision in the persistent audit database."""
    if len(squad_player_ids) != 15:
        raise ValueError(f"Squad must have exactly 15 players; received {len(squad_player_ids)}.")
    if len(starting_player_ids) != 11:
        raise ValueError(f"Starting XI must have exactly 11 players; received {len(starting_player_ids)}.")
    if len(bench_player_ids) != 4:
        raise ValueError(f"Bench must have exactly 4 players; received {len(bench_player_ids)}.")
    if captain_id not in starting_player_ids:
        raise ValueError(f"Captain ID {captain_id} must be in the starting XI.")
    if vice_captain_id not in starting_player_ids:
        raise ValueError(f"Vice-Captain ID {vice_captain_id} must be in the starting XI.")
    if captain_id == vice_captain_id:
        raise ValueError("Captain and Vice-Captain cannot be the same player.")

    store = SnapshotStore(database_path)
    store.initialize()

    # Load latest player metadata from database to validate rules
    with closing(store._connect()) as connection:
        snapshot = connection.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        if snapshot is None:
            raise RuntimeError("No FPL data found in database. Run `fpl update` first.")
        snapshot_id = snapshot[0]

        placeholders = ",".join("?" for _ in squad_player_ids)
        rows = connection.execute(
            f"""
            SELECT player_id, web_name, position_id, team_id, price_tenths
            FROM players
            WHERE snapshot_id = ? AND player_id IN ({placeholders})
            """,
            (snapshot_id, *squad_player_ids),
        ).fetchall()

    players_by_id = {
        row[0]: Player(
            id=row[0],
            name=row[1],
            position=Position(row[2]),
            team_id=row[3],
            price_tenths=row[4],
        )
        for row in rows
    }

    # Verify rule validity
    squad_objs = [players_by_id[pid] for pid in squad_player_ids if pid in players_by_id]
    if len(squad_objs) != 15:
        raise ValueError(f"Not all squad player IDs could be resolved in snapshot #{snapshot_id}.")

    squad_val = validate_squad(squad_objs)
    if not squad_val.is_valid:
        raise ValueError(f"Squad legality check failed: {'; '.join(squad_val.errors)}")

    lineup_val = validate_starting_lineup(squad_objs, starting_player_ids)
    if not lineup_val.is_valid:
        raise ValueError(f"Starting XI legality check failed: {'; '.join(lineup_val.errors)}")

    # Compute expected points projection for this lineup
    projections = project_gameweek(gameweek=gameweek, player_ids=squad_player_ids, database_path=database_path)
    proj_map = {p.player_id: p for p in projections}

    starters_projs = [proj_map[pid] for pid in starting_player_ids if pid in proj_map]
    cap_proj = proj_map.get(captain_id)

    starters_xp = sum(p.expected_points for p in starters_projs)
    cap_bonus_xp = cap_proj.expected_points if cap_proj else 0.0
    lineup_xp = round(starters_xp + cap_bonus_xp, 2)

    starters_floor = sum(p.xp_floor for p in starters_projs) + (cap_proj.xp_floor if cap_proj else 0.0)
    starters_ceil = sum(p.xp_ceiling for p in starters_projs) + (cap_proj.xp_ceiling if cap_proj else 0.0)

    timestamp = utc_timestamp()
    transfers_data = transfers or []

    # Optional model snapshot recommendation capture
    rec_lineup_json = None
    rec_transfers_json = None
    rec_plan_json = None

    if capture_recommendations:
        try:
            from .lineup import select_starting_lineup
            lineup_res = select_starting_lineup(database_path=database_path, gameweek=gameweek)
            rec_lineup_json = json.dumps(lineup_res, ensure_ascii=False)
        except Exception:
            pass

        try:
            from .suggest_transfers import suggest_transfers
            tx_res = suggest_transfers(num_transfers=1, database_path=database_path, max_results=3)
            rec_transfers_json = json.dumps(tx_res, ensure_ascii=False)
        except Exception:
            pass

    with closing(store._connect()) as connection, connection:
        existing = connection.execute(
            "SELECT id FROM decisions WHERE season = ? AND gameweek = ?",
            (season, gameweek),
        ).fetchone()

        if existing and not overwrite:
            raise ValueError(
                f"Decision already logged for {season} GW{gameweek} (Decision ID #{existing[0]}). "
                "Use overwrite=True to update."
            )

        if existing and overwrite:
            decision_id = existing[0]
            connection.execute(
                """
                UPDATE decisions
                SET timestamp = ?, chip_played = ?, transfer_hits = ?, transfers_json = ?,
                    starting_ids_json = ?, bench_ids_json = ?, captain_id = ?, vice_captain_id = ?,
                    predicted_lineup_xp = ?, predicted_floor_xp = ?, predicted_ceiling_xp = ?, notes = ?
                WHERE id = ?
                """,
                (
                    timestamp,
                    chip_played,
                    transfer_hits,
                    json.dumps(transfers_data, ensure_ascii=False),
                    json.dumps(starting_player_ids),
                    json.dumps(bench_player_ids),
                    captain_id,
                    vice_captain_id,
                    lineup_xp,
                    round(starters_floor, 2),
                    round(starters_ceil, 2),
                    notes,
                    decision_id,
                ),
            )
        else:
            cursor = connection.execute(
                """
                INSERT INTO decisions (
                    season, gameweek, timestamp, chip_played, transfer_hits, transfers_json,
                    starting_ids_json, bench_ids_json, captain_id, vice_captain_id,
                    predicted_lineup_xp, predicted_floor_xp, predicted_ceiling_xp, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    season,
                    gameweek,
                    timestamp,
                    chip_played,
                    transfer_hits,
                    json.dumps(transfers_data, ensure_ascii=False),
                    json.dumps(starting_player_ids),
                    json.dumps(bench_player_ids),
                    captain_id,
                    vice_captain_id,
                    lineup_xp,
                    round(starters_floor, 2),
                    round(starters_ceil, 2),
                    notes,
                ),
            )
            decision_id = int(cursor.lastrowid)

        if capture_recommendations:
            connection.execute(
                """
                INSERT OR REPLACE INTO decision_recommendations (
                    decision_id, recommended_lineup_json, recommended_transfers_json, recommended_plan_json
                ) VALUES (?, ?, ?, ?)
                """,
                (decision_id, rec_lineup_json, rec_transfers_json, rec_plan_json),
            )

    return {
        "decision_id": decision_id,
        "season": season,
        "gameweek": gameweek,
        "timestamp": timestamp,
        "chip_played": chip_played,
        "transfer_hits": transfer_hits,
        "transfers": transfers_data,
        "starting_player_ids": starting_player_ids,
        "bench_player_ids": bench_player_ids,
        "captain_id": captain_id,
        "captain_name": players_by_id[captain_id].name,
        "vice_captain_id": vice_captain_id,
        "vice_captain_name": players_by_id[vice_captain_id].name,
        "predicted_lineup_xp": lineup_xp,
        "predicted_floor_xp": round(starters_floor, 2),
        "predicted_ceiling_xp": round(starters_ceil, 2),
        "notes": notes,
    }


def get_gameweek_decision(
    gameweek: int,
    season: str = "2026/27",
    database_path: Path = DATABASE_PATH,
) -> dict[str, Any] | None:
    """Retrieve logged decision for a specific gameweek."""
    store = SnapshotStore(database_path)
    store.initialize()

    with closing(store._connect()) as connection:
        row = connection.execute(
            """
            SELECT id, season, gameweek, timestamp, chip_played, transfer_hits, transfers_json,
                   starting_ids_json, bench_ids_json, captain_id, vice_captain_id,
                   predicted_lineup_xp, predicted_floor_xp, predicted_ceiling_xp, actual_points, notes
            FROM decisions
            WHERE season = ? AND gameweek = ?
            """,
            (season, gameweek),
        ).fetchone()

        if not row:
            return None

        # Fetch player names
        cap_id, vc_id = row[9], row[10]
        cap_row = connection.execute("SELECT web_name FROM players WHERE player_id = ? LIMIT 1", (cap_id,)).fetchone()
        vc_row = connection.execute("SELECT web_name FROM players WHERE player_id = ? LIMIT 1", (vc_id,)).fetchone()
        cap_name = cap_row[0] if cap_row else f"ID {cap_id}"
        vc_name = vc_row[0] if vc_row else f"ID {vc_id}"

    return {
        "decision_id": row[0],
        "season": row[1],
        "gameweek": row[2],
        "timestamp": row[3],
        "chip_played": row[4],
        "transfer_hits": row[5],
        "transfers": json.loads(row[6]),
        "starting_player_ids": json.loads(row[7]),
        "bench_player_ids": json.loads(row[8]),
        "captain_id": cap_id,
        "captain_name": cap_name,
        "vice_captain_id": vc_id,
        "vice_captain_name": vc_name,
        "predicted_lineup_xp": row[11],
        "predicted_floor_xp": row[12],
        "predicted_ceiling_xp": row[13],
        "actual_points": row[14],
        "notes": row[15],
    }


def list_decisions(
    season: str = "2026/27",
    database_path: Path = DATABASE_PATH,
) -> list[dict[str, Any]]:
    """List all logged decisions in chronological order."""
    store = SnapshotStore(database_path)
    store.initialize()

    with closing(store._connect()) as connection:
        query = (
            "SELECT id, season, gameweek, timestamp, chip_played, transfer_hits, transfers_json, "
            "starting_ids_json, bench_ids_json, captain_id, vice_captain_id, "
            "predicted_lineup_xp, predicted_floor_xp, predicted_ceiling_xp, actual_points, notes "
            "FROM decisions WHERE season = ? ORDER BY gameweek ASC"
        )
        rows = connection.execute(query, (season,)).fetchall()
        name_rows = connection.execute("SELECT player_id, web_name FROM players GROUP BY player_id").fetchall()
        player_names = dict(name_rows)

    decisions = []
    for r in rows:
        cap_id = r[9]
        vc_id = r[10]
        decisions.append({
            "decision_id": r[0],
            "season": r[1],
            "gameweek": r[2],
            "timestamp": r[3],
            "chip_played": r[4],
            "transfer_hits": r[5],
            "transfers": json.loads(r[6]),
            "starting_player_ids": json.loads(r[7]),
            "bench_player_ids": json.loads(r[8]),
            "captain_id": cap_id,
            "captain_name": player_names.get(cap_id, f"ID {cap_id}"),
            "vice_captain_id": vc_id,
            "vice_captain_name": player_names.get(vc_id, f"ID {vc_id}"),
            "predicted_lineup_xp": r[11],
            "predicted_floor_xp": r[12],
            "predicted_ceiling_xp": r[13],
            "actual_points": r[14],
            "notes": r[15],
        })
    return decisions


def record_actual_gameweek_score(
    gameweek: int,
    actual_points: int,
    season: str = "2026/27",
    database_path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    """Record finalized actual points scored in a completed gameweek."""
    store = SnapshotStore(database_path)
    store.initialize()

    with closing(store._connect()) as connection, connection:
        row = connection.execute(
            "SELECT id FROM decisions WHERE season = ? AND gameweek = ?",
            (season, gameweek),
        ).fetchone()
        if not row:
            raise ValueError(f"No decision found for {season} GW{gameweek}. Log the decision first.")

        decision_id = row[0]
        connection.execute(
            "UPDATE decisions SET actual_points = ? WHERE id = ?",
            (actual_points, decision_id),
        )

    res = get_gameweek_decision(gameweek, season=season, database_path=database_path)
    if res is None:
        raise RuntimeError("Failed to retrieve updated decision.")
    return res


def log_decision_from_current_squad(
    gameweek: int | None = None,
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    chip_played: str | None = None,
    transfer_hits: int = 0,
    transfers: list[dict[str, Any]] | None = None,
    notes: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Automatically log decision using current squad state and optimized lineup."""
    state = load_current_squad(squad_path)
    store = SnapshotStore(database_path)
    if gameweek is None:
        gameweek = get_current_gameweek(store)

    from .lineup import select_starting_lineup
    lineup_res = select_starting_lineup(squad_path=squad_path, database_path=database_path, gameweek=gameweek)

    starters_ids = [p["id"] for p in lineup_res["starters"]]
    bench_ids = [p["id"] for p in lineup_res["bench"]]
    cap_id = lineup_res["captain"]["id"]
    vc_id = lineup_res["vice_captain"]["id"]

    return record_gameweek_decision(
        gameweek=gameweek,
        season=state.season,
        squad_player_ids=state.player_ids,
        starting_player_ids=starters_ids,
        bench_player_ids=bench_ids,
        captain_id=cap_id,
        vice_captain_id=vc_id,
        transfers=transfers or [],
        transfer_hits=transfer_hits,
        chip_played=chip_played,
        notes=notes,
        database_path=database_path,
        overwrite=overwrite,
    )
