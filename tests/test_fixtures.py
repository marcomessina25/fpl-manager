"""Tests for fixture analysis and FDR calculation module."""

import json
from pathlib import Path
import pytest

from fpl_manager.fixtures import analyze_squad_fixtures, analyze_team_fixtures, get_current_gameweek
from fpl_manager.storage import SnapshotStore, utc_timestamp


@pytest.fixture
def mock_fixture_db(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "fpl.sqlite3"
    squad_path = tmp_path / "current_squad.json"

    store = SnapshotStore(db_path)
    player_ids = [10, 20] + list(range(101, 114))
    elements = [
        {"id": 10, "web_name": "Raya", "team": 1, "element_type": 1, "now_cost": 55, "status": "a", "total_points": 50},
        {"id": 20, "web_name": "Salah", "team": 2, "element_type": 3, "now_cost": 125, "status": "a", "total_points": 90},
    ] + [
        {"id": pid, "web_name": f"P_{pid}", "team": (pid % 2) + 1, "element_type": 2, "now_cost": 50, "status": "a", "total_points": 30}
        for pid in range(101, 114)
    ]

    bootstrap = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Liverpool", "short_name": "LIV"},
        ],
        "elements": elements,
    }

    # Fixtures for GW1 and GW2
    fixtures = [
        {
            "id": 1,
            "event": 1,
            "team_h": 1,
            "team_a": 2,
            "team_h_difficulty": 4,
            "team_a_difficulty": 3,
            "kickoff_time": "2026-08-20T15:00:00Z",
            "finished": True,
        },
        {
            "id": 2,
            "event": 2,
            "team_h": 2,
            "team_a": 1,
            "team_h_difficulty": 3,
            "team_a_difficulty": 4,
            "kickoff_time": "2026-08-27T15:00:00Z",
            "finished": False,
        },
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    squad_data = {
        "season": "2026/27",
        "player_ids": player_ids,
        "purchase_prices_tenths": {str(pid): 50 for pid in player_ids},
        "bank_tenths": 10,
        "free_transfers": 1,
        "chips_remaining": [],
    }
    squad_path.write_text(json.dumps(squad_data), encoding="utf-8")

    return db_path, squad_path


def test_get_current_gameweek(mock_fixture_db: tuple[Path, Path]) -> None:
    db_path, _ = mock_fixture_db
    store = SnapshotStore(db_path)
    # Next unfinished gameweek is 2
    assert get_current_gameweek(store) == 2


def test_analyze_team_fixtures(mock_fixture_db: tuple[Path, Path]) -> None:
    db_path, _ = mock_fixture_db
    res = analyze_team_fixtures(database_path=db_path, num_gameweeks=1, start_gw=2)

    assert res["start_gw"] == 2
    assert len(res["team_rankings"]) == 2

    # Verify team ranking entries
    liv_entry = next(t for t in res["team_rankings"] if t["short_name"] == "LIV")
    assert liv_entry["avg_difficulty"] == 3.0
    assert liv_entry["ticker"] == "ARS(H,3)"

    ars_entry = next(t for t in res["team_rankings"] if t["short_name"] == "ARS")
    assert ars_entry["avg_difficulty"] == 4.0
    assert ars_entry["ticker"] == "LIV(A,4)"


def test_analyze_squad_fixtures(mock_fixture_db: tuple[Path, Path]) -> None:
    db_path, squad_path = mock_fixture_db
    res = analyze_squad_fixtures(squad_path=squad_path, database_path=db_path, num_gameweeks=1, start_gw=2)

    assert len(res["squad_players"]) == 15
    raya = next(p for p in res["squad_players"] if p["name"] == "Raya")
    assert raya["team"] == "ARS"
    assert raya["avg_difficulty"] == 4.0
