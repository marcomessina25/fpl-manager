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
    status: str = "a"
    total_points: int = 0
    minutes: int = 0
    starts: int = 0
    chance_of_playing_next_round: int | None = None
    chance_of_playing_this_round: int | None = None
    expected_goals: float = 0.0
    expected_assists: float = 0.0
    expected_goal_involvements: float = 0.0
    expected_goals_conceded: float = 0.0
    expected_goals_per_90: float = 0.0
    expected_assists_per_90: float = 0.0
    expected_goals_conceded_per_90: float = 0.0
    clean_sheets_per_90: float = 0.0
    bps: int = 0
    ict_index: float = 0.0
    form: float = 0.0
    points_per_game: float = 0.0
    selected_by_percent: float = 0.0
    news: str = ""

