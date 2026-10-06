"""Unit tests for historical standings and point-in-time fixture service (V1.4)."""

import pytest

from src.fpl_manager.historical.standings import (
    compute_historical_standings,
    get_historical_matchday_overview,
    get_historical_past_results,
    get_historical_upcoming_fixtures,
)


def test_standings_gw1_initial_state() -> None:
    """At GW1, before any games are played, all teams must have 0 played and 0 points."""
    standings = compute_historical_standings("2023-24", up_to_gw=1)
    assert len(standings) == 20
    for s in standings:
        assert s.played == 0
        assert s.won == 0
        assert s.drawn == 0
        assert s.lost == 0
        assert s.goals_for == 0
        assert s.goals_against == 0
        assert s.goal_difference == 0
        assert s.points == 0
        assert s.form == ()


def test_standings_mid_season_progression() -> None:
    """At GW10, standings should accurately reflect completed match results strictly up to GW9."""
    standings = compute_historical_standings("2023-24", up_to_gw=10)
    assert len(standings) == 20

    # Spurs and Arsenal were top 2 at GW10 in 2023-24
    top_team = standings[0]
    assert top_team.played == 9
    assert top_team.points >= 20
    assert len(top_team.form) == 5

    # Check sorting order: Points desc, GD desc, GF desc
    for i in range(len(standings) - 1):
        curr_t = standings[i]
        next_t = standings[i + 1]
        if curr_t.points == next_t.points:
            if curr_t.goal_difference == next_t.goal_difference:
                assert curr_t.goals_for >= next_t.goals_for
            else:
                assert curr_t.goal_difference >= next_t.goal_difference
        else:
            assert curr_t.points > next_t.points


def test_past_results_zero_future_leakage() -> None:
    """Past results must strictly contain matches before the target gameweek with valid scores."""
    past = get_historical_past_results("2023-24", up_to_gw=5)
    assert len(past) > 0
    for match in past:
        assert match.event < 5
        assert match.team_h_score is not None
        assert match.team_a_score is not None
        assert match.finished is True


def test_upcoming_fixtures_strict_zero_spoilers() -> None:
    """Upcoming fixtures must NEVER expose match scores, finished status, or future outcomes."""
    upcoming = get_historical_upcoming_fixtures("2023-24", target_gw=5, horizon=1)
    assert len(upcoming) == 10
    for fix in upcoming:
        assert fix.event == 5
        assert not hasattr(fix, "team_h_score") or getattr(fix, "team_h_score", None) is None
        assert not hasattr(fix, "team_a_score") or getattr(fix, "team_a_score", None) is None
        assert not hasattr(fix, "finished")
        assert 1 <= fix.team_h_difficulty <= 5
        assert 1 <= fix.team_a_difficulty <= 5


def test_matchday_overview_payload_contract() -> None:
    """Contract test for get_historical_matchday_overview."""
    overview = get_historical_matchday_overview("2023-24", gameweek=6)
    assert overview["season"] == "2023-24"
    assert overview["gameweek"] == 6
    assert len(overview["standings"]) == 20
    assert len(overview["past_results"]) > 0
    assert len(overview["upcoming_fixtures"]) == 10

    # Verify serialized dictionaries
    top_s = overview["standings"][0]
    assert "position" in top_s
    assert "points" in top_s
    assert "form" in top_s
    assert isinstance(top_s["form"], list)

    sample_u = overview["upcoming_fixtures"][0]
    assert "team_h_name" in sample_u
    assert "team_h_difficulty" in sample_u
    assert "team_h_score" not in sample_u
    assert "team_a_score" not in sample_u
