"""Deterministic transfer validation using current prices and saved squad state."""

from dataclasses import dataclass
from typing import Iterable

from .models import Player
from .rules import ValidationResult, validate_squad
from .squad_state import CurrentSquadState


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
        resulting_squad = [player_by_id[player_id] for player_id in resulting_ids]
        squad_result = validate_squad(resulting_squad, budget_tenths=None)
        errors.extend(squad_result.errors)

    return TransferValidationResult(
        errors=tuple(errors),
        bank_after_tenths=bank_after,
        transfer_hits=max(0, len(proposed) - state.free_transfers),
    )
