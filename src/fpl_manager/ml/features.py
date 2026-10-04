"""Feature extraction pipeline for Gradient Boosting models in FPL Manager (V1.3).

Ensures strict zero-future-leakage temporal discipline:
Extracts tabular feature vectors from point-in-time HistoricalPlayerState and HistoricalFixture.
"""

from typing import Any

from ..historical.models import HistoricalFixture, HistoricalPlayerState, Position

FEATURE_NAMES = [
    "position_code",
    "price_tenths",
    "status_is_a",
    "status_is_d",
    "chance_of_playing",
    "season_starts_ratio",
    "season_mins_ratio",
    "starts_last_3_ratio",
    "starts_last_5_ratio",
    "minutes_last_3_ratio",
    "minutes_last_5_ratio",
    "consecutive_zero_mins",
    "days_since_prev_fixture",
    "matches_last_7_days",
    "matches_last_14_days",
    "fdr",
    "is_home",
    "opponent_strength",
    "team_strength",
    "expected_goals_per_90",
    "expected_assists_per_90",
    "expected_goals_conceded_per_90",
    "form",
    "points_per_game",
    "selected_by_percent",
]


def build_feature_vector(
    position: Position,
    price_tenths: int,
    status: str,
    chance_of_playing_next_round: int | None = None,
    starts: int = 0,
    minutes: int = 0,
    starts_last_3: int = 0,
    starts_last_5: int = 0,
    minutes_last_3: int = 0,
    minutes_last_5: int = 0,
    consecutive_zero_mins: int = 0,
    finished_matches: int = 0,
    days_since_prev_fixture: float | None = None,
    matches_last_7_days: int = 0,
    matches_last_14_days: int = 0,
    fdr: int = 3,
    is_home: bool = True,
    opp_strength: int = 3,
    team_strength: int = 3,
    expected_goals_per_90: float = 0.0,
    expected_assists_per_90: float = 0.0,
    expected_goals_conceded_per_90: float = 0.0,
    form: float = 0.0,
    points_per_game: float = 0.0,
    selected_by_percent: float = 0.0,
) -> list[float]:
    """Build standardized 25-feature vector from raw scalar arguments."""
    chance_val = 1.0
    status_lower = status.lower()
    if chance_of_playing_next_round is not None:
        chance_val = float(chance_of_playing_next_round) / 100.0
    elif status_lower == "d":
        chance_val = 0.50
    elif status_lower in ("i", "s", "u"):
        chance_val = 0.0

    finished = max(1, finished_matches)
    pos_val = float(position.value if hasattr(position, "value") else int(position))
    days_prev = days_since_prev_fixture if days_since_prev_fixture is not None else -1.0

    return [
        pos_val,
        float(price_tenths),
        1.0 if status_lower == "a" else 0.0,
        1.0 if status_lower == "d" else 0.0,
        chance_val,
        float(starts) / float(finished),
        float(minutes) / (90.0 * float(finished)),
        float(starts_last_3) / 3.0,
        float(starts_last_5) / 5.0,
        float(minutes_last_3) / 270.0,
        float(minutes_last_5) / 450.0,
        min(5.0, float(consecutive_zero_mins)),
        days_prev,
        float(matches_last_7_days),
        float(matches_last_14_days),
        float(fdr),
        1.0 if is_home else 0.0,
        float(opp_strength),
        float(team_strength),
        float(expected_goals_per_90),
        float(expected_assists_per_90),
        float(expected_goals_conceded_per_90),
        float(form),
        float(points_per_game),
        float(selected_by_percent),
    ]


def extract_player_feature_vector(
    player: HistoricalPlayerState,
    fixture: HistoricalFixture | None,
    finished_gameweeks: int,
    teams_map: dict[int, dict[str, Any]] | None = None,
) -> list[float]:
    """Extract a 25-dimensional feature vector for a player before a gameweek deadline."""
    fdr = 3
    is_home = True
    opp_strength = 3
    days_prev = None
    m7 = 0
    m14 = 0

    if fixture is not None:
        if player.team_id == fixture.team_h:
            fdr = fixture.team_h_difficulty
            is_home = True
            opp_id = fixture.team_a
            days_prev = fixture.days_since_prev_h
            m7 = fixture.matches_7d_h
            m14 = fixture.matches_14d_h
        else:
            fdr = fixture.team_a_difficulty
            is_home = False
            opp_id = fixture.team_h
            days_prev = fixture.days_since_prev_a
            m7 = fixture.matches_7d_a
            m14 = fixture.matches_14d_a

        if teams_map and opp_id in teams_map:
            opp_strength = teams_map[opp_id].get("strength", 3)

    team_strength = 3
    if teams_map and player.team_id in teams_map:
        team_strength = teams_map[player.team_id].get("strength", 3)

    return build_feature_vector(
        position=player.position,
        price_tenths=player.price_tenths,
        status=player.status,
        chance_of_playing_next_round=player.chance_of_playing_next_round,
        starts=player.starts,
        minutes=player.minutes,
        starts_last_3=player.starts_last_3,
        starts_last_5=player.starts_last_5,
        minutes_last_3=player.minutes_last_3,
        minutes_last_5=player.minutes_last_5,
        consecutive_zero_mins=player.consecutive_zero_mins,
        finished_matches=finished_gameweeks,
        days_since_prev_fixture=days_prev,
        matches_last_7_days=m7,
        matches_last_14_days=m14,
        fdr=fdr,
        is_home=is_home,
        opp_strength=opp_strength,
        team_strength=team_strength,
        expected_goals_per_90=player.expected_goals_per_90,
        expected_assists_per_90=player.expected_assists_per_90,
        expected_goals_conceded_per_90=player.expected_goals_conceded_per_90,
        form=player.form,
        points_per_game=player.points_per_game,
        selected_by_percent=player.selected_by_percent,
    )
