"""Small domain models independent of the FPL API transport format."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
import re
from typing import Any


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
    is_long_term_unavailable: bool = False


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

LONG_TERM_INJURY_KEYWORDS: tuple[str, ...] = (
    "acl",
    "anterior cruciate ligament",
    "cruciate ligament",
    "ruptured ligament",
    "season-ending",
    "out for the season",
    "out for season",
    "indefinitely",
)

_MONTH_NAMES: dict[str, int] = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# Matches FPL-style return-date phrasing: "Suspended until 17 Jan", "Expected back 17 Jan",
# "until 17 January 2024". Captures (day, month name, optional year).
_RETURN_DATE_RE = re.compile(
    r"(?:suspended\s+until|expected\s+(?:to\s+)?(?:be\s+)?back|out\s+until|until|back)"
    r"\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?(?:\s+(\d{4}))?",
    re.IGNORECASE,
)

# Matches disciplinary ban duration phrasing such as "8-month" or "10 months".
_MONTHS_BAN_RE = re.compile(r"\d+[\s-]*months?", re.IGNORECASE)


def _parse_return_date(news_lower: str, reference: datetime) -> datetime | None:
    """Extract a point-in-time expected return date from FPL news text, if present."""
    match = _RETURN_DATE_RE.search(news_lower)
    if not match:
        return None
    day_str, month_str, year_str = match.groups()
    month = _MONTH_NAMES.get(month_str.lower())
    if month is None:
        return None
    try:
        day = int(day_str)
    except ValueError:
        return None
    if year_str:
        try:
            return datetime(int(year_str), month, day, tzinfo=timezone.utc)
        except ValueError:
            return None
    # No year given: choose the first occurrence of that day/month that is not more
    # than ~30 days before the reference date (roll into next year if needed).
    try:
        candidate = datetime(reference.year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None
    if (reference - candidate).days > 30:
        try:
            candidate = datetime(reference.year + 1, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None
    return candidate


def _reference_datetime(snapshot: object | None) -> datetime:
    """Resolve the point-in-time reference datetime for return-date calculations."""
    if snapshot is not None:
        deadline_str = getattr(snapshot, "deadline_time", None)
        if deadline_str:
            try:
                clean = deadline_str.replace("Z", "+00:00")
                dt = datetime.fromisoformat(clean)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    return datetime.now(timezone.utc)


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

    return False


def evaluate_long_term_unavailable(
    status: str | None,
    news: str | None,
    chance_this: int | None,
    chance_next: int | None,
    reference_dt: datetime,
) -> bool:
    """Point-in-time heuristic verdict for long-term unavailability from raw signals.

    This is the shared core used both by `is_long_term_unavailable`'s fallback path (for raw
    live-API objects with no precomputed verdict) and by `build_historical_snapshot` (to compute
    the verdict once, at snapshot-build time, using the gameweek deadline as `reference_dt`
    instead of wall-clock "now"). Criteria:
    1. Official FPL status == 'u' (unavailable / departed) -> True.
    2. Registry marker: news starting with "Long-term unavailable:" (stamped by
       `build_historical_snapshot` for registry-applied players) -> True regardless of status.
    3. For status 's' (suspended) or 'i' (injured) with zero chance of playing:
       a. If the news contains a parseable expected-return date, long-term iff that date is
          more than 35 days after `reference_dt`.
       b. Else if status == 'i' and the news contains a severe long-term injury keyword
          (ACL, cruciate ligament, out for the season, indefinitely, ...) -> True.
       c. Else if status == 's' and the news indicates a long ban ("indefinitely" or an
          "N-month(s)" phrasing) -> True.
       d. Otherwise False (e.g. a short suspension or a bare "Suspended" with no other signal).
    4. Otherwise False.
    """
    if status == "u":
        return True

    news_lower = (news or "").lower()

    if news_lower.startswith("long-term unavailable:"):
        return True

    if status not in ("s", "i"):
        return False

    is_zero_chance = (
        chance_this == 0
        or chance_next == 0
        or (chance_this is None and chance_next is None)
    )
    if not is_zero_chance:
        return False

    return_date = _parse_return_date(news_lower, reference_dt)
    if return_date is not None:
        return (return_date - reference_dt).days > 35

    if status == "i":
        return any(kw in news_lower for kw in LONG_TERM_INJURY_KEYWORDS)

    # status == "s"
    if "indefinitely" in news_lower:
        return True
    if _MONTHS_BAN_RE.search(news_lower):
        return True
    return False


def is_long_term_unavailable(player: object, snapshot: object = None) -> bool:
    """Determine whether a player is long-term unavailable (expected return > 35 days away).

    Point-in-time criteria:
    0. Precomputed verdict short-circuit: if `player` carries an `is_long_term_unavailable`
       boolean attribute (stamped once, at the correct point in time, by
       `build_historical_snapshot` and carried through every derived object -
       `ExpectedPointsProjection`, `PlayerInfo`, `PlayerOptInfo`), that verdict is authoritative
       and returned immediately. This avoids re-deriving the signal from free-text `news` (which
       is not reliably transported to derived objects) and avoids any wall-clock dependency for
       historical/backtest objects that already have a point-in-time-correct verdict baked in.
    1. Already classified as departed from Premier League, or official FPL status == 'u'.
    2. Registry marker: `build_historical_snapshot` stamps registry-applied players' news with
       a "Long-term unavailable: <reason>" prefix (see historical/snapshots.py); such a marker
       is always treated as long-term regardless of status.
    3. For status 's' (suspended) or 'i' (injured) with zero chance of playing:
       a. If the news contains a parseable expected-return date, long-term iff that date is
          more than 35 days after the point-in-time reference date (the snapshot's deadline
          if available, otherwise "now").
       b. Else if status == 'i' and the news contains a severe long-term injury keyword
          (ACL, cruciate ligament, out for the season, indefinitely, ...) -> True.
       c. Else if status == 's' and the news indicates a long ban ("indefinitely" or an
          "N-month(s)" phrasing) -> True.
       d. Otherwise False (e.g. a short suspension or a bare "Suspended" with no other signal).

    NOTE: criteria 1-3 (the heuristic fallback) are only reached for objects with no precomputed
    verdict (e.g. raw live-API `Player` objects); they are never reached for historical/backtest
    objects once criterion 0 fires.
    """
    flag = getattr(player, "is_long_term_unavailable", None)
    if isinstance(flag, bool):
        return flag

    if is_departed_from_premier_league(player, snapshot=snapshot):
        return True

    status = getattr(player, "status", None)
    news = getattr(player, "news", None) or ""
    chance_this = getattr(player, "chance_of_playing_this_round", None)
    chance_next = getattr(player, "chance_of_playing_next_round", None)
    reference_dt = _reference_datetime(snapshot)
    return evaluate_long_term_unavailable(status, news, chance_this, chance_next, reference_dt)


def get_player_eligibility_status(
    player: object,
    snapshot: object = None,
    dead_capital_weight: float = 3.0,
) -> PlayerEligibilityStatus:
    """Assess eligibility and calculate dead capital penalty for transfer prioritization."""
    departed = is_departed_from_premier_league(player, snapshot=snapshot)
    long_term_unavail = is_long_term_unavailable(player, snapshot=snapshot)
    is_dead = departed or long_term_unavail
    price_tenths = getattr(player, "price_tenths", 50)
    penalty = (dead_capital_weight * (price_tenths / 10.0)) if is_dead else 0.0
    return PlayerEligibilityStatus(
        player_id=getattr(player, "id", getattr(player, "player_id", 0)),
        is_in_premier_league=not departed,
        status_code=getattr(player, "status", "a"),
        news=getattr(player, "news", "") or "",
        dead_capital_penalty=penalty,
        is_long_term_unavailable=long_term_unavail,
    )


