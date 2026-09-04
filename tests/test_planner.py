"""Tests for multi-gameweek transfer planning engine (planner.py)."""

import json
from pathlib import Path
import pytest

from fpl_manager.planner import generate_multi_gameweek_plan
from fpl_manager.storage import SnapshotStore, utc_timestamp


@pytest.fixture
def planner_test_db(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "fpl.sqlite3"
    squad_path = tmp_path / "current_squad.json"

    store = SnapshotStore(db_path)
    teams = [
        {"id": 1, "name": "Arsenal", "short_name": "ARS"},
        {"id": 2, "name": "Liverpool", "short_name": "LIV"},
        {"id": 3, "name": "Manchester City", "short_name": "MCI"},
        {"id": 4, "name": "Chelsea", "short_name": "CHE"},
        {"id": 5, "name": "Tottenham", "short_name": "TOT"},
        {"id": 6, "name": "Newcastle", "short_name": "NEW"},
        {"id": 7, "name": "Aston Villa", "short_name": "AVL"},
        {"id": 8, "name": "Brighton", "short_name": "BHA"},
        {"id": 9, "name": "Fulham", "short_name": "FUL"},
        {"id": 10, "name": "Brentford", "short_name": "BRE"},
    ]
    elements = []

    # 15 players in current squad (IDs 1..15)
    for i in range(1, 16):
        pos_id = 1 if i <= 2 else (2 if i <= 7 else (3 if i <= 12 else 4))
        team_id = ((i - 1) % 10) + 1
        elements.append({
            "id": i,
            "web_name": f"Squad_{i}",
            "team": team_id,
            "element_type": pos_id,
            "now_cost": 50,
            "status": "a",
            "total_points": 20,
            "minutes": 450,
            "expected_goals": "0.1",
            "expected_assists": "0.1",
            "expected_goals_conceded": "1.0",
        })

    # Pool of candidate targets across all positions and teams
    cand_id = 100
    for pos_id, count in [(1, 6), (2, 10), (3, 10), (4, 6)]:
        for c in range(count):
            cand_id += 1
            elements.append({
                "id": cand_id,
                "web_name": f"Target_{cand_id}",
                "team": (c % 10) + 1,
                "element_type": pos_id,
                "now_cost": 45 + (c % 4) * 10,
                "status": "a",
                "total_points": 50 + c * 5,
                "minutes": 800,
                "expected_goals": "0.4",
                "expected_assists": "0.3",
                "expected_goals_conceded": "0.5",
            })

    bootstrap = {"teams": teams, "elements": elements}
    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 3, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 3, "event": 2, "team_h": 3, "team_a": 4, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 4, "event": 2, "team_h": 5, "team_a": 6, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 5, "event": 2, "team_h": 7, "team_a": 8, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 6, "event": 2, "team_h": 9, "team_a": 10, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 7, "event": 3, "team_h": 2, "team_a": 1, "team_h_difficulty": 3, "team_a_difficulty": 2, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 8, "event": 3, "team_h": 4, "team_a": 3, "team_h_difficulty": 3, "team_a_difficulty": 2, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 9, "event": 3, "team_h": 6, "team_a": 5, "team_h_difficulty": 3, "team_a_difficulty": 2, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 10, "event": 3, "team_h": 8, "team_a": 7, "team_h_difficulty": 3, "team_a_difficulty": 2, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 11, "event": 3, "team_h": 10, "team_a": 9, "team_h_difficulty": 3, "team_a_difficulty": 2, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 12, "event": 4, "team_h": 1, "team_a": 3, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-09-10T15:00:00Z", "finished": False},
        {"id": 13, "event": 4, "team_h": 2, "team_a": 4, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-09-10T15:00:00Z", "finished": False},
        {"id": 14, "event": 4, "team_h": 5, "team_a": 7, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-09-10T15:00:00Z", "finished": False},
        {"id": 15, "event": 4, "team_h": 6, "team_a": 8, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-09-10T15:00:00Z", "finished": False},
        {"id": 16, "event": 4, "team_h": 9, "team_a": 10, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-09-10T15:00:00Z", "finished": False},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    squad_data = {
        "season": "2026/27",
        "player_ids": list(range(1, 16)),
        "purchase_prices_tenths": {str(pid): 50 for pid in range(1, 16)},
        "bank_tenths": 15,
        "free_transfers": 1,
        "chips_remaining": ["wildcard", "freehit"],
    }
    squad_path.write_text(json.dumps(squad_data), encoding="utf-8")

    return db_path, squad_path


def test_generate_multi_gameweek_plan_basic(tmp_path: Path, planner_test_db: tuple[Path, Path]) -> None:
    db_path, squad_path = planner_test_db
    report_file = tmp_path / "plan.json"

    res = generate_multi_gameweek_plan(
        squad_path=squad_path,
        database_path=db_path,
        horizon=3,
        report_path=report_file,
    )

    assert res["planning_horizon"] == 3
    assert len(res["target_gameweeks"]) == 3
    assert report_file.is_file()

    best = res["best_plan"]
    assert best is not None
    assert "total_net_xp" in best
    assert "total_floor_xp" in best
    assert "total_ceiling_xp" in best
    assert len(best["gameweek_steps"]) == 3

    for step in best["gameweek_steps"]:
        assert "gameweek" in step
        assert "action" in step
        assert "formation" in step
        assert "captain" in step
        assert "vice_captain" in step
        assert "lineup_xp" in step
        assert "net_xp" in step
        assert "bank_after_fmt" in step
        assert "free_transfers_after" in step
        assert step["free_transfers_after"] <= 5


def test_generate_multi_gameweek_plan_no_hits(tmp_path: Path, planner_test_db: tuple[Path, Path]) -> None:
    db_path, squad_path = planner_test_db
    report_file = tmp_path / "plan_nohits.json"

    res = generate_multi_gameweek_plan(
        squad_path=squad_path,
        database_path=db_path,
        horizon=2,
        allow_hits=False,
        report_path=report_file,
    )

    assert res["allow_hits"] is False
    best = res["best_plan"]
    assert best["total_hits"] == 0
    for step in best["gameweek_steps"]:
        assert step["transfer_hits"] == 0


def test_generate_multi_gameweek_plan_validation_and_risk(planner_test_db: tuple[Path, Path]) -> None:
    db_path, squad_path = planner_test_db

    for risk in ("neutral", "floor", "ceiling"):
        res = generate_multi_gameweek_plan(
            squad_path=squad_path,
            database_path=db_path,
            horizon=2,
            risk_profile=risk,
        )
        assert res["risk_profile"] == risk
        assert res["best_plan"] is not None

    with pytest.raises(ValueError, match="Invalid horizon"):
        generate_multi_gameweek_plan(squad_path=squad_path, database_path=db_path, horizon=0)

    with pytest.raises(ValueError, match="Invalid horizon"):
        generate_multi_gameweek_plan(squad_path=squad_path, database_path=db_path, horizon=10)

    with pytest.raises(ValueError, match="Invalid risk_profile"):
        generate_multi_gameweek_plan(squad_path=squad_path, database_path=db_path, risk_profile="unknown")
