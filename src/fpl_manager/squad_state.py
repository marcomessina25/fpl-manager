"""Private local representation of a manager's current FPL state."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CurrentSquadState:
    player_ids: tuple[int, ...]
    purchase_prices_tenths: dict[int, int]
    bank_tenths: int
    free_transfers: int
    chips_remaining: tuple[str, ...]
    season: str

    def purchase_price(self, player_id: int) -> int:
        try:
            return self.purchase_prices_tenths[player_id]
        except KeyError as error:
            raise ValueError(f"Missing purchase price for player {player_id}.") from error


def load_current_squad(path: Path) -> CurrentSquadState:
    """Load and minimally validate a private squad-state JSON file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    player_ids = tuple(raw["player_ids"])
    purchase_prices = {int(player_id): price for player_id, price in raw["purchase_prices_tenths"].items()}
    if len(player_ids) != 15:
        raise ValueError(f"Current squad must contain 15 player IDs; received {len(player_ids)}.")
    if len(set(player_ids)) != len(player_ids):
        raise ValueError("Current squad cannot contain duplicate player IDs.")
    if set(player_ids) != set(purchase_prices):
        raise ValueError("Player IDs and purchase-price IDs must match exactly.")
    if raw["bank_tenths"] < 0:
        raise ValueError("Bank cannot be negative.")
    if raw["free_transfers"] < 0:
        raise ValueError("Free transfers cannot be negative.")
    return CurrentSquadState(
        player_ids=player_ids,
        purchase_prices_tenths=purchase_prices,
        bank_tenths=raw["bank_tenths"],
        free_transfers=raw["free_transfers"],
        chips_remaining=tuple(raw.get("chips_remaining", [])),
        season=raw["season"],
    )
