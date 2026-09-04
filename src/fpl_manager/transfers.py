"""Deterministic transfer validation using current prices and saved squad state."""

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


def validate_transfers(
    state: CurrentSquadState,
    players: Iterable[Player],
    transfers: Iterable[Transfer],
) -> TransferValidationResult:
    """Validate a position-preserving transfer set against state, bank, and squad rules."""
    player_by_id = {player.id: player for player in players}
    proposed = tuple(transfers)
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
        new_prices[tx.incoming_id] = in_p.price_tenths

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
    new_ft = max(0, state.free_transfers - num_tx)

    updated_state = CurrentSquadState(
        player_ids=tuple(new_ids),
        purchase_prices_tenths=new_prices,
        bank_tenths=new_bank,
        free_transfers=new_ft,
        chips_remaining=state.chips_remaining,
        season=state.season,
        gameweek=state.gameweek,
    )
    save_current_squad(squad_path, updated_state)

    team_id = "default"
    try:
        from .teams import get_team_id_from_squad_path
        team_id = get_team_id_from_squad_path(squad_path)
    except Exception:
        pass

    target_gw = gameweek or state.gameweek
    if target_gw is not None:
        try:
            from .decision_log import get_gameweek_decision, record_gameweek_decision
            existing_dec = get_gameweek_decision(target_gw, season=state.season, team_id=team_id, database_path=database_path)
            if existing_dec is not None:
                existing_tx = existing_dec.get("transfers", [])
                merged_tx = existing_tx + records

                cur_starters = list(existing_dec.get("starting_player_ids", []))
                cur_bench = list(existing_dec.get("bench_player_ids", []))
                cur_cap = existing_dec.get("captain_id")
                cur_vc = existing_dec.get("vice_captain_id")

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
                    transfer_hits=max(0, len(merged_tx) - state.free_transfers),
                    chip_played=existing_dec.get("chip_played"),
                    notes=existing_dec.get("notes", ""),
                    database_path=database_path,
                    overwrite=True,
                )
        except Exception:
            pass

    return {
        "success": True,
        "team_id": team_id,
        "gameweek": target_gw,
        "transfers": records,
        "bank_tenths": new_bank,
        "bank_fmt": f"£{new_bank / 10:.1f}m",
        "free_transfers": new_ft,
        "transfer_hits": val_res.transfer_hits,
        "new_player_ids": new_ids,
    }
