"""Explicit, framework-independent command identities."""

import json
from dataclasses import dataclass
from typing import Any


def _validate(identifier: str, season: str, gameweek: int) -> None:
    if (
        not isinstance(identifier, str)
        or not identifier.strip()
        or identifier != identifier.strip()
        or identifier in {".", ".."}
        or any(character in identifier for character in "/\\:\0")
    ):
        raise ValueError("A context ID must be nonempty and cannot contain a path.")
    if not isinstance(season, str) or not season.strip() or season != season.strip():
        raise ValueError("An explicit, nonempty season is required.")
    if isinstance(gameweek, bool) or not isinstance(gameweek, int) or gameweek < 0:
        raise ValueError("gameweek must be a nonnegative integer.")


@dataclass(frozen=True)
class LiveContext:
    team_id: str
    season: str
    gameweek: int

    def __post_init__(self) -> None:
        _validate(self.team_id, self.season, self.gameweek)

    @property
    def key(self) -> str:
        return json.dumps(["live", self.team_id, self.season], separators=(",", ":"))

    def to_dict(self) -> dict[str, Any]:
        return {"mode": "live", "team_id": self.team_id, "season": self.season, "gameweek": self.gameweek}


@dataclass(frozen=True)
class HistoricalContext:
    session_id: str
    season: str
    gameweek: int

    def __post_init__(self) -> None:
        _validate(self.session_id, self.season, self.gameweek)

    @property
    def key(self) -> str:
        return json.dumps(["historical", self.session_id, self.season], separators=(",", ":"))

    def to_dict(self) -> dict[str, Any]:
        return {"mode": "historical", "session_id": self.session_id, "season": self.season, "gameweek": self.gameweek}


CommandContext = LiveContext | HistoricalContext
