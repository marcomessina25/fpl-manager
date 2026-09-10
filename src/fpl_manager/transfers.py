"""Deterministic transfer validation using current prices and saved squad state."""

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import Player
from .rules import ValidationResult, validate_squad
from .squad_state import CurrentSquadState, load_current_squad, save_current_squad
from .storage import SnapshotStore


@dataclass(frozen=True, slots=True)
class Transfer:
    outgoing_id: int
    incoming_id: int


@dataclass(frozen=True, slots=True)
class TransferValidationResult(ValidationResult):
    bank_after_tenths: int | None
    transfer_hits: int


def selling_price(purchase_price_tenths: int, current_price_tenths: int) -> int:
    """Calculate FPL selling price in tenths, including half of price rises."""
    if current_price_tenths <= purchase_price_tenths:
        return current_price_tenths
    return purchase_price_tenths + ((current_price_tenths - purchase_price_tenths) // 2)


def resolve_chained_transfers(
    transfers: Iterable[Transfer | dict[str, Any] | tuple[int, int]],
) -> list[Any]:
    """Resolve and logically consolidate chained transfers within a gameweek.

    If Player A is transferred for Player B, and subsequently Player B is
    transferred for Player C, the net result is a single transfer Player A -> Player C.
    Self-loops (e.g. A -> B followed by B -> A) cancel out completely.
    Distinct logical chains are strictly preserved by player identity so they
    cannot accidentally swap or transform into an incorrect transfer set.
    """
    tx_list = list(transfers)
    if not tx_list:
        return []

    def _extract_ids(tx: Any) -> tuple[int, int]:
        if isinstance(tx, Transfer):
            return tx.outgoing_id, tx.incoming_id
        if isinstance(tx, dict):
            out_val = tx.get("outgoing_id", tx.get("outgoing", 0))
            in_val = tx.get("incoming_id", tx.get("incoming", 0))
            return int(out_val), int(in_val)
        if isinstance(tx, (tuple, list)):
            return int(tx[0]), int(tx[1])
        raise TypeError(f"Unsupported transfer item type: {type(tx)}")

    # active_chains: list of [initial_out_id, current_in_id, first_raw_item, last_raw_item]
    active_chains: list[list[Any]] = []

    for item in tx_list:
        out_id, in_id = _extract_ids(item)
        if out_id == in_id:
            continue

        # Find existing chain where current_incoming_id == out_id (predecessor)
        pred_chain = next(
            (c for c in active_chains if c[1] == out_id),
            None,
        )
        # Find existing chain where initial_outgoing_id == in_id (successor)
        succ_chain = next(
            (c for c in active_chains if c[0] == in_id),
            None,
        )

        if pred_chain is not None and succ_chain is not None:
            if pred_chain is succ_chain:
                active_chains.remove(pred_chain)
            else:
                new_out = pred_chain[0]
                new_in = succ_chain[1]
                last_raw = succ_chain[3]
                if new_out == new_in:
                    active_chains.remove(pred_chain)
                    active_chains.remove(succ_chain)
                else:
                    pred_chain[1] = new_in
                    pred_chain[3] = last_raw
                    active_chains.remove(succ_chain)
        elif pred_chain is not None:
            if pred_chain[0] == in_id:
                active_chains.remove(pred_chain)
            else:
                pred_chain[1] = in_id
                pred_chain[3] = item
        elif succ_chain is not None:
            if succ_chain[1] == out_id:
                active_chains.remove(succ_chain)
            else:
                succ_chain[0] = out_id
                succ_chain[2] = item
        else:
            active_chains.append([out_id, in_id, item, item])

    results: list[Any] = []
    for init_out, cur_in, first_raw, last_raw in active_chains:
        if isinstance(first_raw, dict):
            merged_dict = dict(first_raw)
            merged_dict["outgoing_id"] = init_out
            merged_dict["incoming_id"] = cur_in
            if isinstance(last_raw, dict):
                if "incoming_name" in last_raw:
                    merged_dict["incoming_name"] = last_raw["incoming_name"]
                if "incoming_team" in last_raw:
                    merged_dict["incoming_team"] = last_raw["incoming_team"]
                if "purchase_price_tenths" in last_raw:
                    merged_dict["purchase_price_tenths"] = last_raw["purchase_price_tenths"]
            results.append(merged_dict)
        elif isinstance(first_raw, Transfer):
            results.append(Transfer(outgoing_id=init_out, incoming_id=cur_in))
        elif isinstance(first_raw, tuple):
            results.append((init_out, cur_in))
        else:
            results.append(Transfer(outgoing_id=init_out, incoming_id=cur_in))

    return results


def validate_transfers(
    state: CurrentSquadState,
    players: Iterable[Player],
    transfers: Iterable[Transfer],
) -> TransferValidationResult:
    """Validate a position-preserving transfer set against state, bank, and squad rules."""
    player_by_id = {player.id: player for player in players}
    proposed = tuple(resolve_chained_transfers(transfers))
    errors: list[str] = []
    outgoing_ids = [transfer.outgoing_id for transfer in proposed]
    incoming_ids = [transfer.incoming_id for transfer in proposed]

    if not proposed:
        errors.append("At least one transfer is required.")
    if len(set(outgoing_ids)) != len(outgoing_ids):
        errors.append("A player cannot be transferred out more than once.")
    if len(set(incoming_ids)) != len(incoming_ids):
        errors.append("A player cannot be transferred in more than once.")

    # If any proposed transfer crosses positions, check if overall positions match and re-align
    all_known_out = [player_by_id.get(t.outgoing_id) for t in proposed]
    all_known_in = [player_by_id.get(t.incoming_id) for t in proposed]
    if all(p is not None for p in all_known_out) and all(p is not None for p in all_known_in):
        out_pos = sorted(p.position.value for p in all_known_out)
        in_pos = sorted(p.position.value for p in all_known_in)
        if out_pos == in_pos and any(o.position != i.position for o, i in zip(all_known_out, all_known_in)):
            outs_by_pos: dict[Any, list[int]] = {}
            for t in proposed:
                p = player_by_id[t.outgoing_id]
                outs_by_pos.setdefault(p.position, []).append(t.outgoing_id)
            ins_by_pos: dict[Any, list[int]] = {}
            for t in proposed:
                p = player_by_id[t.incoming_id]
                ins_by_pos.setdefault(p.position, []).append(t.incoming_id)

            realigned = []
            for pos, out_list in outs_by_pos.items():
                in_list = ins_by_pos.get(pos, [])
                for o_id, i_id in zip(out_list, in_list):
                    realigned.append(Transfer(outgoing_id=o_id, incoming_id=i_id))
            proposed = tuple(realigned)

    squad_ids = set(state.player_ids)
    for transfer in proposed:
        outgoing = player_by_id.get(transfer.outgoing_id)
        incoming = player_by_id.get(transfer.incoming_id)
        if transfer.outgoing_id not in squad_ids:
            errors.append(f"Player {transfer.outgoing_id} is not in the current squad.")
        if transfer.incoming_id in squad_ids and transfer.incoming_id not in outgoing_ids:
            errors.append(f"Player {transfer.incoming_id} is already in the current squad.")
        if outgoing is None:
            errors.append(f"No current FPL data for outgoing player {transfer.outgoing_id}.")
        if incoming is None:
            errors.append(f"No current FPL data for incoming player {transfer.incoming_id}.")
        if outgoing and incoming and outgoing.position != incoming.position:
            errors.append(f"Transfer {outgoing.id} -> {incoming.id} changes position and is not legal.")

    bank_after: int | None = None
    if not errors:
        proceeds = sum(
            selling_price(state.purchase_price(transfer.outgoing_id), player_by_id[transfer.outgoing_id].price_tenths)
            for transfer in proposed
        )
        cost = sum(player_by_id[transfer.incoming_id].price_tenths for transfer in proposed)
        bank_after = state.bank_tenths + proceeds - cost
        if bank_after < 0:
            errors.append(f"Transfers need £{-bank_after / 10:.1f}m more than is available.")

        resulting_ids = (squad_ids - set(outgoing_ids)) | set(incoming_ids)
        resulting_squad = [player_by_id[player_id] for player_id in resulting_ids if player_id in player_by_id]
        squad_result = validate_squad(resulting_squad, budget_tenths=None)
        errors.extend(squad_result.errors)

    return TransferValidationResult(
        errors=tuple(errors),
        bank_after_tenths=bank_after,
        transfer_hits=max(0, len(proposed) - state.free_transfers),
    )


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = PROJECT_ROOT / "data" / "fpl.sqlite3"


def execute_transfers(
    squad_path: Path,
    transfers: list[Transfer | dict[str, Any] | tuple[int, int]],
    database_path: Path = DATABASE_PATH,
    gameweek: int | None = None,
) -> dict[str, Any]:
    """Execute and persist proposed transfers directly to the squad state file and decision records."""
    orig_state_text = squad_path.read_text(encoding="utf-8") if squad_path.exists() else None
    state = load_current_squad(squad_path)
    store = SnapshotStore(database_path)
    store.initialize()

    tx_objs: list[Transfer] = []
    for t in transfers:
        if isinstance(t, Transfer):
            tx_objs.append(t)
        elif isinstance(t, (tuple, list)):
            tx_objs.append(Transfer(outgoing_id=int(t[0]), incoming_id=int(t[1])))
        elif isinstance(t, dict):
            out_id = int(t.get("outgoing_id", t.get("outgoing", 0)))
            in_id = int(t.get("incoming_id", t.get("incoming", 0)))
            tx_objs.append(Transfer(outgoing_id=out_id, incoming_id=in_id))

    tx_objs = resolve_chained_transfers(tx_objs)
    if not tx_objs:
        raise ValueError("No net transfers to execute.")

    all_players = store.latest_players()
    all_player_map = {p.id: p for p in all_players}
    out_with_p = [all_player_map.get(tx.outgoing_id) for tx in tx_objs]
    in_with_p = [all_player_map.get(tx.incoming_id) for tx in tx_objs]
    if all(p is not None for p in out_with_p) and all(p is not None for p in in_with_p):
        out_pos = sorted(p.position.value for p in out_with_p)
        in_pos = sorted(p.position.value for p in in_with_p)
        if out_pos == in_pos and any(o.position != i.position for o, i in zip(out_with_p, in_with_p)):
            outs_by_pos: dict[Any, list[int]] = {}
            for tx in tx_objs:
                p = all_player_map[tx.outgoing_id]
                outs_by_pos.setdefault(p.position, []).append(tx.outgoing_id)
            ins_by_pos: dict[Any, list[int]] = {}
            for tx in tx_objs:
                p = all_player_map[tx.incoming_id]
                ins_by_pos.setdefault(p.position, []).append(tx.incoming_id)

            realigned = []
            for pos, out_list in outs_by_pos.items():
                in_list = ins_by_pos.get(pos, [])
                for o_id, i_id in zip(out_list, in_list):
                    realigned.append(Transfer(outgoing_id=o_id, incoming_id=i_id))
            tx_objs = realigned

    val_res = validate_transfers(state, all_players, tx_objs)
    if not val_res.is_valid:
        raise ValueError(f"Transfer validation failed: {'; '.join(val_res.errors)}")

    team_id = "default"
    try:
        from .teams import get_team_id_from_squad_path
        team_id = get_team_id_from_squad_path(squad_path)
    except Exception:
        pass

    target_gw = gameweek or state.gameweek
    existing_dec = None
    existing_tx: list[dict[str, Any]] = []
    if target_gw is not None:
        try:
            from .decision_log import get_gameweek_decision
            existing_dec = get_gameweek_decision(target_gw, season=state.season, team_id=team_id, database_path=database_path)
            if existing_dec is not None:
                existing_tx = existing_dec.get("transfers", [])
        except Exception:
            pass

    player_map = {p.id: p for p in all_players}
    new_ids = list(state.player_ids)
    new_prices = dict(state.purchase_prices_tenths)
    records = []

    for tx in tx_objs:
        out_p = player_map[tx.outgoing_id]
        in_p = player_map[tx.incoming_id]

        out_purchase = state.purchase_price(tx.outgoing_id)
        sell_p = selling_price(out_purchase, out_p.price_tenths)

        new_ids.remove(tx.outgoing_id)
        new_ids.append(tx.incoming_id)

        new_prices.pop(tx.outgoing_id, None)
        # Restore pre-transfer purchase price if player is being re-acquired within the same gameweek
        orig_p_purchase = None
        for ptx in existing_tx:
            if ptx.get("outgoing_id") == tx.incoming_id:
                orig_p_purchase = ptx.get("outgoing_purchase_price_tenths")
                break
        new_prices[tx.incoming_id] = orig_p_purchase if orig_p_purchase is not None else in_p.price_tenths

        records.append({
            "outgoing_id": tx.outgoing_id,
            "outgoing_name": out_p.name,
            "outgoing_team": out_p.team_id,
            "incoming_id": tx.incoming_id,
            "incoming_name": in_p.name,
            "incoming_team": in_p.team_id,
            "selling_price_tenths": sell_p,
            "purchase_price_tenths": in_p.price_tenths,
            "outgoing_purchase_price_tenths": out_purchase,
        })

    num_tx = len(tx_objs)
    new_bank = val_res.bank_after_tenths if val_res.bank_after_tenths is not None else state.bank_tenths

    merged_tx = resolve_chained_transfers(list(existing_tx) + list(records)) if existing_tx else resolve_chained_transfers(records)
    tx_hits = val_res.transfer_hits
    starting_ft = max(1, state.free_transfers)

    orig_decision_row = None
    orig_recommendation_row = None
    if target_gw is not None:
        try:
            with closing(store._connect()) as conn:
                orig_decision_row = conn.execute(
                    """
                    SELECT id, team_id, season, gameweek, timestamp, chip_played, transfer_hits,
                           transfers_json, starting_ids_json, bench_ids_json, captain_id, vice_captain_id,
                           predicted_lineup_xp, predicted_floor_xp, predicted_ceiling_xp, actual_points, notes
                    FROM decisions
                    WHERE team_id = ? AND season = ? AND gameweek = ?
                    """,
                    (team_id, state.season, target_gw),
                ).fetchone()
                if orig_decision_row:
                    orig_recommendation_row = conn.execute(
                        """
                        SELECT recommended_lineup_json, recommended_transfers_json, recommended_plan_json
                        FROM decision_recommendations
                        WHERE decision_id = ?
                        """,
                        (orig_decision_row[0],),
                    ).fetchone()
        except Exception:
            pass

    try:
        if target_gw is not None:
            from .decision_log import (
                compute_expected_free_transfers,
                record_gameweek_decision,
            )

            try:
                starting_ft = compute_expected_free_transfers(
                    target_gw,
                    team_id=team_id,
                    season=state.season,
                    database_path=database_path,
                )
            except Exception:
                starting_ft = max(1, state.free_transfers)

            if existing_dec is not None:
                cur_starters = list(existing_dec.get("starting_player_ids", []))
                cur_bench = list(existing_dec.get("bench_player_ids", []))
                cur_cap = existing_dec.get("captain_id")
                cur_vc = existing_dec.get("vice_captain_id")
                chip_played = existing_dec.get("chip_played")
                notes = existing_dec.get("notes", "")
            else:
                from .decision_log import get_gameweek_decision
                prev_dec = None
                if target_gw > 1:
                    prev_dec = get_gameweek_decision(target_gw - 1, season=state.season, team_id=team_id, database_path=database_path)
                if prev_dec is not None and len(prev_dec.get("starting_player_ids", [])) == 11 and len(prev_dec.get("bench_player_ids", [])) == 4:
                    cur_starters = list(prev_dec.get("starting_player_ids", []))
                    cur_bench = list(prev_dec.get("bench_player_ids", []))
                    cur_cap = prev_dec.get("captain_id")
                    cur_vc = prev_dec.get("vice_captain_id")
                    chip_played = None
                    notes = ""
                else:
                    cur_starters = []
                    cur_bench = []
                    cur_cap = None
                    cur_vc = None
                    chip_played = None
                    notes = ""

            for tx in tx_objs:
                if tx.outgoing_id in cur_starters:
                    idx = cur_starters.index(tx.outgoing_id)
                    cur_starters[idx] = tx.incoming_id
                elif tx.outgoing_id in cur_bench:
                    idx = cur_bench.index(tx.outgoing_id)
                    cur_bench[idx] = tx.incoming_id
                if cur_cap == tx.outgoing_id:
                    cur_cap = tx.incoming_id
                if cur_vc == tx.outgoing_id:
                    cur_vc = tx.incoming_id

            if set(cur_starters + cur_bench) != set(new_ids) or len(cur_starters) != 11 or len(cur_bench) != 4:
                tmp_state = CurrentSquadState(
                    player_ids=tuple(new_ids),
                    purchase_prices_tenths=new_prices,
                    bank_tenths=new_bank,
                    free_transfers=max(0, starting_ft - len(merged_tx)),
                    chips_remaining=state.chips_remaining,
                    season=state.season,
                    gameweek=state.gameweek,
                )
                save_current_squad(squad_path, tmp_state)
                from .lineup import select_starting_lineup
                lineup_sol = select_starting_lineup(squad_path=squad_path, database_path=database_path, gameweek=target_gw)
                cur_starters = [p["id"] for p in lineup_sol["starters"]]
                cur_bench = [p["id"] for p in lineup_sol["bench"]]
                cur_cap = lineup_sol["captain"]["id"]
                cur_vc = lineup_sol["vice_captain"]["id"]

            if cur_cap not in cur_starters:
                cur_cap = cur_starters[0] if cur_starters else None
            if cur_vc not in cur_starters or cur_vc == cur_cap:
                other_starters = [p for p in cur_starters if p != cur_cap]
                cur_vc = other_starters[0] if other_starters else cur_cap

            if chip_played and str(chip_played).lower().strip() in ("wildcard", "wc", "freehit", "free_hit", "fh"):
                tx_hits = 0
            else:
                tx_hits = max(0, len(merged_tx) - starting_ft)

            record_gameweek_decision(
                gameweek=target_gw,
                season=state.season,
                team_id=team_id,
                squad_player_ids=new_ids,
                starting_player_ids=cur_starters,
                bench_player_ids=cur_bench,
                captain_id=cur_cap,
                vice_captain_id=cur_vc,
                transfers=merged_tx,
                transfer_hits=tx_hits,
                chip_played=chip_played,
                notes=notes,
                database_path=database_path,
                overwrite=True,
            )

        new_ft = max(0, starting_ft - len(merged_tx))
        updated_state = CurrentSquadState(
            player_ids=tuple(new_ids),
            purchase_prices_tenths=new_prices,
            bank_tenths=new_bank,
            free_transfers=new_ft,
            chips_remaining=state.chips_remaining,
            season=state.season,
            gameweek=max(state.gameweek or 1, target_gw or 1),
        )
        save_current_squad(squad_path, updated_state)
    except Exception:
        # Explicit compensating rollback across both persistence systems
        # 1. Restore squad state file
        try:
            if orig_state_text is not None:
                squad_path.write_text(orig_state_text, encoding="utf-8")
            elif squad_path.exists():
                squad_path.unlink()
        except Exception:
            pass

        # 2. Restore decision record in database
        try:
            with closing(store._connect()) as conn, conn:
                if orig_decision_row is not None:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO decisions (
                            id, team_id, season, gameweek, timestamp, chip_played, transfer_hits,
                            transfers_json, starting_ids_json, bench_ids_json, captain_id, vice_captain_id,
                            predicted_lineup_xp, predicted_floor_xp, predicted_ceiling_xp, actual_points, notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        orig_decision_row,
                    )
                    if orig_recommendation_row is not None:
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO decision_recommendations (
                                decision_id, recommended_lineup_json, recommended_transfers_json, recommended_plan_json
                            ) VALUES (?, ?, ?, ?)
                            """,
                            (orig_decision_row[0], *orig_recommendation_row),
                        )
                    else:
                        conn.execute(
                            "DELETE FROM decision_recommendations WHERE decision_id = ?",
                            (orig_decision_row[0],),
                        )
                elif target_gw is not None:
                    conn.execute(
                        """
                        DELETE FROM decision_recommendations
                        WHERE decision_id IN (
                            SELECT id FROM decisions WHERE team_id = ? AND season = ? AND gameweek = ?
                        )
                        """,
                        (team_id, state.season, target_gw),
                    )
                    conn.execute(
                        "DELETE FROM decisions WHERE team_id = ? AND season = ? AND gameweek = ?",
                        (team_id, state.season, target_gw),
                    )
        except Exception:
            pass

        raise

    return {
        "success": True,
        "team_id": team_id,
        "gameweek": target_gw,
        "transfers": merged_tx,
        "bank_tenths": new_bank,
        "bank_fmt": f"£{new_bank / 10:.1f}m",
        "free_transfers": new_ft,
        "transfer_hits": tx_hits,
        "new_player_ids": new_ids,
    }
