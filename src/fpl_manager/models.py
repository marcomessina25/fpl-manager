"""Small domain models independent of the FPL API transport format."""

from dataclasses import dataclass
from enum import IntEnum


class Position(IntEnum):
    GOALKEEPER = 1
    DEFENDER = 2
    MIDFIELDER = 3
    FORWARD = 4


@dataclass(frozen=True, slots=True)
class Player:
    id: int
    name: str
    position: Position
    team_id: int
    price_tenths: int
