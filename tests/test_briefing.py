"""Tests for structured analytical briefing and manager dossier generator."""

from pathlib import Path
import pytest

from fpl_manager.briefing import generate_manager_briefing
from fpl_manager.decision_log import log_decision_from_current_squad
from fpl_manager.storage import SnapshotStore, utc_timestamp


@pytest.fixture
def briefing_test_env(tmp_path: Path) -> tuple[Path, Path]:
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
        "events": [
            {"id": 1, "name": "Gameweek 1", "deadline_time": "2026-08-15T10:00:00Z", "is_current": False, "finished": True},
            {"id": 2, "name": "Gameweek 2", "deadline_time": "2026-08-22T10:00:00Z", "is_current": False, "finished": True},
            {"id": 3, "name": "Gameweek 3", "deadline_time": "2026-08-29T10:00:00Z", "is_current": True, "finished": False},
        ],
        "elements": [],
    }

    for p_id in range(1, 18):
        pos_id = 1 if p_id <= 2 else (2 if p_id <= 7 else (3 if p_id <= 12 else 4))
        cost = 50
        news_text = "Hamstring tightness" if p_id == 5 else ""
        status_val = "d" if p_id == 5 else "a"
        chance_val = 75 if p_id == 5 else 100

        bootstrap["elements"].append({
            "id": p_id,
            "web_name": f"Player_{p_id}",
            "team": 5 if p_id == 16 else (4 if p_id == 17 else (((p_id - 1) % 5) + 1)),
            "element_type": pos_id,
            "now_cost": cost,
            "status": status_val,
            "chance_of_playing_next_round": chance_val,
            "news": news_text,
            "total_points": 25,
            "selected_by_percent": 15.0,
        })

    fixtures = [
        {"id": 1, "event": 3, "team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 3, "kickoff_time": "2026-08-29T11:30:00Z", "finished": False},
        {"id": 2, "event": 3, "team_h": 3, "team_a": 4, "team_h_difficulty": 2, "team_a_difficulty": 4, "kickoff_time": "2026-08-29T14:00:00Z", "finished": False},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    squad_data = {
        "season": "2026/27",
        "free_transfers": 1,
        "bank_tenths": 15,
        "chips_remaining": ["wildcard"],
        "player_ids": list(range(1, 16)),
        "purchase_prices_tenths": {str(i): 50 for i in range(1, 16)},
        "gameweek": 3,
    }
    import json
    squad_path.write_text(json.dumps(squad_data, indent=2), encoding="utf-8")

    return db_path, squad_path


def test_generate_manager_briefing(briefing_test_env: tuple[Path, Path]) -> None:
    db_path, squad_path = briefing_test_env

    # 1. Generate briefing without decision logged
    dossier = generate_manager_briefing(
        squad_path=squad_path,
        gameweek=3,
        database_path=db_path,
        save_reports=False,
    )

    assert dossier["gameweek"] == 3
    assert dossier["financials"]["bank_fmt"] == "£1.5m"
    assert dossier["financials"]["free_transfers"] == 1
    assert "lineup" in dossier
    assert len(dossier["lineup"]["starters"]) == 11
    assert len(dossier["lineup"]["bench"]) == 4
    assert dossier["lineup"]["captain"]["name"] is not None

    # Check squad health alert was captured for Player_5
    assert len(dossier["squad_health_alerts"]) == 1
    assert dossier["squad_health_alerts"][0]["name"] == "Player_5"
    assert dossier["squad_health_alerts"][0]["chance_pct"] == 75

    # Check Markdown output exists and has sections
    md = dossier["markdown"]
    assert "# FPL Manager Analytical Dossier — Gameweek 3" in md
    assert "## 1. Squad Status & Financials" in md
    assert "## 2. Matchday Starting XI & Projections" in md
    assert "## 3. Injury Flags & Press Conference Intel" in md
    assert "Player_5" in md

    # 2. Log a decision and re-generate
    log_decision_from_current_squad(
        gameweek=3,
        squad_path=squad_path,
        database_path=db_path,
        starting_player_ids=[1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14],
        bench_player_ids=[2, 6, 7, 15],
        captain_id=13,
        vice_captain_id=8,
        overwrite=True,
    )

    dossier_logged = generate_manager_briefing(
        squad_path=squad_path,
        gameweek=3,
        database_path=db_path,
        save_reports=False,
    )
    assert dossier_logged["is_decision_logged"] is True
    assert dossier_logged["lineup"]["captain"]["id"] == 13
