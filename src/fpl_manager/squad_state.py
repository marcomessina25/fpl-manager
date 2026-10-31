"""Private local representation of a manager's current FPL state."""

import json
from dataclasses import asdict, dataclass, is_dataclass, replace
from pathlib import Path
from functools import wraps
from inspect import signature


@dataclass(frozen=True, slots=True)
class OwnershipSnapshot:
    """Authoritative saved human ownership, never inferred from market quotes."""

    player_ids: tuple[int, ...]
    purchase_prices_tenths: dict[int, int]
    bank_tenths: int
    free_transfers: int
    chips_remaining: tuple[str, ...]
    season: str
    gameweek: int
    chip_segment: int | None

    @classmethod
    def capture(cls, state: "CurrentSquadState", gameweek: int) -> "OwnershipSnapshot":
        return cls(
            tuple(state.player_ids), dict(state.purchase_prices_tenths), state.bank_tenths,
            state.free_transfers, tuple(state.chips_remaining), state.season,
            gameweek, state.chip_segment,
        )

    def restore(self, state: "CurrentSquadState") -> "CurrentSquadState":
        return replace(
            state, player_ids=self.player_ids, purchase_prices_tenths=dict(self.purchase_prices_tenths),
            bank_tenths=self.bank_tenths,
        )


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
    gameweek_start_state: OwnershipSnapshot | None = None
    pre_free_hit_state: OwnershipSnapshot | None = None

    def purchase_price(self, player_id: int) -> int:
        try:
            return self.purchase_prices_tenths[player_id]
        except KeyError as error:
            raise ValueError(f"Missing purchase price for player {player_id}.") from error


def validate_current_squad(state: CurrentSquadState) -> None:
    """Validate ownership and integer money without capping appreciated team value."""
    if len(state.player_ids) != 15 or len(set(state.player_ids)) != 15:
        raise ValueError("Current squad must contain 15 distinct player IDs.")
    if any(type(pid) is not int or pid <= 0 for pid in state.player_ids):
        raise ValueError("Player IDs must be positive integers.")
    if set(state.player_ids) != set(state.purchase_prices_tenths):
        raise ValueError("Player IDs and purchase-price IDs must match exactly.")
    if any(type(pid) is not int or pid <= 0 for pid in state.purchase_prices_tenths):
        raise ValueError("Purchase-price IDs must be positive integers.")
    for label, amount in [("Bank", state.bank_tenths), ("Free transfers", state.free_transfers)]:
        if type(amount) is not int or amount < 0:
            raise ValueError(f"{label} must be a non-negative integer.")
    if any(type(price) is not int or price < 0 for price in state.purchase_prices_tenths.values()):
        raise ValueError("Purchase prices must be non-negative integer tenths.")
    if state.chip_segment is not None and (type(state.chip_segment) is not int or state.chip_segment not in (1, 2)):
        raise ValueError("Chip segment must be 1 or 2.")
    if state.gameweek is not None and (type(state.gameweek) is not int or not 1 <= state.gameweek <= 38):
        raise ValueError("Gameweek must be an integer between 1 and 38.")
    if not isinstance(state.season, str) or not state.season.strip():
        raise ValueError("Season must be a nonempty string.")
    if any(not isinstance(chip, str) or not chip.strip() for chip in state.chips_remaining):
        raise ValueError("Chips must be nonempty strings.")
    for snapshot in (state.gameweek_start_state, state.pre_free_hit_state):
        if snapshot is None:
            continue
        if not isinstance(snapshot, OwnershipSnapshot):
            raise ValueError("Saved ownership must be an OwnershipSnapshot.")
        validate_current_squad(CurrentSquadState(
            snapshot.player_ids, snapshot.purchase_prices_tenths, snapshot.bank_tenths,
            snapshot.free_transfers, snapshot.chips_remaining, snapshot.season,
            snapshot.gameweek, snapshot.chip_segment,
        ))
        if snapshot.season != state.season or snapshot.gameweek != (state.gameweek or 1):
            raise ValueError("Saved ownership season/gameweek must match the current squad.")


def prepare_live_lifecycle(
    state: CurrentSquadState, gameweek: int, chip: str | None, already_played: str | None = None,
) -> CurrentSquadState:
    """Capture once before any temporary transfer or same-deadline ownership edit."""
    from .decision_log import normalize_chip
    validate_current_squad(state)
    if gameweek != (state.gameweek or 1):
        raise ValueError("Advance the squad before capturing gameweek ownership.")
    if already_played and normalize_chip(already_played) == "free_hit" and state.pre_free_hit_state is None:
        raise ValueError("Legacy Free Hit has no authoritative pre-chip ownership snapshot; reconcile it before editing.")
    baseline = state.gameweek_start_state or OwnershipSnapshot.capture(state, gameweek)
    temporary = state.pre_free_hit_state
    if chip and normalize_chip(chip) == "free_hit" and temporary is None:
        # Free Hit reverses all transfers for this deadline, including earlier ones.
        temporary = baseline
    return replace(state, gameweek_start_state=baseline, pre_free_hit_state=temporary)


def live_command(operation: str):
    """Put standalone live domain mutations through the shared durable command bus."""
    def decorate(function):
        sig = signature(function)

        @wraps(function)
        def wrapped(*args, **kwargs):
            from .application import CommandBus, LiveContext, active_command
            from .teams import (
                get_active_team_id, get_team_id_from_squad_path, get_team_squad_path,
                resolve_creation_squad, slugify_team_id, team_workspace_exists,
            )
            from .application.files import state_file_exists
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            values = bound.arguments
            auto_creation = operation == "create_team" and not values.get("team_id")
            path = values.get("squad_path") or values.get("squad_file")
            team_id = values.get("team_id")
            state = values.get("squad_state")
            if function.__module__.endswith(".teams") and path is None:
                config_dir = values.get("config_dir")
                if operation == "create_team":
                    if not values["name"] or not values["name"].strip():
                        raise ValueError("Team name cannot be empty.")
                    state = resolve_creation_squad(state, values.get("copy_from_team_id"), config_dir)
                    values["squad_state"] = state
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
                if operation == "create_team":
                    values["team_id"] = team_id
                else:
                    candidate = get_team_squad_path(team_id, config_dir)
                    if state_file_exists(candidate):
                        path = candidate
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
                return function(*bound.args, **bound.kwargs)

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
            from .teams import TeamIDCollision
            for attempt in range(64):
                payload = serializable({key: value for key, value in values.items() if key != "database_path"})
                try:
                    receipt = CommandBus(Path(database_path)).execute(context, operation, payload, invoke)
                    return receipt.result
                except TeamIDCollision:
                    if not auto_creation or attempt == 63:
                        raise
                    # The failed command rolled back under SQLite's process-wide write lock.
                    # Rebind a new identity before entering the next command, never inside it.
                    suffix = 2
                    team_id = base_id
                    while team_workspace_exists(team_id, config_dir):
                        team_id = f"{base_id}-{suffix}"
                        suffix += 1
                    values["team_id"] = team_id
                    context = replace(context, team_id=team_id)
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
        gameweek_start_state=_load_ownership_snapshot(raw.get("gameweek_start_state")),
        pre_free_hit_state=_load_ownership_snapshot(raw.get("pre_free_hit_state")),
    )
    validate_current_squad(state)
    return state


def _load_ownership_snapshot(raw: object) -> OwnershipSnapshot | None:
    if raw is None:
        return None
    fields = {
        "player_ids", "purchase_prices_tenths", "bank_tenths", "free_transfers",
        "chips_remaining", "season", "gameweek", "chip_segment",
    }
    if not isinstance(raw, dict) or set(raw) != fields:
        raise ValueError("Saved ownership snapshot must contain all typed lifecycle fields.")
    if not isinstance(raw["player_ids"], list) or not isinstance(raw["purchase_prices_tenths"], dict):
        raise ValueError("Saved ownership IDs/prices must be a list and mapping.")
    if not isinstance(raw["chips_remaining"], list):
        raise ValueError("Saved ownership chips must be a list.")
    try:
        prices = {int(pid): price for pid, price in raw["purchase_prices_tenths"].items()}
    except (ValueError, TypeError) as error:
        raise ValueError("Saved ownership purchase-price IDs must be integers.") from error
    return OwnershipSnapshot(
        tuple(raw["player_ids"]), prices, raw["bank_tenths"], raw["free_transfers"],
        tuple(raw["chips_remaining"]), raw["season"], raw["gameweek"], raw["chip_segment"],
    )


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
    for field, snapshot in (
        ("gameweek_start_state", state.gameweek_start_state),
        ("pre_free_hit_state", state.pre_free_hit_state),
    ):
        if snapshot is not None:
            data[field] = asdict(snapshot)
    write_state_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
