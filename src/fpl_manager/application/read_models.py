"""Client-independent read contracts with revision and provenance identities."""

from dataclasses import dataclass
from copy import deepcopy
from typing import Any

from .contexts import CommandContext


@dataclass(frozen=True)
class StateIdentity:
    context: CommandContext
    revision: int
    execution_version: str
    read_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_context": self.context.to_dict(), "revision": self.revision,
            "execution_version": self.execution_version, "read_only": self.read_only,
        }


@dataclass(frozen=True)
class ReadModel:
    identity: StateIdentity
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {**self.data, **self.identity.to_dict()}


@dataclass(frozen=True)
class PlayerValuation:
    player_id: int
    purchase_price_tenths: int
    current_price_tenths: int | None
    selling_price_tenths: int | None


@dataclass(frozen=True)
class StagedMove:
    outgoing_id: int
    incoming_id: int
    cost_tenths: int | None
    already_applied: bool


@dataclass(frozen=True)
class SquadReadModel(ReadModel):
    valuations: tuple[PlayerValuation, ...] = ()
    staged_moves: tuple[StagedMove, ...] = ()


@dataclass(frozen=True)
class LineupReadModel(ReadModel):
    starting_ids: tuple[int, ...] = ()
    bench_ids: tuple[int, ...] = ()
    captain_id: int | None = None
    vice_captain_id: int | None = None


@dataclass(frozen=True)
class PlanReadModel(ReadModel):
    steps: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class DecisionReadModel(ReadModel):
    decisions: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ChipReadModel(ReadModel):
    available_chips: tuple[str, ...] = ()
    recommended_schedule: tuple[dict[str, Any], ...] = ()


def build_read_model(identity: StateIdentity, operation: str, data: dict[str, Any]) -> ReadModel:
    leaf = operation.rstrip("/").rsplit("/", 1)[-1]
    if "strategic-squad" in operation and leaf != "config":
        data = deepcopy(data)
        candidates = [data]
        selected = data.get("selected_candidate")
        if isinstance(selected, dict):
            candidates.append(selected)
        candidates.extend((data.get("strategic_candidates") or {}).values())
        candidates.extend(data.get("candidates") or [])
        for candidate in candidates:
            candidate.update(identity.to_dict())
        return ReadModel(identity, data)
    if leaf == "squad" or (leaf == identity.context.to_dict().get("session_id")):
        players = data.get("squad", data.get("players", []))
        valuations = tuple(
            PlayerValuation(
                player["id"], player["purchase_price_tenths"],
                player.get("current_price_tenths"), player.get("selling_price_tenths"),
            )
            for player in players if "purchase_price_tenths" in player
        )
        staged = tuple(
            StagedMove(item["out_id"], item["in_id"], item.get("cost_tenths"), bool(item.get("already_applied")))
            for item in data.get("transfers_staged", [])
        )
        return SquadReadModel(identity, data, valuations, staged)
    if leaf == "lineup":
        def ids(players: list[dict[str, Any]]) -> tuple[int, ...]:
            identifiers = []
            for player in players:
                identifier = player.get("id", player.get("player_id"))
                if not isinstance(identifier, int):
                    raise ValueError("A lineup player requires an integer ID.")
                identifiers.append(identifier)
            return tuple(identifiers)

        return LineupReadModel(
            identity, data, ids(data.get("starters", [])), ids(data.get("bench", [])),
            (data.get("captain") or {}).get("id"), (data.get("vice_captain") or {}).get("id"),
        )
    if leaf == "plan":
        return PlanReadModel(identity, data, tuple((data.get("best_plan") or data).get("steps", [])))
    if leaf == "decisions":
        return DecisionReadModel(identity, data, tuple(data.get("decisions", [])))
    if leaf == "chips":
        return ChipReadModel(
            identity, data, tuple(data.get("available_chips", data.get("chips_remaining", []))),
            tuple(data.get("recommended_schedule", [])),
        )
    return ReadModel(identity, data)
