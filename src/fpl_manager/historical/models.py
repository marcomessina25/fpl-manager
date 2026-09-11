"""Historical domain models ensuring point-in-time integrity for V0.7."""

from dataclasses import dataclass
from typing import Any

from ..models import Position


@dataclass(frozen=True, slots=True)
class HistoricalPlayerState:
    """Player state strictly knowable before Gameweek deadline."""
    player_id: int
    web_name: str
    position: Position
    team_id: int
    price_tenths: int
    status: str
    chance_of_playing_next_round: int | None
    chance_of_playing_this_round: int | None
    total_points: int            # Cumulative prior to deadline
    minutes: int                 # Cumulative prior to deadline
    starts: int                  # Cumulative prior to deadline
    expected_goals: float        # Cumulative prior to deadline
    expected_assists: float      # Cumulative prior to deadline
    expected_goal_involvements: float
    expected_goals_conceded: float
    expected_goals_per_90: float
    expected_assists_per_90: float
    expected_goals_conceded_per_90: float
    clean_sheets_per_90: float
    bps: int
    ict_index: float
    form: float
    points_per_game: float
    selected_by_percent: float
    news: str


@dataclass(frozen=True, slots=True)
class HistoricalFixture:
    """Fixture representation as known at the decision deadline."""
    fixture_id: int
    event: int
    team_h: int
    team_a: int
    team_h_difficulty: int
    team_a_difficulty: int
    kickoff_time: str | None


@dataclass(frozen=True, slots=True)
class HistoricalGameweekSnapshot:
    """Complete immutable point-in-time data snapshot for a specific gameweek."""
    season: str
    gameweek: int
    deadline_time: str
    finished_gameweeks: int
    players: tuple[HistoricalPlayerState, ...]
    teams: tuple[dict[str, Any], ...]
    fixtures: tuple[HistoricalFixture, ...]


@dataclass(frozen=True, slots=True)
class GameweekOutcome:
    """Revealed ground truth for a player in a completed gameweek.
    
    MUST NEVER be accessed before or during gameweek decision making.
    """
    season: str
    gameweek: int
    player_id: int
    minutes: int
    total_points: int
    goals_scored: int = 0
    assists: int = 0
    clean_sheets: int = 0
    goals_conceded: int = 0
    bonus: int = 0
    bps: int = 0
    was_home: bool = True
    opponent_team_id: int = 0


@dataclass(frozen=True, slots=True)
class SeasonManifest:
    """Metadata describing an ingested historical season."""
    season: str
    total_gameweeks: int
    num_players: int
    num_teams: int
    num_fixtures: int
    deadlines: dict[int, str]
