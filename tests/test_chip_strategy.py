"""Tests for Chip Strategy and Blank/Double Gameweek planner engine."""

import json
from pathlib import Path
import pytest

from fpl_manager.chip_strategy import (
    analyze_fixture_calendar,
    evaluate_chip_candidates,
    recommend_chip_strategy,
)
from fpl_manager.cli import format_chip_strategy_concise
from fpl_manager.storage import SnapshotStore, utc_timestamp


@pytest.fixture
def chip_planner_env(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "fpl.sqlite3"
    squad_path = tmp_path / "current_squad.json"

    store = SnapshotStore(db_path)
    store.initialize()

    bootstrap = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Liverpool", "short_name": "LIV"},
            {"id": 3, "name": "Manchester City", "short_name": "MCI"},
            {"id": 4, "name": "Chelsea", "short_name": "CHE"},
            {"id": 5, "name": "Tottenham", "short_name": "TOT"},
        ],
        "elements": [],
    }

    # 15 players in squad:
    # 2 GKP, 5 DEF, 5 MID, 3 FWD
    for p_id in range(1, 16):
        pos_id = 1 if p_id <= 2 else (2 if p_id <= 7 else (3 if p_id <= 12 else 4))
        bootstrap["elements"].append({
            "id": p_id,
            "web_name": f"Player_{p_id}",
            "team": ((p_id - 1) % 5) + 1,
            "element_type": pos_id,
            "now_cost": 120 if p_id == 13 else 55,
            "status": "a",
            "total_points": 45 if p_id == 13 else 25,
            "selected_by_percent": "60.0" if p_id == 13 else "10.0",
        })

    # Create fixtures with distinct calendar characteristics:
    # GW2: Standard GW (all teams play once)
    # GW3: Double Gameweek (Team 3 plays twice: against 1 and 2; Team 4 has 0 fixtures -> BGW + DGW!)
    # GW4: Blank Gameweek (Team 5 has 0 fixtures, others play once)
    # GW5: Standard GW
    fixtures = [
        # GW1
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
        # GW2 (Standard)
        {"id": 2, "event": 2, "team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 3, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 3, "event": 2, "team_h": 3, "team_a": 4, "team_h_difficulty": 2, "team_a_difficulty": 4, "kickoff_time": "2026-08-27T17:30:00Z", "finished": False},
        # GW3 (DGW for Team 3; BGW for Team 4)
        {"id": 4, "event": 3, "team_h": 3, "team_a": 1, "team_h_difficulty": 2, "team_a_difficulty": 4, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 5, "event": 3, "team_h": 3, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 4, "kickoff_time": "2026-09-05T15:00:00Z", "finished": False},
        {"id": 6, "event": 3, "team_h": 5, "team_a": 1, "team_h_difficulty": 2, "team_a_difficulty": 3, "kickoff_time": "2026-09-03T17:30:00Z", "finished": False},
        # GW4 (BGW: Team 5 has 0 matches)
        {"id": 7, "event": 4, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-09-10T15:00:00Z", "finished": False},
        {"id": 8, "event": 4, "team_h": 3, "team_a": 4, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-09-10T17:30:00Z", "finished": False},
        # GW5 (Standard)
        {"id": 9, "event": 5, "team_h": 1, "team_a": 3, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-09-17T15:00:00Z", "finished": False},
        {"id": 10, "event": 5, "team_h": 2, "team_a": 4, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-09-17T17:30:00Z", "finished": False},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    squad_data = {
        "season": "2026/27",
        "free_transfers": 1,
        "bank_tenths": 15,
        "player_ids": list(range(1, 16)),
        "purchase_prices_tenths": {str(i): 50 for i in range(1, 16)},
    }
    squad_path.write_text(json.dumps(squad_data, indent=2), encoding="utf-8")

    return db_path, squad_path


def test_analyze_fixture_calendar(chip_planner_env: tuple[Path, Path]) -> None:
    db_path, squad_path = chip_planner_env

    res = analyze_fixture_calendar(start_gw=2, end_gw=5, squad_path=squad_path, database_path=db_path)

    assert res["has_confirmed_blank_gameweeks"] is True
    assert res["has_confirmed_double_gameweeks"] is True
    assert len(res["calendar"]) == 4

    gws_by_num = {item["gameweek"]: item for item in res["calendar"]}

    # GW3 should detect doubling Team 3 and blanking Team 4
    gw3 = gws_by_num[3]
    assert gw3["gw_type"] == "BLANK_AND_DOUBLE"
    assert any(t["short_name"] == "MCI" for t in gw3["doubling_teams"])
    assert any(t["short_name"] == "CHE" for t in gw3["blanking_teams"])
    assert gw3["squad_double_count"] > 0
    assert gw3["squad_blank_count"] > 0

    # GW4 should detect blanking Team 5
    gw4 = gws_by_num[4]
    assert gw4["gw_type"] == "BLANK"
    assert any(t["short_name"] == "TOT" for t in gw4["blanking_teams"])
    assert gw4["squad_blank_count"] > 0


def test_evaluate_chip_candidates(chip_planner_env: tuple[Path, Path]) -> None:
    db_path, squad_path = chip_planner_env

    candidates = evaluate_chip_candidates(start_gw=2, end_gw=5, squad_path=squad_path, database_path=db_path)

    assert "triplecaptain" in candidates
    assert "freehit" in candidates
    assert "benchboost" in candidates
    assert "wildcard" in candidates

    # Triple Captain candidate for DGW3 should have high rating
    top_tc = candidates["triplecaptain"][0]
    assert top_tc["gameweek"] == 3
    assert top_tc["gw_type"] == "BLANK_AND_DOUBLE"

    # Free Hit should prioritize gameweeks with high blanking players (GW3 or GW4)
    top_fh = candidates["freehit"][0]
    assert top_fh["squad_blanks"] > 0


def test_recommend_chip_strategy(chip_planner_env: tuple[Path, Path], tmp_path: Path) -> None:
    db_path, squad_path = chip_planner_env
    rep_path = tmp_path / "chip_plan.json"

    res = recommend_chip_strategy(
        squad_path=squad_path,
        database_path=db_path,
        start_gw=2,
        end_gw=5,
        report_path=rep_path,
    )

    assert len(res["available_chips"]) == 4
    assert len(res["recommended_schedule"]) > 0

    # Verify no two chips are assigned to the exact same gameweek
    assigned_gws = [rec["gameweek"] for rec in res["recommended_schedule"]]
    assert len(assigned_gws) == len(set(assigned_gws))

    assert rep_path.exists()


def test_recommend_chip_strategy_with_used_chips(chip_planner_env: tuple[Path, Path]) -> None:
    db_path, squad_path = chip_planner_env

    res = recommend_chip_strategy(
        squad_path=squad_path,
        database_path=db_path,
        start_gw=2,
        end_gw=5,
        used_chips=["wildcard", "freehit"],
    )

    assert "wildcard" not in res["available_chips"]
    assert "freehit" not in res["available_chips"]
    assert set(res["available_chips"]) == {"benchboost", "triplecaptain"}

    scheduled_chips = [rec["chip"] for rec in res["recommended_schedule"]]
    assert "wildcard" not in scheduled_chips
    assert "freehit" not in scheduled_chips


def test_format_chip_strategy_concise(chip_planner_env: tuple[Path, Path]) -> None:
    db_path, squad_path = chip_planner_env

    res = recommend_chip_strategy(
        squad_path=squad_path,
        database_path=db_path,
        start_gw=2,
        end_gw=5,
    )

    concise = format_chip_strategy_concise(res)
    assert "Chip Strategy & BGW/DGW Roadmap" in concise
    assert "Available Chips:" in concise
    assert "Recommended Deployment Schedule:" in concise
    assert "Top Candidate Gameweeks by Chip:" in concise
