"""Tests for the expected points baseline projection model."""

import json
from pathlib import Path
import pytest

from fpl_manager.expected_points import (
    availability_multiplier,
    calculate_base_xp,
    calculate_fixture_xp,
    fdr_multiplier,
    project_gameweek,
    venue_multiplier,
)
from fpl_manager.models import Position
from fpl_manager.storage import SnapshotStore, utc_timestamp


def test_calculate_base_xp() -> None:
    # £4.0m budget prior
    assert calculate_base_xp(price_tenths=40, total_points=0, finished_matches=0) == 1.50
    # £10.0m premium prior: 1.5 + (10 - 4)*0.65 = 5.40
    assert calculate_base_xp(price_tenths=100, total_points=0, finished_matches=0) == 5.40

    # With match data: e.g. 5 finished matches, 40 points -> observed PPG = 8.0
    # weight = 5/10 = 0.50. base = 0.5 * 8.0 + 0.5 * 5.40 = 6.70
    blended = calculate_base_xp(price_tenths=100, total_points=40, finished_matches=5)
    assert blended == 6.70


def test_availability_multiplier() -> None:
    assert availability_multiplier("a") == 1.0
    assert availability_multiplier("A") == 1.0
    assert availability_multiplier("d") == 0.75
    assert availability_multiplier("i") == 0.0
    assert availability_multiplier("s") == 0.0
    assert availability_multiplier("u") == 0.0
    assert availability_multiplier("unknown") == 0.0


def test_fdr_multiplier() -> None:
    # GKP / DEF are more sensitive
    assert fdr_multiplier(Position.DEFENDER, 2) == 1.15
    assert fdr_multiplier(Position.DEFENDER, 3) == 1.00
    assert fdr_multiplier(Position.DEFENDER, 4) == 0.85

    # MID / FWD are moderately sensitive
    assert fdr_multiplier(Position.FORWARD, 2) == 1.10
    assert fdr_multiplier(Position.FORWARD, 3) == 1.00
    assert fdr_multiplier(Position.FORWARD, 4) == 0.90


def test_venue_multiplier() -> None:
    assert venue_multiplier(is_home=True) == 1.06
    assert venue_multiplier(is_home=False) == 0.94


def test_calculate_fixture_xp() -> None:
    # Injured player yields 0 xP
    assert calculate_fixture_xp(base_xp=5.0, avail_mult=0.0, position=Position.MIDFIELDER, fdr=2, is_home=True) == 0.0

    # Available player
    xp = calculate_fixture_xp(base_xp=5.0, avail_mult=1.0, position=Position.MIDFIELDER, fdr=3, is_home=True)
    assert xp == round(5.0 * 1.0 * 1.0 * 1.06, 2)


@pytest.fixture
def xp_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "fpl.sqlite3"
    store = SnapshotStore(db_path)

    bootstrap = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Chelsea", "short_name": "CHE"},
        ],
        "elements": [
            {"id": 10, "web_name": "Saka", "team": 1, "element_type": 3, "now_cost": 100, "status": "a", "total_points": 20},
            {"id": 20, "web_name": "Palmer", "team": 2, "element_type": 3, "now_cost": 105, "status": "d", "total_points": 15},
        ],
    }

    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 4, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 2, "team_a": 1, "team_h_difficulty": 4, "team_a_difficulty": 3, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())
    return db_path


def test_project_gameweek(xp_db: Path) -> None:
    projections = project_gameweek(gameweek=2, database_path=xp_db)
    assert len(projections) == 2

    by_name = {p.web_name: p for p in projections}
    saka = by_name["Saka"]
    palmer = by_name["Palmer"]

    assert saka.availability_pct == 100.0
    assert palmer.availability_pct == 75.0
    assert len(saka.fixtures) == 1
    assert saka.fixtures[0].opponent_short == "CHE"
    assert saka.fixtures[0].venue == "A"
    assert saka.expected_points > 0.0
    assert saka.expected_minutes > 0.0
    assert saka.start_probability > 0.0
    assert saka.xp_ceiling >= saka.expected_points
    assert saka.xp_floor <= saka.expected_points


def test_calculate_availability() -> None:
    from fpl_manager.expected_points import calculate_availability
    assert calculate_availability("a", None) == 1.0
    assert calculate_availability("d", None) == 0.75
    assert calculate_availability("i", None) == 0.0
    # Explicit percentage takes priority
    assert calculate_availability("d", 50) == 0.50
    assert calculate_availability("d", 25) == 0.25
    assert calculate_availability("a", 100) == 1.00
    assert calculate_availability("a", 0) == 0.00


def test_calculate_expected_minutes() -> None:
    from fpl_manager.expected_points import calculate_expected_minutes
    # Fit starter: 2 starts in 2 finished matches
    xm, p_start, prob_60, prob_sub = calculate_expected_minutes(
        status="a",
        chance_of_playing_next_round=None,
        starts=2,
        minutes=180,
        finished_matches=2,
        price_tenths=150,
        position=Position.FORWARD,
    )
    assert xm > 75.0
    assert p_start > 0.90
    assert prob_60 > 0.85

    # Injured player
    xm_inj, p_start_inj, prob_60_inj, _ = calculate_expected_minutes(
        status="i",
        chance_of_playing_next_round=0,
        starts=2,
        minutes=180,
        finished_matches=2,
        price_tenths=150,
        position=Position.FORWARD,
    )
    assert xm_inj == 0.0
    assert p_start_inj == 0.0
    assert prob_60_inj == 0.0

    # Doubtful (50% chance)
    xm_dbt, p_start_dbt, _, _ = calculate_expected_minutes(
        status="d",
        chance_of_playing_next_round=50,
        starts=2,
        minutes=180,
        finished_matches=2,
        price_tenths=150,
        position=Position.FORWARD,
    )
    assert xm_dbt < xm
    assert round(p_start_dbt * 2, 2) == round(p_start, 2)


def test_calculate_component_xp() -> None:
    from fpl_manager.expected_points import calculate_component_xp
    # Attacking forward at home vs FDR 2
    comp_fwd = calculate_component_xp(
        position=Position.FORWARD,
        price_tenths=150,
        fdr=2,
        is_home=True,
        expected_minutes=85.0,
        prob_60_plus=0.90,
        prob_sub=0.05,
        expected_goals_per_90=0.75,
        expected_assists_per_90=0.20,
        finished_matches=2,
    )
    assert comp_fwd["app"] > 1.8
    assert comp_fwd["att"] > 2.0
    assert comp_fwd["total"] > 5.0
    assert comp_fwd["ceil"] > comp_fwd["total"]
    assert comp_fwd["floor"] <= comp_fwd["total"]
    assert comp_fwd["sigma"] > 0.0

    # Zero minutes yields zero points
    comp_zero = calculate_component_xp(
        position=Position.MIDFIELDER,
        price_tenths=70,
        fdr=3,
        is_home=True,
        expected_minutes=0.0,
        prob_60_plus=0.0,
        prob_sub=0.0,
    )
    assert comp_zero["total"] == 0.0
    assert comp_zero["floor"] == 0.0
    assert comp_zero["ceil"] == 0.0


def test_project_multi_gameweek_profiles(xp_db: Path) -> None:
    from fpl_manager.expected_points import project_multi_gameweek_profiles
    profiles = project_multi_gameweek_profiles(gameweeks=[2], database_path=xp_db)
    assert len(profiles) == 2
    saka_prof = [p for p in profiles.values() if p.web_name == "Saka"][0]
    assert saka_prof.expected_points > 0.0
    assert saka_prof.expected_minutes > 0.0
    assert saka_prof.xp_ceiling >= saka_prof.expected_points
    assert saka_prof.xp_floor <= saka_prof.expected_points
    assert saka_prof.fixtures_count == 1

