"""Private local representation of a manager's current FPL state."""

import json
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from functools import wraps
from inspect import signature


@dataclass(frozen=True, slots=True)
class CurrentSquadState:
    player_ids: tuple[int, ...]
    purchase_prices_tenths: dict[int, int]
    bank_tenths: int
    free_transfers: int
    chips_remaining: tuple[str, ...]
    season: str
    gameweek: int | None = None
    chip_segment: int | None = None

    def purchase_price(self, player_id: int) -> int:
        try:
            return self.purchase_prices_tenths[player_id]
        except KeyError as error:
            raise ValueError(f"Missing purchase price for player {player_id}.") from error


def validate_current_squad(state: CurrentSquadState) -> None:
    """Validate ownership and integer money without capping appreciated team value."""
    if len(state.player_ids) != 15 or len(set(state.player_ids)) != 15:
        raise ValueError("Current squad must contain 15 distinct player IDs.")
    if set(state.player_ids) != set(state.purchase_prices_tenths):
        raise ValueError("Player IDs and purchase-price IDs must match exactly.")
    for label, amount in [("Bank", state.bank_tenths), ("Free transfers", state.free_transfers)]:
        if type(amount) is not int or amount < 0:
            raise ValueError(f"{label} must be a non-negative integer.")
    if any(type(price) is not int or price < 0 for price in state.purchase_prices_tenths.values()):
        raise ValueError("Purchase prices must be non-negative integer tenths.")
    if state.chip_segment not in (None, 1, 2):
        raise ValueError("Chip segment must be 1 or 2.")


def live_command(operation: str):
    """Put standalone live domain mutations through the shared durable command bus."""
    def decorate(function):
        sig = signature(function)

        @wraps(function)
        def wrapped(*args, **kwargs):
            from .application import CommandBus, LiveContext, active_command
            from .teams import (
                get_active_team_id, get_team_id_from_squad_path, get_team_squad_path,
                slugify_team_id, team_workspace_exists,
            )
            from .application.files import state_file_exists
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            values = bound.arguments
            path = values.get("squad_path") or values.get("squad_file")
            team_id = values.get("team_id")
            state = values.get("squad_state")
            if function.__module__.endswith(".teams") and path is None:
                config_dir = values.get("config_dir")
                if operation == "create_team" and team_id:
                    team_id = slugify_team_id(team_id)
                if operation == "create_team" and not team_id:
                    base_id = slugify_team_id(values["name"])
                    team_id = base_id
                    suffix = 2
                    while team_workspace_exists(team_id, config_dir):
                        team_id = f"{base_id}-{suffix}"
                        suffix += 1
                team_id = team_id or get_active_team_id(config_dir)
                candidate = get_team_squad_path(team_id, config_dir)
                if state_file_exists(candidate):
                    path = candidate
                elif state is None:
                    source = get_team_squad_path(values.get("copy_from_team_id"), config_dir)
                    if state_file_exists(source):
                        state = load_current_squad(source)
            if path is not None:
                state = load_current_squad(Path(path))
                owned_path = Path(path)
                if (
                    owned_path.name == "squad.json" and owned_path.parent.parent.name == "teams"
                    and team_id is not None and team_id != owned_path.parent.name
                ):
                    raise ValueError("Command team ID does not match the selected squad file.")
            team_id = team_id or (
                get_team_id_from_squad_path(Path(path)) if path is not None else "default"
            )
            context = LiveContext(
                team_id=str(team_id),
                season=state.season if state is not None else values.get("season", "2026/27"),
                gameweek=values.get("target_gameweek") or values.get("gameweek") or (
                    state.gameweek if state is not None else None
                ) or 1,
            )
            database_path = values.get("database_path")
            if database_path is None:
                config_dir = values.get("config_dir")
                database_path = (
                    Path(config_dir).parent / "data" / "fpl.sqlite3"
                    if config_dir is not None else Path(__file__).resolve().parents[2] / "data" / "fpl.sqlite3"
                )

            def invoke():
                if path is not None and operation in {
                    "execute_transfers", "log_decision_from_current_squad", "apply_wildcard_or_freehit",
                }:
                    current = load_current_squad(Path(path))
                    target = values.get("gameweek") or current.gameweek or 1
                    if target > (current.gameweek or 1) or (target >= 20 and current.chip_segment == 1):
                        from .teams import advance_current_squad
                        advance_current_squad(
                            Path(path), target_gameweek=target, team_id=str(team_id),
                            config_dir=values.get("config_dir"), database_path=Path(database_path),
                        )
                return function(*args, **kwargs)

            if active_command(context) is not None:
                return invoke()
            def serializable(value):
                if isinstance(value, Path):
                    return str(value)
                if is_dataclass(value):
                    return serializable(asdict(value))
                if isinstance(value, dict):
                    return {str(key): serializable(item) for key, item in value.items()}
                if isinstance(value, (tuple, list)):
                    return [serializable(item) for item in value]
                return value
            payload = serializable({key: value for key, value in values.items() if key != "database_path"})
            receipt = CommandBus(Path(database_path)).execute(
                context, operation, payload, invoke
            )
            return receipt.result
        return wrapped
    return decorate


def load_current_squad(path: Path) -> CurrentSquadState:
    """Load and minimally validate a private squad-state JSON file."""
    from .application.files import read_state_text
    raw = json.loads(read_state_text(path))
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
    raw_gw = raw.get("gameweek") or raw.get("current_gameweek")
    gw_val = int(raw_gw) if raw_gw is not None else None
    state = CurrentSquadState(
        player_ids=player_ids,
        purchase_prices_tenths=purchase_prices,
        bank_tenths=raw["bank_tenths"],
        free_transfers=raw["free_transfers"],
        chips_remaining=tuple(raw.get("chips_remaining", [])),
        season=raw["season"],
        gameweek=gw_val,
        chip_segment=raw.get("chip_segment"),
    )
    validate_current_squad(state)
    return state


def save_current_squad(path: Path, state: CurrentSquadState) -> None:
    """Save current squad state to a JSON file."""
    from .application.files import write_state_text
    validate_current_squad(state)
    data = {
        "season": state.season,
        "gameweek": state.gameweek if state.gameweek is not None else 1,
        "player_ids": list(state.player_ids),
        "purchase_prices_tenths": {str(pid): price for pid, price in state.purchase_prices_tenths.items()},
        "bank_tenths": state.bank_tenths,
        "free_transfers": state.free_transfers,
        "chips_remaining": list(state.chips_remaining),
        "chip_segment": state.chip_segment,
    }
    write_state_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
