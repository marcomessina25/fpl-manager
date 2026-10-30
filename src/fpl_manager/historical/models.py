"""Historical decision views and immutable fixture-level outcome provenance."""

from dataclasses import dataclass
from typing import Any

from ..models import Position


@dataclass(frozen=True, slots=True)
class HistoricalPlayerState:
    """Archived player attributes and strictly prior performance in a deadline view.

    Announcement-time evidence for archived price/status/ownership is assessed
    separately; a normalized matchday row alone does not establish that evidence.
    """
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
    starts_last_3: int = 0
    starts_last_5: int = 0
    minutes_last_3: int = 0
    minutes_last_5: int = 0
    consecutive_zero_mins: int = 0
    recent_starts: tuple[int, ...] = ()
    recent_minutes: tuple[int, ...] = ()
    is_long_term_unavailable: bool = False


@dataclass(frozen=True, slots=True)
class HistoricalFixture:
    """Score-masked fixture view; historical announcement timing is not verified."""
    fixture_id: int
    event: int
    team_h: int
    team_a: int
    team_h_difficulty: int
    team_a_difficulty: int
    kickoff_time: str | None
    days_since_prev_h: float | None = None
    days_since_prev_a: float | None = None
    matches_7d_h: int = 0
    matches_7d_a: int = 0
    matches_14d_h: int = 0
    matches_14d_a: int = 0
    finished: bool = False



@dataclass(frozen=True, slots=True)
class HistoricalGameweekSnapshot:
    """Immutable decision view whose source as-of evidence is assessed separately."""
    season: str
    gameweek: int
    deadline_time: str
    finished_gameweeks: int
    players: tuple[HistoricalPlayerState, ...]
    teams: tuple[dict[str, Any], ...]
    fixtures: tuple[HistoricalFixture, ...]


@dataclass(frozen=True, slots=True)
class FixtureOutcome:
    """One revealed fixture row, retaining identity rather than a fictitious GW opponent.

    ``identity_source`` is ``record`` for an explicit source fixture ID,
    ``fixture_schedule`` for a unique schedule match, or ``unidentified`` for a
    compatible old single-row record. ``source_file`` identifies the outcome asset.
    """
    fixture_id: int | None
    minutes: int
    total_points: int
    starts: int = 0
    goals_scored: int = 0
    assists: int = 0
    clean_sheets: int = 0
    goals_conceded: int = 0
    bonus: int = 0
    bps: int = 0
    was_home: bool | None = None
    opponent_team_id: int | None = None
    team_id: int | None = None
    kickoff_time: str | None = None
    identity_source: str = "unidentified"
    source_file: str | None = None


@dataclass(frozen=True, slots=True)
class GameweekOutcome:
    """Revealed ground truth for a player in a completed gameweek.

    MUST NEVER be accessed before or during gameweek decision making.

    Corrected execution sums counting statistics across every fixture. The legacy
    scalar ``was_home`` / ``opponent_team_id`` fields describe only a single-fixture
    outcome; both are ``None`` for multiple fixtures, even if both were at home.
    ``fixture_outcomes`` retains each fixture's identity, statistics and provenance.
    Explicit legacy execution preserves the original last-row scalar semantics.
    """
    season: str
    gameweek: int
    player_id: int
    minutes: int
    total_points: int
    starts: int = 0
    goals_scored: int = 0
    assists: int = 0
    clean_sheets: int = 0
    goals_conceded: int = 0
    bonus: int = 0
    bps: int = 0
    was_home: bool | None = True
    opponent_team_id: int | None = 0
    fixture_outcomes: tuple[FixtureOutcome, ...] = ()


@dataclass(frozen=True, slots=True)
class SeasonManifest:
    """Metadata describing an ingested historical season."""
    season: str
    total_gameweeks: int
    num_players: int
    num_teams: int
    num_fixtures: int
    deadlines: dict[int, str]
