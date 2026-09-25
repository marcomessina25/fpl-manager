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


@dataclass(frozen=True, slots=True)
class PlayerEligibilityStatus:
    player_id: int
    is_in_premier_league: bool
    status_code: str
    news: str
    dead_capital_penalty: float


DEPARTURE_KEYWORDS: tuple[str, ...] = (
    "transferred to",
    "transferred permanently",
    "permanent transfer",
    "permanent deal",
    "joined ",
    "loaned to",
    "season-long loan",
    "loan move",
    "left the club",
    "contract terminated",
    "moved to",
    "released",
    "retired",
    "sold to",
)


def is_departed_from_premier_league(player: object, snapshot: object = None) -> bool:
    """Determine whether a player has permanently or seasonally departed the Premier League.

    Point-in-time criteria:
    1. Official FPL status == 'u' (unavailable due to leaving the league / club).
    2. Player has 0% chance of playing (this round or next round) combined with explicit
       transfer, loan, or departure news.
    3. If snapshot is provided and season is active:
       - The player's club has 0 remaining scheduled fixtures or is not active.
    """
    # 1. Status 'u'
    status = getattr(player, "status", None)
    if status == "u":
        return True

    # 2. News + 0% chance of playing or definitive departure phrasing
    news = (getattr(player, "news", None) or "").lower()
    chance_this = getattr(player, "chance_of_playing_this_round", None)
    chance_next = getattr(player, "chance_of_playing_next_round", None)

    has_departure_news = any(kw in news for kw in DEPARTURE_KEYWORDS)
    is_zero_chance = (chance_this == 0 or chance_next == 0)

    if has_departure_news and (
        is_zero_chance
        or "transferred" in news
        or "permanent" in news
        or "sold to" in news
        or "left the club" in news
        or "contract terminated" in news
    ):
        return True

    # 3. Snapshot verification if available
    if snapshot is not None:
        team_id = getattr(player, "team_id", None)
        if team_id is not None:
            teams = getattr(snapshot, "teams", None)
            if teams:
                team_ids = {
                    t["team_id"] if isinstance(t, dict) else getattr(t, "team_id", None)
                    for t in teams
                }
                if team_id not in team_ids:
                    return True
            fixtures = getattr(snapshot, "fixtures", None)
            current_gw = getattr(snapshot, "gameweek", None)
            if fixtures and current_gw is not None and current_gw < 38:
                rem_fixtures = [
                    f
                    for f in fixtures
                    if (getattr(f, "team_h", None) == team_id or getattr(f, "team_a", None) == team_id)
                    and not getattr(f, "finished", False)
                ]
                if len(rem_fixtures) == 0:
                    return True

    return False


def get_player_eligibility_status(
    player: object,
    snapshot: object = None,
    dead_capital_weight: float = 3.0,
) -> PlayerEligibilityStatus:
    """Assess eligibility and calculate dead capital penalty for transfer prioritization."""
    departed = is_departed_from_premier_league(player, snapshot=snapshot)
    price_tenths = getattr(player, "price_tenths", 50)
    penalty = (dead_capital_weight * (price_tenths / 10.0)) if departed else 0.0
    return PlayerEligibilityStatus(
        player_id=getattr(player, "id", getattr(player, "player_id", 0)),
        is_in_premier_league=not departed,
        status_code=getattr(player, "status", "a"),
        news=getattr(player, "news", "") or "",
        dead_capital_penalty=penalty,
    )


