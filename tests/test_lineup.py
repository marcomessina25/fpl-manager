"""Tests for starting XI and captaincy selection module."""

import json
from pathlib import Path
import pytest

from fpl_manager.lineup import select_starting_lineup
from fpl_manager.storage import SnapshotStore, utc_timestamp


@pytest.fixture
def lineup_test_env(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "fpl.sqlite3"
    squad_path = tmp_path / "current_squad.json"

    store = SnapshotStore(db_path)
    bootstrap = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Liverpool", "short_name": "LIV"},
            {"id": 3, "name": "Manchester City", "short_name": "MCI"},
        ],
        "elements": [],
    }

    # 15 players:
    # 2 GKP (ids 1, 2)
    # 5 DEF (ids 3, 4, 5, 6, 7)
    # 5 MID (ids 8, 9, 10, 11, 12)
    # 3 FWD (ids 13, 14, 15)
    player_ids = list(range(1, 16))
    for p_id in player_ids:
        if p_id <= 2:
            pos_id = 1
            cost = 50 if p_id == 1 else 40
        elif p_id <= 7:
            pos_id = 2
            cost = 60 if p_id == 3 else 45
        elif p_id <= 12:
            pos_id = 3
            cost = 100 if p_id == 8 else 50
        else:
            pos_id = 4
            cost = 150 if p_id == 13 else 60

        bootstrap["elements"].append({
            "id": p_id,
            "web_name": f"Player_{p_id}",
            "team": ((p_id - 1) % 3) + 1,
            "element_type": pos_id,
            "now_cost": cost,
            "status": "a",
            "total_points": 20,
        })

    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 3, "team_a": 1, "team_h_difficulty": 2, "team_a_difficulty": 4, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 3, "event": 2, "team_h": 2, "team_a": 3, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-27T17:30:00Z", "finished": False},
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


def test_select_starting_lineup(tmp_path: Path, lineup_test_env: tuple[Path, Path]) -> None:
    db_path, squad_path = lineup_test_env
    report_file = tmp_path / "lineup_report.json"

    res = select_starting_lineup(
        squad_path=squad_path,
        database_path=db_path,
        gameweek=2,
        report_path=report_file,
    )

    assert res["gameweek"] == 2
    assert report_file.is_file()

    starters = res["starters"]
    bench = res["bench"]

    assert len(starters) == 11
    assert len(bench) == 4

    # Verify positions
    gks = [p for p in starters if p["pos_abbr"] == "GKP"]
    defs = [p for p in starters if p["pos_abbr"] == "DEF"]
    mids = [p for p in starters if p["pos_abbr"] == "MID"]
    fwds = [p for p in starters if p["pos_abbr"] == "FWD"]

    assert len(gks) == 1
    assert len(defs) >= 3
    assert len(mids) >= 2
    assert len(fwds) >= 1

    # Check formation string
    assert res["formation"] == f"{len(defs)}-{len(mids)}-{len(fwds)}"

    # Check bench
    assert bench[0]["role"] == "GK_SUB"
    assert bench[0]["pos_abbr"] == "GKP"

    # Check captain
    captain = res["captain"]
    assert captain["role"] == "CAPTAIN"
    # Captain has max xP among starters
    for s in starters:
        assert captain["expected_points"] >= s["expected_points"]

    # Check vice-captain
    vc = res["vice_captain"]
    assert vc["role"] == "VICE_CAPTAIN"
    assert vc["id"] != captain["id"]

    # Check points math
    pts = res["projected_points"]
    assert pts["captain_bonus_xp"] == captain["expected_points"]
    assert pts["total_xp"] == round(pts["starters_xp"] + pts["captain_bonus_xp"], 2)
