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


def resolve_player_id(store: SnapshotStore, val: int | str) -> int:
    """Resolve a player ID or name query to an integer player ID."""
    if isinstance(val, int):
        return val
    val_str = str(val).strip()
    if val_str.isdigit():
        return int(val_str)
    from .import_squad import search_player_exact_or_single
    match = search_player_exact_or_single(store, val_str)
    if match is None:
        raise ValueError(f"Could not resolve '{val_str}' to a unique player. Use exact name or ID.")
    return match["id"]


def resolve_player_ids_list(store: SnapshotStore, items: list[int | str] | str | None) -> list[int]:
    """Parse comma-separated or list of player names/IDs into a list of integer IDs."""
    if not items:
        return []
    if isinstance(items, str):
        parts = [p.strip() for p in items.replace(";", ",").split(",") if p.strip()]
    else:
        parts = items
    return [resolve_player_id(store, p) for p in parts]


def parse_and_apply_transfers(
    store: SnapshotStore,
    current_player_ids: list[int],
    transfers_input: list[str] | list[dict[str, Any]] | None,
    allow_past_outgoing: bool = False,
) -> tuple[list[int], list[dict[str, Any]]]:
    """Parse transfer inputs (e.g. 'OUT:IN' or dicts), apply them to player IDs, and return new IDs and records."""
    if not transfers_input:
        return list(current_player_ids), []

    squad_ids = list(current_player_ids)
    transfer_records = []

    with closing(store._connect()) as connection:
        name_rows = connection.execute("SELECT player_id, web_name FROM players GROUP BY player_id").fetchall()
        p_names = dict(name_rows)

    for tx in transfers_input:
        if isinstance(tx, dict):
            out_id = resolve_player_id(store, tx.get("outgoing_id", tx.get("outgoing")))
            in_id = resolve_player_id(store, tx.get("incoming_id", tx.get("incoming")))
        elif isinstance(tx, str):
            if ":" not in tx:
                raise ValueError(f"Invalid transfer format '{tx}'. Use 'OUTGOING:INCOMING'.")
            out_str, in_str = tx.split(":", maxsplit=1)
            out_id = resolve_player_id(store, out_str.strip())
            in_id = resolve_player_id(store, in_str.strip())
        else:
            continue

        if out_id in squad_ids:
            squad_ids.remove(out_id)
            if in_id not in squad_ids:
                squad_ids.append(in_id)
        elif allow_past_outgoing:
            # When logging a past gameweek:
            # If in_id is already in squad_ids (e.g. from current squad or post-transfer lineup),
            # squad_ids already reflects the post-transfer squad.
            if in_id not in squad_ids and len(squad_ids) < 15:
                squad_ids.append(in_id)
        else:
            out_name = p_names.get(out_id, f"ID {out_id}")
            raise ValueError(f"Outgoing player {out_name} (ID {out_id}) is not in your current squad.")

        transfer_records.append({
            "outgoing_id": out_id,
            "outgoing_name": p_names.get(out_id, f"ID {out_id}"),
            "incoming_id": in_id,
            "incoming_name": p_names.get(in_id, f"ID {in_id}"),
        })

    return squad_ids, transfer_records


def log_decision_from_current_squad(
    gameweek: int | None = None,
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    squad_player_ids: list[int | str] | str | None = None,
    starting_player_ids: list[int | str] | str | None = None,
    bench_player_ids: list[int | str] | str | None = None,
    captain_id: int | str | None = None,
    vice_captain_id: int | str | None = None,
    chip_played: str | None = None,
    transfer_hits: int | None = None,
    transfers: list[str] | list[dict[str, Any]] | None = None,
    notes: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Log decision using current squad, custom trades, and custom or optimized lineup.

    If gameweek is in the past (gameweek < current_squad.gameweek), permits entering players
    who were on the team at that time without requiring them to be in the current squad, and
    records the decision for evaluation without mutating current_squad.json.
    If gameweek is current, applies trades directly and updates current_squad.json.
    """
    state = load_current_squad(squad_path)
    store = SnapshotStore(database_path)
    store.initialize()

    squad_gw = getattr(state, "gameweek", 1)
    if gameweek is None:
        gameweek = squad_gw

    is_past = (gameweek < squad_gw)

    # 1. Determine base squad for this gameweek
    if squad_player_ids is not None:
        base_squad = resolve_player_ids_list(store, squad_player_ids)
        if len(base_squad) != 15:
            raise ValueError(f"Explicit squad must have exactly 15 players; received {len(base_squad)}.")
    elif is_past:
        prev_dec = get_gameweek_decision(gameweek - 1, database_path=database_path)
        if prev_dec:
            base_squad = list(prev_dec.get("squad_player_ids") or (prev_dec["starting_player_ids"] + prev_dec["bench_player_ids"]))
        else:
            base_squad = list(state.player_ids)
    else:
        base_squad = list(state.player_ids)

    # 2. Parse and apply any trades (transfers)
    squad_ids, parsed_transfers = parse_and_apply_transfers(
        store, base_squad, transfers, allow_past_outgoing=is_past
    )

    # 3. Compute transfer hits if not explicitly provided
    if transfer_hits is None:
        if parsed_transfers:
            from .transfers import Transfer, validate_transfers
            transfer_objs = [Transfer(t["outgoing_id"], t["incoming_id"]) for t in parsed_transfers]
            val_res = validate_transfers(state, store.latest_players(), transfer_objs)
            computed_hits = val_res.transfer_hits
        else:
            computed_hits = 0
    else:
        computed_hits = transfer_hits

    # 4. Integrate any starters entered for a past gameweek into squad_ids if needed
    if starting_player_ids is not None:
        starters_ids = resolve_player_ids_list(store, starting_player_ids)
        if len(starters_ids) != 11:
            raise ValueError(f"Starting XI must have exactly 11 players; received {len(starters_ids)}.")

        missing_starters = [pid for pid in starters_ids if pid not in squad_ids]
        if missing_starters:
            if is_past:
                with closing(store._connect()) as conn:
                    snap = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
                    snap_id = snap[0] if snap else 1
                    for m_id in missing_starters:
                        m_row = conn.execute("SELECT position_id FROM players WHERE snapshot_id = ? AND player_id = ?", (snap_id, m_id)).fetchone()
                        pos_id = m_row[0] if m_row else None
                        cands = [p for p in squad_ids if p not in starters_ids]
                        replaced = False
                        for c_id in cands:
                            c_row = conn.execute("SELECT position_id FROM players WHERE snapshot_id = ? AND player_id = ?", (snap_id, c_id)).fetchone()
                            if c_row and c_row[0] == pos_id:
                                squad_ids.remove(c_id)
                                squad_ids.append(m_id)
                                replaced = True
                                break
                        if not replaced and cands:
                            squad_ids.remove(cands[0])
                            squad_ids.append(m_id)
            else:
                with closing(store._connect()) as conn:
                    row = conn.execute("SELECT web_name FROM players WHERE player_id = ? LIMIT 1", (missing_starters[0],)).fetchone()
                name = row[0] if row else f"ID {missing_starters[0]}"
                raise ValueError(f"Selected starter {name} (ID {missing_starters[0]}) is not in the squad.")

        if bench_player_ids is not None:
            bench_ids = resolve_player_ids_list(store, bench_player_ids)
            if len(bench_ids) != 4:
                raise ValueError(f"Bench must have exactly 4 players; received {len(bench_ids)}.")
            if is_past:
                squad_ids = starters_ids + [pid for pid in bench_ids if pid not in starters_ids]
            else:
                missing_bench = [pid for pid in bench_ids if pid not in squad_ids]
                if missing_bench:
                    with closing(store._connect()) as conn:
                        row = conn.execute("SELECT web_name FROM players WHERE player_id = ? LIMIT 1", (missing_bench[0],)).fetchone()
                    name = row[0] if row else f"ID {missing_bench[0]}"
                    raise ValueError(f"Selected bench player {name} (ID {missing_bench[0]}) is not in the squad.")

        projections = project_gameweek(gameweek=gameweek, player_ids=squad_ids, database_path=database_path)
        proj_map = {p.player_id: p for p in projections}

        if bench_player_ids is None:
            remaining = [pid for pid in squad_ids if pid not in starters_ids]
            gkps = [pid for pid in remaining if proj_map.get(pid) and proj_map[pid].position == Position.GOALKEEPER]
            outfield = [pid for pid in remaining if pid not in gkps]
            outfield.sort(key=lambda pid: proj_map[pid].expected_points if pid in proj_map else 0.0, reverse=True)
            bench_ids = gkps + outfield
    else:
        projections = project_gameweek(gameweek=gameweek, player_ids=squad_ids, database_path=database_path)
        proj_map = {p.player_id: p for p in projections}

        from .lineup import LEGAL_FORMATIONS
        gkps = [p for p in projections if p.position == Position.GOALKEEPER]
        defs = [p for p in projections if p.position == Position.DEFENDER]
        mids = [p for p in projections if p.position == Position.MIDFIELDER]
        fwds = [p for p in projections if p.position == Position.FORWARD]

        gkps.sort(key=lambda p: (p.expected_points, p.base_xp_per_match), reverse=True)
        defs.sort(key=lambda p: (p.expected_points, p.base_xp_per_match), reverse=True)
        mids.sort(key=lambda p: (p.expected_points, p.base_xp_per_match), reverse=True)
        fwds.sort(key=lambda p: (p.expected_points, p.base_xp_per_match), reverse=True)

        best_score = -1e9
        best_starters = []
        best_bench = []

        for req_def, req_mid, req_fwd in LEGAL_FORMATIONS:
            starters = [gkps[0]] + defs[:req_def] + mids[:req_mid] + fwds[:req_fwd]
            bench = [gkps[1]]
            bench_outfield = defs[req_def:] + mids[req_mid:] + fwds[req_fwd:]
            bench_outfield.sort(key=lambda p: (p.expected_points, p.base_xp_per_match), reverse=True)
            bench.extend(bench_outfield)

            s_score = sum(p.expected_points for p in starters)
            if s_score > best_score:
                best_score = s_score
                best_starters = starters
                best_bench = bench

        starters_ids = [p.player_id for p in best_starters]
        bench_ids = [p.player_id for p in best_bench]

    starters_projs = [proj_map[pid] for pid in starters_ids if pid in proj_map]
    starters_ranked = sorted(starters_projs, key=lambda p: (p.expected_points, p.base_xp_per_match), reverse=True)

    if captain_id is not None:
        cap_id = resolve_player_id(store, captain_id)
        if cap_id not in starters_ids:
            with closing(store._connect()) as conn:
                row = conn.execute("SELECT web_name FROM players WHERE player_id = ? LIMIT 1", (cap_id,)).fetchone()
            name = row[0] if row else f"ID {cap_id}"
            raise ValueError(f"Captain {name} (ID {cap_id}) must be in the starting XI.")
    else:
        cap_id = starters_ranked[0].player_id if starters_ranked else starters_ids[0]

    if vice_captain_id is not None:
        vc_id = resolve_player_id(store, vice_captain_id)
        if vc_id not in starters_ids:
            with closing(store._connect()) as conn:
                row = conn.execute("SELECT web_name FROM players WHERE player_id = ? LIMIT 1", (vc_id,)).fetchone()
            name = row[0] if row else f"ID {vc_id}"
            raise ValueError(f"Vice-Captain {name} (ID {vc_id}) must be in the starting XI.")
    else:
        eligible_vcs = [p for p in starters_ranked if p.player_id != cap_id]
        vc_id = eligible_vcs[0].player_id if eligible_vcs else ([pid for pid in starters_ids if pid != cap_id][0])

    decision = record_gameweek_decision(
        gameweek=gameweek,
        season=state.season,
        squad_player_ids=squad_ids,
        starting_player_ids=starters_ids,
        bench_player_ids=bench_ids,
        captain_id=cap_id,
        vice_captain_id=vc_id,
        transfers=parsed_transfers,
        transfer_hits=computed_hits,
        chip_played=chip_played,
        notes=notes,
        database_path=database_path,
        overwrite=overwrite,
    )

    decision["is_past_gameweek"] = is_past
    decision["current_squad_updated"] = not is_past

    # 5. If logging NOW (not in the past), impact and update current_squad.json!
    if not is_past:
        from .squad_state import save_current_squad
        new_player_ids = tuple(squad_ids)
        new_prices = dict(state.purchase_prices_tenths)
        new_bank = state.bank_tenths

        with closing(store._connect()) as conn:
            snap = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
            snap_id = snap[0] if snap else 1

            for tx in parsed_transfers:
                out_id = tx["outgoing_id"]
                in_id = tx["incoming_id"]

                out_row = conn.execute("SELECT price_tenths FROM players WHERE snapshot_id = ? AND player_id = ?", (snap_id, out_id)).fetchone()
                in_row = conn.execute("SELECT price_tenths FROM players WHERE snapshot_id = ? AND player_id = ?", (snap_id, in_id)).fetchone()

                out_current_cost = out_row[0] if out_row else new_prices.get(out_id, 50)
                in_current_cost = in_row[0] if in_row else 50
                out_purchase = new_prices.get(out_id, out_current_cost)

                gain = max(0, (out_current_cost - out_purchase) // 2)
                selling_price = out_purchase + gain

                new_prices.pop(out_id, None)
                new_prices[in_id] = in_current_cost
                new_bank += (selling_price - in_current_cost)

        new_chips = list(state.chips_remaining)
        if chip_played and chip_played in new_chips:
            new_chips.remove(chip_played)

        num_tx = len(parsed_transfers)
        if num_tx > 0:
            new_ft = max(1, min(5, state.free_transfers - num_tx + 1))
        else:
            new_ft = min(5, state.free_transfers + 1)

        new_gw = max(squad_gw, gameweek)

        updated_state = CurrentSquadState(
            player_ids=new_player_ids,
            purchase_prices_tenths=new_prices,
            bank_tenths=max(0, new_bank),
            free_transfers=new_ft,
            chips_remaining=tuple(new_chips),
            season=state.season,
            gameweek=new_gw,
        )
        save_current_squad(squad_path, updated_state)

    return decision

