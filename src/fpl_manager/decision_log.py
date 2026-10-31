"""Decision logging and audit trail system for FPL Manager (V1.0.1).

Maintains an immutable historical record of all pre-deadline manager decisions:
- Selected Starting XI, captain, vice-captain, and ordered bench.
- Transfers executed and transfer hits taken (with automatic chip hit-waiver rules).
- Chips played (Wildcard, Free Hit, Bench Boost, Triple Captain).
- Model baseline recommendations at that exact moment (to track human vs model divergences).
- Post-matchday actual points scored to evaluate decision quality over time.
"""

from contextlib import closing
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
from typing import Any

from .expected_points import project_gameweek
from .fixtures import get_current_gameweek
from .models import Player, Position
from .rules import free_transfer_transition, is_free_transfers_chip, validate_squad, validate_starting_lineup
from .squad_state import CurrentSquadState, live_command, load_current_squad, prepare_live_lifecycle, save_current_squad
from .storage import SnapshotStore, utc_timestamp
from .transfers import Transfer, prepare_transfer_finance, resolve_chained_transfers, selling_price

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"


@dataclass(frozen=True, slots=True)
class DecisionContext:
    """Immutable pre-deadline ownership, finance and data identity for model capture."""
    team_id: str
    squad_player_ids: tuple[int, ...]
    purchase_prices_tenths: tuple[tuple[int, int], ...]
    bank_tenths: int
    free_transfers: int
    chips_remaining: tuple[str, ...]
    season: str
    gameweek: int
    snapshot_id: int
    chip_played: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "squad_player_ids", tuple(self.squad_player_ids))
        object.__setattr__(self, "purchase_prices_tenths", tuple(tuple(item) for item in self.purchase_prices_tenths))
        object.__setattr__(self, "chips_remaining", tuple(self.chips_remaining))
        from .squad_state import validate_current_squad
        validate_current_squad(self.state)

    @classmethod
    def from_state(cls, team_id, state, gameweek, snapshot_id, chip_played=None):
        return cls(
            team_id, tuple(state.player_ids), tuple(sorted(state.purchase_prices_tenths.items())),
            state.bank_tenths, state.free_transfers, tuple(state.chips_remaining),
            state.season, gameweek, snapshot_id, chip_played,
        )

    @property
    def state(self) -> CurrentSquadState:
        return CurrentSquadState(
            self.squad_player_ids, dict(self.purchase_prices_tenths), self.bank_tenths,
            self.free_transfers, self.chips_remaining, self.season, self.gameweek,
        )


def consume_chip(
    state: CurrentSquadState, chip: str | None, gameweek: int,
    already_played: str | None = None,
) -> tuple[str, ...]:
    if not chip or (already_played and normalize_chip(chip) == normalize_chip(already_played)):
        return state.chips_remaining
    normalized = normalize_chip(chip)
    if normalized == "wildcard":
        aliases = {"wildcard", f"wildcard_{1 if gameweek <= 19 else 2}"}
    else:
        aliases = {normalized}
    remaining = list(state.chips_remaining)
    match = next((item for item in remaining if normalize_chip(item) in aliases), None)
    if match is None:
        raise ValueError(f"Chip '{chip}' is not available in GW{gameweek}.")
    remaining.remove(match)
    return tuple(remaining)


def normalize_chip(chip: str) -> str:
    name = str(chip).strip().lower().replace("_", "").replace(" ", "")
    return {
        "wc": "wildcard", "wildcard1": "wildcard_1", "wildcard2": "wildcard_2",
        "fh": "free_hit", "freehit": "free_hit", "bb": "bench_boost",
        "benchboost": "bench_boost", "tc": "triple_captain", "3xc": "triple_captain",
        "triplecaptain": "triple_captain",
    }.get(name, name)


@live_command("record_gameweek_decision")
def record_gameweek_decision(
    gameweek: int,
    squad_player_ids: list[int],
    starting_player_ids: list[int],
    bench_player_ids: list[int],
    captain_id: int,
    vice_captain_id: int,
    team_id: str = "default",
    season: str = "2026/27",
    transfers: list[dict[str, Any]] | None = None,
    transfer_hits: int = 0,
    chip_played: str | None = None,
    notes: str = "",
    database_path: Path = DATABASE_PATH,
    capture_recommendations: bool = True,
    overwrite: bool = True,
    decision_context: DecisionContext | None = None,
) -> dict[str, Any]:
    """Record and lock in a gameweek decision in the persistent audit database."""
    if len(squad_player_ids) != 15:
        raise ValueError(f"Squad must have exactly 15 players; received {len(squad_player_ids)}.")
    if len(starting_player_ids) != 11:
        raise ValueError(f"Starting XI must have exactly 11 players; received {len(starting_player_ids)}.")
    if len(bench_player_ids) != 4:
        raise ValueError(f"Bench must have exactly 4 players; received {len(bench_player_ids)}.")
    if set(starting_player_ids).intersection(set(bench_player_ids)):
        raise ValueError("Starting XI and bench cannot contain overlapping players.")
    if set(starting_player_ids) | set(bench_player_ids) != set(squad_player_ids):
        raise ValueError("Starting XI and bench must comprise all 15 squad players.")
    if captain_id not in starting_player_ids:
        raise ValueError(f"Captain ID {captain_id} must be in the starting XI.")
    if vice_captain_id not in starting_player_ids:
        raise ValueError(f"Vice-Captain ID {vice_captain_id} must be in the starting XI.")
    if captain_id == vice_captain_id:
        raise ValueError("Captain and Vice-Captain cannot be the same player.")
    if type(gameweek) is not int or not 1 <= gameweek <= 38:
        raise ValueError("Gameweek must be an integer between 1 and 38.")
    if type(transfer_hits) is not int or transfer_hits < 0:
        raise ValueError("Transfer hits must be a non-negative integer.")

    if is_free_transfers_chip(chip_played):
        transfer_hits = 0

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
    if decision_context is not None:
        if (
            decision_context.team_id != team_id or decision_context.gameweek != gameweek
            or decision_context.state.season != season
            or set(decision_context.state.player_ids) != set(squad_player_ids)
            or decision_context.snapshot_id != snapshot_id
        ):
            raise ValueError("Decision context does not match the recorded team, squad, gameweek or snapshot.")

    # Verify rule validity (formation, 15 players, club limits; budget is None because price appreciation naturally increases squad value over time)
    squad_objs = [players_by_id[pid] for pid in squad_player_ids if pid in players_by_id]
    if len(squad_objs) != 15:
        raise ValueError(f"Not all squad player IDs could be resolved in snapshot #{snapshot_id}.")

    squad_val = validate_squad(squad_objs, budget_tenths=None)
    if not squad_val.is_valid:
        raise ValueError(f"Squad legality check failed: {'; '.join(squad_val.errors)}")

    lineup_val = validate_starting_lineup(squad_objs, starting_player_ids)
    if not lineup_val.is_valid:
        raise ValueError(f"Starting XI legality check failed: {'; '.join(lineup_val.errors)}")

    # Compute expected points projection for this lineup
    point_in_time_unavailable = gameweek < get_current_gameweek(store)
    projections = [] if point_in_time_unavailable else project_gameweek(
        gameweek=gameweek, player_ids=squad_player_ids, database_path=database_path
    )
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
        if decision_context is None or point_in_time_unavailable:
            missing = {
                "capture_status": "not_captured",
                "reason": "point_in_time_snapshot_unavailable" if point_in_time_unavailable else "explicit_decision_context_required",
            }
            rec_lineup_json = json.dumps(missing)
            rec_transfers_json = json.dumps(missing)
        else:
            from .lineup import select_starting_lineup
            lineup_res = select_starting_lineup(
                database_path=database_path, gameweek=gameweek,
                state=decision_context.state, report_path=None,
            )
            lineup_res["decision_context"] = {
                "team_id": team_id, "season": season, "gameweek": gameweek,
                "snapshot_id": decision_context.snapshot_id,
                "bank_tenths": decision_context.bank_tenths,
                "free_transfers": decision_context.free_transfers,
                "chip_played": decision_context.chip_played,
            }
            rec_lineup_json = json.dumps(lineup_res, ensure_ascii=False)
            from .suggest_transfers import suggest_transfers
            transfer_res = suggest_transfers(
                state=decision_context.state, gameweek=gameweek, team_id=team_id,
                database_path=database_path, report_path=None,
            )
            transfer_res["decision_context"] = dict(lineup_res["decision_context"])
            rec_transfers_json = json.dumps(transfer_res, ensure_ascii=False)

    with closing(store._connect()) as connection, connection:
        existing = connection.execute(
            "SELECT id FROM decisions WHERE team_id = ? AND season = ? AND gameweek = ?",
            (team_id, season, gameweek),
        ).fetchone()

        if existing and not overwrite:
            raise ValueError(
                f"Decision already logged for team '{team_id}' {season} GW{gameweek} (Decision ID #{existing[0]}). "
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
                    team_id, season, gameweek, timestamp, chip_played, transfer_hits, transfers_json,
                    starting_ids_json, bench_ids_json, captain_id, vice_captain_id,
                    predicted_lineup_xp, predicted_floor_xp, predicted_ceiling_xp, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    team_id,
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
        "team_id": team_id,
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
        "prediction_status": "not_captured_point_in_time_unavailable" if point_in_time_unavailable else "captured",
    }


def get_gameweek_decision(
    gameweek: int,
    season: str = "2026/27",
    team_id: str = "default",
    database_path: Path = DATABASE_PATH,
) -> dict[str, Any] | None:
    """Retrieve logged decision for a specific gameweek and team."""
    store = SnapshotStore(database_path)
    store.initialize()

    with closing(store._connect()) as connection:
        row = connection.execute(
            """
            SELECT id, season, gameweek, timestamp, chip_played, transfer_hits, transfers_json,
                   starting_ids_json, bench_ids_json, captain_id, vice_captain_id,
                   predicted_lineup_xp, predicted_floor_xp, predicted_ceiling_xp, actual_points, notes, team_id
            FROM decisions
            WHERE team_id = ? AND season = ? AND gameweek = ?
            """,
            (team_id, season, gameweek),
        ).fetchone()

        if not row:
            return None

        # Fetch player names
        cap_id, vc_id = row[9], row[10]
        cap_row = connection.execute("SELECT web_name FROM players WHERE player_id = ? LIMIT 1", (cap_id,)).fetchone()
        vc_row = connection.execute("SELECT web_name FROM players WHERE player_id = ? LIMIT 1", (vc_id,)).fetchone()
        cap_name = cap_row[0] if cap_row else f"ID {cap_id}"
        vc_name = vc_row[0] if vc_row else f"ID {vc_id}"

    starters = json.loads(row[7])
    bench = json.loads(row[8])

    return {
        "decision_id": row[0],
        "team_id": row[16] if len(row) > 16 else team_id,
        "season": row[1],
        "gameweek": row[2],
        "timestamp": row[3],
        "chip_played": row[4],
        "transfer_hits": row[5],
        "transfers": json.loads(row[6]),
        "starting_player_ids": starters,
        "bench_player_ids": bench,
        "squad_player_ids": starters + bench,
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
    team_id: str = "default",
    database_path: Path = DATABASE_PATH,
) -> list[dict[str, Any]]:
    """List all logged decisions for a specific team in chronological order."""
    store = SnapshotStore(database_path)
    store.initialize()

    with closing(store._connect()) as connection:
        query = (
            "SELECT id, season, gameweek, timestamp, chip_played, transfer_hits, transfers_json, "
            "starting_ids_json, bench_ids_json, captain_id, vice_captain_id, "
            "predicted_lineup_xp, predicted_floor_xp, predicted_ceiling_xp, actual_points, notes, team_id "
            "FROM decisions WHERE team_id = ? AND season = ? ORDER BY gameweek ASC"
        )
        rows = connection.execute(query, (team_id, season)).fetchall()
        name_rows = connection.execute("SELECT player_id, web_name FROM players GROUP BY player_id").fetchall()
        player_names = dict(name_rows)

    decisions = []
    for r in rows:
        cap_id = r[9]
        vc_id = r[10]
        decisions.append({
            "decision_id": r[0],
            "team_id": r[16] if len(r) > 16 else team_id,
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


@live_command("record_actual_gameweek_score")
def record_actual_gameweek_score(
    gameweek: int,
    actual_points: int,
    season: str = "2026/27",
    team_id: str = "default",
    database_path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    """Record finalized actual points scored in a completed gameweek for a specific team."""
    store = SnapshotStore(database_path)
    store.initialize()

    with closing(store._connect()) as connection, connection:
        row = connection.execute(
            "SELECT id FROM decisions WHERE team_id = ? AND season = ? AND gameweek = ?",
            (team_id, season, gameweek),
        ).fetchone()
        if not row:
            raise ValueError(f"No decision found for team '{team_id}' {season} GW{gameweek}. Log the decision first.")

        decision_id = row[0]
        connection.execute(
            "UPDATE decisions SET actual_points = ? WHERE id = ?",
            (actual_points, decision_id),
        )

    res = get_gameweek_decision(gameweek, season=season, team_id=team_id, database_path=database_path)
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
    already_applied_pairs: set[tuple[int, int]] | None = None,
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
        elif (out_id, in_id) in (already_applied_pairs or set()) and in_id in squad_ids:
            pass
        elif allow_past_outgoing:
            # When logging a past gameweek:
            # If in_id is already in squad_ids (e.g. from current squad or post-transfer lineup),
            # squad_ids already reflects the post-transfer squad.
            if in_id not in squad_ids:
                if len(squad_ids) >= 15:
                    squad_ids.pop()
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

    return squad_ids, resolve_chained_transfers(transfer_records)


def reconcile_squad_transfers(
    prev_squad_ids: list[int] | set[int],
    curr_squad_ids: list[int] | set[int],
    store: SnapshotStore,
    purchase_prices_tenths: dict[int, int] | None = None,
) -> list[dict[str, Any]]:
    """Reconcile player transfers between two squad states by position matching."""
    prev_set = set(prev_squad_ids)
    curr_set = set(curr_squad_ids)
    out_pids = sorted(list(prev_set - curr_set))
    in_pids = sorted(list(curr_set - prev_set))

    if not out_pids or not in_pids or len(out_pids) != len(in_pids):
        return []

    with closing(store._connect()) as conn:
        snap = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        snap_id = snap[0] if snap else 1
        all_ids = out_pids + in_pids
        placeholders = ",".join("?" for _ in all_ids)
        all_p_rows = conn.execute(
            f"SELECT player_id, web_name, team_id, position_id, price_tenths FROM players WHERE snapshot_id = ? AND player_id IN ({placeholders})",
            (snap_id, *all_ids),
        ).fetchall()
        p_info = {r[0]: {"name": r[1], "team": r[2], "pos": r[3], "price": r[4]} for r in all_p_rows}

    # Sort matching by position first, then player_id
    unmatched_outs = sorted(list(out_pids), key=lambda pid: (p_info.get(pid, {}).get("pos", 0), pid))
    unmatched_ins = sorted(list(in_pids), key=lambda pid: (p_info.get(pid, {}).get("pos", 0), pid))
    reconciled = []
    for o_id in list(unmatched_outs):
        o_pos = p_info.get(o_id, {}).get("pos")
        match_in = next((i_id for i_id in unmatched_ins if p_info.get(i_id, {}).get("pos") == o_pos), None)
        if match_in is not None:
            unmatched_outs.remove(o_id)
            unmatched_ins.remove(match_in)
            reconciled.append((o_id, match_in))
    for o_id, i_id in zip(unmatched_outs, unmatched_ins):
        reconciled.append((o_id, i_id))

    purchases = purchase_prices_tenths or {}
    tx_records = []
    for o_id, i_id in reconciled:
        o_meta = p_info.get(o_id, {})
        i_meta = p_info.get(i_id, {})
        out_current_cost = o_meta.get("price", 50)
        in_current_cost = i_meta.get("price", 50)
        out_purchase = purchases.get(o_id, out_current_cost)
        sell_price = selling_price(out_purchase, out_current_cost)

        tx_records.append({
            "outgoing_id": o_id,
            "outgoing_name": o_meta.get("name", f"ID {o_id}"),
            "outgoing_team": o_meta.get("team", ""),
            "incoming_id": i_id,
            "incoming_name": i_meta.get("name", f"ID {i_id}"),
            "incoming_team": i_meta.get("team", ""),
            "selling_price_tenths": sell_price,
            "purchase_price_tenths": in_current_cost,
            "outgoing_purchase_price_tenths": out_purchase,
        })
    return tx_records


@live_command("log_decision_from_current_squad")
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
    team_id: str | None = None,
    overwrite: bool = True,
    season: str | None = None,
) -> dict[str, Any]:
    """Log decision using current squad, custom trades, and custom or optimized lineup.

    If gameweek is in the past (gameweek < current_squad.gameweek), permits entering players
    who were on the team at that time without requiring them to be in the current squad, and
    records the decision for evaluation without mutating current_squad.json.
    If gameweek is current, applies trades directly and updates current_squad.json.
    """
    state = load_current_squad(squad_path)
    if season is not None and season != state.season:
        raise ValueError("Decision season does not match the selected squad.")
    store = SnapshotStore(database_path)
    store.initialize()

    if team_id is None:
        try:
            from .teams import get_team_id_from_squad_path
            team_id = get_team_id_from_squad_path(squad_path)
        except Exception:
            team_id = "default"

    try:
        from .fixtures import get_current_gameweek
        active_fpl_gw = get_current_gameweek(store)
    except Exception:
        active_fpl_gw = 1

    squad_gw = getattr(state, "gameweek", None)
    if squad_gw is None:
        squad_gw = active_fpl_gw

    if gameweek is None:
        gameweek = squad_gw

    is_past = (gameweek < squad_gw) or (active_fpl_gw is not None and gameweek < active_fpl_gw)

    # 1. Determine base squad and previous gameweek squad
    prev_dec = None
    if gameweek > 1:
        prev_dec = get_gameweek_decision(gameweek - 1, season=state.season, team_id=team_id, database_path=database_path)

    if not is_past and prev_dec and prev_dec.get("chip_played") and normalize_chip(prev_dec["chip_played"]) == "free_hit":
        baseline = state.gameweek_start_state
        prev_squad_ids = list(baseline.player_ids if baseline else state.player_ids)
    elif prev_dec:
        prev_squad_ids = list(prev_dec.get("squad_player_ids") or (prev_dec.get("starting_player_ids", []) + prev_dec.get("bench_player_ids", [])))
    else:
        prev_squad_ids = list(state.player_ids)

    if squad_player_ids is not None:
        base_squad = resolve_player_ids_list(store, squad_player_ids)
        if len(base_squad) != 15:
            raise ValueError(f"Explicit squad must have exactly 15 players; received {len(base_squad)}.")
    elif is_past:
        base_squad = list(prev_squad_ids)
    else:
        base_squad = list(state.player_ids)

    existing_dec = get_gameweek_decision(gameweek, season=state.season, team_id=team_id, database_path=database_path)
    existing_records = {
        (tx["outgoing_id"], tx["incoming_id"]): tx for tx in existing_dec.get("transfers", [])
    } if existing_dec else {}
    # 2. Parse and apply any trades (transfers)
    squad_ids, parsed_transfers = parse_and_apply_transfers(
        store, base_squad, transfers, allow_past_outgoing=is_past,
        already_applied_pairs=set(existing_records),
    )
    parsed_transfers = [
        dict(existing_records.get((tx["outgoing_id"], tx["incoming_id"]), tx)) for tx in parsed_transfers
    ]

    if chip_played is None and existing_dec is not None and existing_dec.get("chip_played"):
        chip_played = existing_dec["chip_played"]

    if transfers is None and existing_dec and existing_dec.get("transfers"):
        parsed_transfers = list(existing_dec.get("transfers", []))

    # 4. Integrate any starters entered for a past gameweek into squad_ids if needed
    if starting_player_ids is not None:
        starters_ids = resolve_player_ids_list(store, starting_player_ids)
        if len(starters_ids) != 11:
            raise ValueError(f"Starting XI must have exactly 11 players; received {len(starters_ids)}.")

        missing_starters = [pid for pid in starters_ids if pid not in squad_ids]
        if missing_starters:
            if is_past or is_free_transfers_chip(chip_played):
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
            if is_past or is_free_transfers_chip(chip_played):
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
            if starting_player_ids is None and cap_id in squad_ids:
                cap_proj = proj_map.get(cap_id)
                if cap_proj:
                    same_pos = [pid for pid in starters_ids if proj_map.get(pid) and proj_map[pid].position == cap_proj.position]
                    if same_pos:
                        same_pos.sort(key=lambda pid: proj_map[pid].expected_points)
                        swap_out = same_pos[0]
                        starters_ids.remove(swap_out)
                        starters_ids.append(cap_id)
                        if cap_id in bench_ids:
                            bench_ids.remove(cap_id)
                        bench_ids.append(swap_out)
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
            if starting_player_ids is None and vc_id in squad_ids:
                vc_proj = proj_map.get(vc_id)
                if vc_proj:
                    same_pos = [pid for pid in starters_ids if proj_map.get(pid) and proj_map[pid].position == vc_proj.position and pid != cap_id]
                    if same_pos:
                        same_pos.sort(key=lambda pid: proj_map[pid].expected_points)
                        swap_out = same_pos[0]
                        starters_ids.remove(swap_out)
                        starters_ids.append(vc_id)
                        if vc_id in bench_ids:
                            bench_ids.remove(vc_id)
                        bench_ids.append(swap_out)
            if vc_id not in starters_ids:
                with closing(store._connect()) as conn:
                    row = conn.execute("SELECT web_name FROM players WHERE player_id = ? LIMIT 1", (vc_id,)).fetchone()
                name = row[0] if row else f"ID {vc_id}"
                raise ValueError(f"Vice-Captain {name} (ID {vc_id}) must be in the starting XI.")
    else:
        eligible_vcs = [p for p in starters_ranked if p.player_id != cap_id]
        vc_id = eligible_vcs[0].player_id if eligible_vcs else ([pid for pid in starters_ids if pid != cap_id][0])

    # 4. Reconcile transfers if not explicitly provided and squad differs from previous gameweek
    existing_squad_matches = False
    if existing_dec and existing_dec.get("transfers"):
        ex_squad = set(existing_dec.get("squad_player_ids") or (existing_dec.get("starting_player_ids", []) + existing_dec.get("bench_player_ids", [])))
        if ex_squad == set(squad_ids):
            existing_squad_matches = True

    if not existing_squad_matches and transfers is None and gameweek > 1:
        if set(prev_squad_ids) != set(squad_ids):
            parsed_transfers = reconcile_squad_transfers(
                prev_squad_ids,
                squad_ids,
                store,
                purchase_prices_tenths=state.purchase_prices_tenths,
            )

    if parsed_transfers:
        with closing(store._connect()) as conn:
            snap = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
            snap_id = snap[0] if snap else 1
            for tx in parsed_transfers:
                out_id = tx["outgoing_id"]
                in_id = tx["incoming_id"]
                out_row = conn.execute("SELECT price_tenths FROM players WHERE snapshot_id = ? AND player_id = ?", (snap_id, out_id)).fetchone()
                in_row = conn.execute("SELECT price_tenths FROM players WHERE snapshot_id = ? AND player_id = ?", (snap_id, in_id)).fetchone()
                out_current_cost = out_row[0] if out_row else state.purchase_prices_tenths.get(out_id, 50)
                in_current_cost = in_row[0] if in_row else 50
                out_purchase = state.purchase_prices_tenths.get(out_id, out_current_cost)
                sell_price = selling_price(out_purchase, out_current_cost)
                if "selling_price_tenths" not in tx:
                    tx["selling_price_tenths"] = sell_price
                if "purchase_price_tenths" not in tx:
                    tx["purchase_price_tenths"] = in_current_cost
                if "outgoing_purchase_price_tenths" not in tx:
                    tx["outgoing_purchase_price_tenths"] = out_purchase

    # 5. Compute transfer hits if not explicitly provided
    if is_free_transfers_chip(chip_played):
        computed_hits = 0
    elif transfer_hits is None:
        if parsed_transfers:
            starting_ft = compute_expected_free_transfers(
                gameweek,
                team_id=team_id,
                season=state.season,
                database_path=database_path,
            )
            computed_hits = max(0, len(parsed_transfers) - starting_ft)
        else:
            computed_hits = 0
    else:
        computed_hits = transfer_hits

    updated_state = None
    capture_context = None
    if not is_past:
        state = prepare_live_lifecycle(
            state, gameweek, chip_played, existing_dec.get("chip_played") if existing_dec else None,
        )
        players = store.latest_players()
        player_map = {player.id: player for player in players}
        outgoing = set(state.player_ids) - set(squad_ids)
        incoming = set(squad_ids) - set(state.player_ids)
        if len(outgoing) != len(incoming):
            raise ValueError("Decision squad does not preserve full ownership.")
        changed = reconcile_squad_transfers(
            state.player_ids, squad_ids, store, state.purchase_prices_tenths
        ) if outgoing else []
        if outgoing and not changed:
            raise ValueError("Cannot establish a complete transfer basis for decision squad.")
        settlement = state
        if changed:
            settlement, priced = prepare_transfer_finance(
                state, players, [Transfer(tx["outgoing_id"], tx["incoming_id"]) for tx in changed]
            )
            priced_by_pair = {(tx["outgoing_id"], tx["incoming_id"]): tx for tx in priced}
            for tx in parsed_transfers:
                match = priced_by_pair.get((tx["outgoing_id"], tx["incoming_id"]))
                if match is not None:
                    tx.update(match)
        if any(pid not in player_map for pid in squad_ids):
            raise ValueError("Decision squad includes unknown players.")
        new_chips = consume_chip(
            state, chip_played, gameweek, existing_dec.get("chip_played") if existing_dec else None
        )
        starting_ft = compute_expected_free_transfers(
            gameweek, team_id=team_id, season=state.season, database_path=database_path
        )
        updated_state = replace(
            settlement, player_ids=tuple(squad_ids), chips_remaining=new_chips,
            free_transfers=1 if is_free_transfers_chip(chip_played) else max(0, starting_ft - len(parsed_transfers)),
            gameweek=max(squad_gw, gameweek),
        )
        with closing(store._connect()) as conn:
            snapshot_id = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()[0]
        capture_context = DecisionContext.from_state(team_id, updated_state, gameweek, snapshot_id, chip_played)

    decision = record_gameweek_decision(
        gameweek=gameweek,
        season=state.season,
        team_id=team_id,
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
        decision_context=capture_context,
    )

    decision["is_past_gameweek"] = is_past
    decision["current_squad_updated"] = not is_past

    if updated_state is not None:
        save_current_squad(squad_path, updated_state)

    return decision


def compute_expected_free_transfers(
    target_gw: int,
    team_id: str = "default",
    season: str = "2026/27",
    database_path: Path = DATABASE_PATH,
) -> int:
    """Compute the expected free transfers entering target_gw based on past decisions."""
    if target_gw <= 2:
        return 1

    store = SnapshotStore(database_path)
    store.initialize()

    # Gameweek 2 begins with 1 free transfer in FPL
    ft = 1
    with closing(store._connect()) as conn:
        rows = conn.execute(
            """
            SELECT gameweek, transfers_json, chip_played
            FROM decisions
            WHERE team_id = ? AND season = ? AND gameweek >= 2 AND gameweek < ?
            ORDER BY gameweek ASC
            """,
            (team_id, season, target_gw),
        ).fetchall()

        gw_decisions = {r[0]: (json.loads(r[1]) if r[1] else [], r[2]) for r in rows}

        for gw in range(2, target_gw):
            if gw in gw_decisions:
                tx_list, chip = gw_decisions[gw]
                if is_free_transfers_chip(chip):
                    ft = 1
                else:
                    tx_count = len(resolve_chained_transfers(tx_list))
                    _, ft = free_transfer_transition(gw, ft, tx_count, max_free_transfers=5)
            else:
                ft = 1

    return max(1, min(5, ft))


@live_command("undo_gameweek_changes")
def undo_gameweek_changes(
    squad_path: Path,
    gameweek: int | None = None,
    team_id: str | None = None,
    season: str | None = None,
    database_path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    """Reset changes for the target gameweek and revert squad to the status of the previous gameweek."""
    cur_state = load_current_squad(squad_path)
    from .teams import get_team_id_from_squad_path
    team_id = team_id or get_team_id_from_squad_path(squad_path)
    season = season or cur_state.season
    if season != cur_state.season:
        raise ValueError("Undo season does not match the selected squad.")
    target_gw = gameweek or cur_state.gameweek or 1

    store = SnapshotStore(database_path)
    store.initialize()

    with closing(store._connect()) as conn:
        row = conn.execute(
            """
            SELECT gameweek, starting_ids_json, bench_ids_json, transfers_json, chip_played, transfer_hits
            FROM decisions
            WHERE team_id = ? AND season = ? AND gameweek < ?
            ORDER BY gameweek DESC LIMIT 1
            """,
            (team_id, season, target_gw),
        ).fetchone()

    if row:
        prev_gw, prev_starters_json, prev_bench_json, _, prev_chip, _ = row
        prev_squad_ids = tuple(json.loads(prev_starters_json) + json.loads(prev_bench_json))
    else:
        saved = cur_state.gameweek_start_state or cur_state.pre_free_hit_state
        if saved is None or saved.gameweek != target_gw:
            raise ValueError(f"No previous gameweek is available to revert to (prior to GW{target_gw}).")
        prev_gw, prev_chip = max(1, target_gw - 1), None
        prev_squad_ids = saved.player_ids

    if len(prev_squad_ids) != 15:
        raise ValueError(f"Previous gameweek (GW{prev_gw}) decision does not contain 15 players.")

    # Check for any logged decision for target_gw and delete it
    cur_tx = []
    cur_chip = None
    with closing(store._connect()) as conn, conn:
        cur_dec_row = conn.execute(
            """
            SELECT id, transfers_json, chip_played FROM decisions
            WHERE team_id = ? AND season = ? AND gameweek = ?
            """,
            (team_id, season, target_gw),
        ).fetchone()
        if cur_dec_row:
            cur_tx = json.loads(cur_dec_row[1]) if cur_dec_row[1] else []
            cur_chip = cur_dec_row[2]

    if target_gw != (cur_state.gameweek or 1):
        raise ValueError("Undo must target the current squad gameweek.")
    baseline = cur_state.gameweek_start_state
    if baseline is None and cur_state.pre_free_hit_state is not None:
        baseline = cur_state.pre_free_hit_state
    if baseline is not None:
        prev_squad_ids = baseline.player_ids
        reverted_prices = dict(baseline.purchase_prices_tenths)
        reverted_bank = baseline.bank_tenths
    else:
        if cur_chip and normalize_chip(cur_chip) == "free_hit":
            raise ValueError("Legacy Free Hit has no authoritative pre-chip ownership snapshot; cannot undo.")
        if prev_chip and normalize_chip(prev_chip) == "free_hit":
            # A previous FH decision describes temporary ownership, not the next GW's team.
            prev_squad_ids = cur_state.player_ids
        with closing(store._connect()) as conn:
            past_rows = conn.execute(
                "SELECT transfers_json, chip_played FROM decisions WHERE team_id = ? "
                "AND season = ? AND gameweek <= ? ORDER BY gameweek DESC",
                (team_id, season, prev_gw),
            ).fetchall()
        reverted_prices = {}
        for pid in prev_squad_ids:
            outgoing = [tx for tx in cur_tx if tx.get("outgoing_id") == pid]
            price = next((tx["outgoing_purchase_price_tenths"] for tx in outgoing
                          if "outgoing_purchase_price_tenths" in tx), None)
            reacquired = any(tx.get("incoming_id") == pid for tx in cur_tx)
            if price is None and not outgoing and not reacquired and pid in cur_state.purchase_prices_tenths:
                price = cur_state.purchase_price(pid)
            if price is None:
                for text, chip in past_rows:
                    if chip and normalize_chip(chip) == "free_hit":
                        continue
                    transactions = json.loads(text) if text else []
                    latest = next((tx for tx in reversed(transactions)
                                   if pid in (tx.get("incoming_id"), tx.get("outgoing_id"))), None)
                    if latest is not None:
                        if latest.get("incoming_id") == pid:
                            price = latest.get("purchase_price_tenths")
                        break
            if type(price) is not int or price < 0:
                raise ValueError(f"Cannot undo: no authoritative purchase-price basis for player {pid}.")
            reverted_prices[pid] = price

        net_cash_impact = 0
        if cur_tx:
            for tx in cur_tx:
                sell_p = tx.get("selling_price_tenths")
                buy_p = tx.get("purchase_price_tenths")
                if any(type(amount) is not int or amount < 0 for amount in (sell_p, buy_p)):
                    raise ValueError("Cannot undo: recorded transfers lack exact integer cash settlement.")
                net_cash_impact += sell_p - buy_p
        elif set(cur_state.player_ids) != set(prev_squad_ids):
            raise ValueError("Cannot undo: ownership changes lack an authoritative saved cash settlement.")
        reverted_bank = cur_state.bank_tenths - net_cash_impact
    if reverted_bank < 0:
        raise ValueError("Cannot undo: recorded transfers do not conserve available funds.")

    # Restore chips
    reverted_chips = list(baseline.chips_remaining if baseline else cur_state.chips_remaining)
    if baseline is None and cur_chip and not any(
        normalize_chip(cur_chip) == normalize_chip(chip) for chip in reverted_chips
    ):
        reverted_chips.append(cur_chip)

    # Restore free transfers: compute expected free transfers entering target_gw
    reverted_ft = (
        baseline.free_transfers if baseline is not None else compute_expected_free_transfers(
            target_gw=target_gw,
            team_id=team_id,
            season=season,
            database_path=database_path,
        )
    )

    reverted_state = CurrentSquadState(
        player_ids=prev_squad_ids,
        purchase_prices_tenths=reverted_prices,
        bank_tenths=reverted_bank,
        free_transfers=reverted_ft,
        chips_remaining=tuple(reverted_chips),
        season=season,
        gameweek=target_gw,
        chip_segment=cur_state.chip_segment,
        gameweek_start_state=baseline,
    )
    save_current_squad(squad_path, reverted_state)
    if cur_dec_row:
        with closing(store._connect()) as conn, conn:
            conn.execute("DELETE FROM decision_recommendations WHERE decision_id = ?", (cur_dec_row[0],))
            conn.execute("DELETE FROM decisions WHERE id = ?", (cur_dec_row[0],))

    return {
        "success": True,
        "team_id": team_id,
        "gameweek": target_gw,
        "reverted_to_gameweek": prev_gw,
        "player_ids": list(prev_squad_ids),
        "bank_tenths": reverted_bank,
        "bank_fmt": f"£{reverted_bank / 10:.1f}m",
        "free_transfers": reverted_ft,
        "message": f"Successfully reset GW{target_gw} changes and reverted squad to GW{prev_gw} state.",
    }


@live_command("apply_wildcard_or_freehit")
def apply_wildcard_or_freehit(
    squad_path: Path,
    gameweek: int,
    mode: str,
    squad_ids: list[int],
    starter_ids: list[int],
    bench_ids: list[int],
    captain_id: int,
    vice_captain_id: int,
    bank_tenths: int,
    team_id: str | None = None,
    season: str | None = None,
    database_path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    """Apply a Wildcard or Free Hit squad overhaul directly to squad state and decision log."""
    if len(squad_ids) != 15:
        raise ValueError(f"Squad must contain exactly 15 players; got {len(squad_ids)}.")
    if len(starter_ids) != 11:
        raise ValueError(f"Starting XI must contain exactly 11 players; got {len(starter_ids)}.")
    if len(bench_ids) != 4:
        raise ValueError(f"Bench must contain exactly 4 players; got {len(bench_ids)}.")
    if captain_id not in starter_ids:
        raise ValueError("Captain must be in the starting XI.")
    if vice_captain_id not in starter_ids:
        raise ValueError("Vice-Captain must be in the starting XI.")
    if captain_id == vice_captain_id:
        raise ValueError("Captain and Vice-Captain cannot be the same player.")
    if set(starter_ids) & set(bench_ids) or set(starter_ids + bench_ids) != set(squad_ids):
        raise ValueError("Starting XI and bench must partition the squad.")
    if type(bank_tenths) is not int or bank_tenths < 0:
        raise ValueError("Bank must be a non-negative integer.")
    if mode.lower().strip() not in ("initial", "init", "start", "wildcard", "wc", "freehit", "free_hit", "fh"):
        raise ValueError(f"Unknown strategic squad mode '{mode}'.")

    store = SnapshotStore(database_path)
    store.initialize()
    state = load_current_squad(squad_path)
    from .teams import get_team_id_from_squad_path
    team_id = team_id or get_team_id_from_squad_path(squad_path)
    season = season or state.season
    if season != state.season:
        raise ValueError("Strategic squad season does not match the selected squad.")
    if gameweek < (state.gameweek or 1):
        raise ValueError("Cannot apply a strategic squad to a past gameweek.")
    all_players = store.latest_players()
    player_map = {player.id: player for player in all_players}
    if any(pid not in player_map for pid in squad_ids):
        raise ValueError("Strategic squad contains unknown players.")
    squad_players = [player_map[pid] for pid in squad_ids]
    legality = validate_squad(squad_players, budget_tenths=None)
    lineup_legality = validate_starting_lineup(squad_players, starter_ids)
    if not legality.is_valid or not lineup_legality.is_valid:
        raise ValueError("; ".join((*legality.errors, *lineup_legality.errors)))

    with closing(store._connect()) as conn:
        snap = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        snap_id = snap[0] if snap else 1
        all_need_ids = sorted(set(squad_ids) | set(state.player_ids))
        placeholders = ",".join("?" for _ in all_need_ids)
        p_rows = conn.execute(
            f"SELECT player_id, price_tenths FROM players WHERE snapshot_id = ? AND player_id IN ({placeholders})",
            (snap_id, *all_need_ids),
        ).fetchall()
        costs = {r[0]: r[1] for r in p_rows}

    # Build new purchase prices: keep existing purchase price if already owned, else use current cost
    new_prices = {}
    for pid in squad_ids:
        if pid in state.purchase_prices_tenths:
            new_prices[pid] = state.purchase_prices_tenths[pid]
        else:
            new_prices[pid] = costs.get(pid, 50)

    if mode.lower().strip() in ("initial", "init", "start"):
        chip_norm = None
    elif mode.lower().strip() in ("wildcard", "wc"):
        chip_norm = "wildcard"
    else:
        chip_norm = "freehit"

    existing = get_gameweek_decision(gameweek, team_id=team_id, season=state.season, database_path=database_path)
    rem_chips = consume_chip(state, chip_norm, gameweek, existing.get("chip_played") if existing else None)
    state = prepare_live_lifecycle(
        state, gameweek, chip_norm, existing.get("chip_played") if existing else None,
    )

    if chip_norm in ("wildcard", "freehit") and state.player_ids:
        from .transfers import selling_price as _calc_sell
        old_set = set(state.player_ids)
        avail_budget = state.bank_tenths + sum(
            _calc_sell(state.purchase_price(pid), costs.get(pid, state.purchase_price(pid)))
            for pid in state.player_ids
        )
        req_cost = sum(
            _calc_sell(state.purchase_price(pid), costs.get(pid, state.purchase_price(pid)))
            if pid in old_set
            else costs.get(pid, 50)
            for pid in squad_ids
        )
        if req_cost > avail_budget:
            raise ValueError(f"Strategic squad cost ({req_cost} tenths) exceeds available budget ({avail_budget} tenths).")
        bank_tenths = avail_budget - req_cost
    elif sum(costs[pid] for pid in squad_ids) + bank_tenths > 1000:
        raise ValueError("Initial squad and bank exceed the starting budget.")

    updated_state = replace(
        state,
        player_ids=tuple(squad_ids),
        purchase_prices_tenths=new_prices,
        bank_tenths=bank_tenths,
        free_transfers=1,
        chips_remaining=tuple(rem_chips),
        season=state.season,
        gameweek=max(state.gameweek or 1, gameweek),
    )
    save_current_squad(squad_path, updated_state)
    # If default team, also sync legacy current_squad.json if present
    try:
        if team_id == "default" and "teams" in squad_path.parts:
            legacy_file = squad_path.parent.parent.parent / "current_squad.json"
            if legacy_file.exists():
                save_current_squad(legacy_file, updated_state)
    except Exception:
        pass

    # Reconcile transfers made from previous gameweek decision or previous squad state
    prev_dec = get_gameweek_decision(gameweek - 1, season=season or state.season, team_id=team_id, database_path=database_path) if gameweek > 1 else None
    if prev_dec and prev_dec.get("chip_played") and normalize_chip(prev_dec["chip_played"]) == "free_hit":
        baseline_ids = list(state.player_ids)
    elif prev_dec:
        baseline_ids = list(prev_dec.get("squad_player_ids") or (prev_dec.get("starting_player_ids", []) + prev_dec.get("bench_player_ids", [])))
    else:
        baseline_ids = list(state.player_ids)

    tx_records = reconcile_squad_transfers(
        baseline_ids,
        squad_ids,
        store,
        purchase_prices_tenths=state.purchase_prices_tenths,
    )

    # Record the gameweek decision in the database
    record_gameweek_decision(
        gameweek=gameweek,
        squad_player_ids=squad_ids,
        starting_player_ids=starter_ids,
        bench_player_ids=bench_ids,
        captain_id=captain_id,
        vice_captain_id=vice_captain_id,
        chip_played=chip_norm,
        transfers=tx_records,
        transfer_hits=0,
        team_id=team_id,
        season=season or state.season,
        database_path=database_path,
        overwrite=True,
    )

    mode_label = (chip_norm or mode or "initial").upper()
    return {
        "success": True,
        "mode": chip_norm or mode,
        "gameweek": gameweek,
        "message": f"Successfully applied {mode_label} squad for GW{gameweek}!",
        "squad_player_ids": squad_ids,
        "bank_tenths": bank_tenths,
    }
