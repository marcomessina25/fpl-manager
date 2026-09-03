"""Tests for current-squad report generator module."""

import json
from pathlib import Path
import pytest

from fpl_manager.squad_report import generate_squad_report
from fpl_manager.storage import SnapshotStore, utc_timestamp


@pytest.fixture
def mock_squad_db(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "fpl.sqlite3"
    squad_path = tmp_path / "current_squad.json"

    store = SnapshotStore(db_path)
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

    # 2 GKP, 5 DEF, 5 MID, 3 FWD
    player_ids = list(range(1, 16))
    for i, p_id in enumerate(player_ids):
        pos_id = 1 if i < 2 else (2 if i < 7 else (3 if i < 12 else 4))
        team_id = (i % 5) + 1
        bootstrap["elements"].append({
            "id": p_id,
            "web_name": f"Player_{p_id}",
            "team": team_id,
            "element_type": pos_id,
            "now_cost": 50 + (p_id % 10),
            "status": "a",
            "total_points": 10 * p_id,
        })

    store.save_snapshot(bootstrap, [], utc_timestamp())

    squad_data = {
        "season": "2026/27",
        "player_ids": player_ids,
        "purchase_prices_tenths": {str(pid): 50 for pid in player_ids},
        "bank_tenths": 15,
        "free_transfers": 1,
        "chips_remaining": ["wildcard_1", "free_hit"],
    }
    squad_path.write_text(json.dumps(squad_data), encoding="utf-8")

    return db_path, squad_path


def test_generate_squad_report(tmp_path: Path, mock_squad_db: tuple[Path, Path]) -> None:
    db_path, squad_path = mock_squad_db
    report_file = tmp_path / "squad_report.json"

    report = generate_squad_report(
        squad_path=squad_path,
        database_path=db_path,
        report_path=report_file,
    )

    assert report["season"] == "2026/27"
    assert report["squad_size"] == 15
    assert report["is_valid"] is True
    assert report["financials"]["bank_tenths"] == 15
    assert report["financials"]["bank_fmt"] == "£1.5m"
    assert len(report["players"]) == 15
    assert report["breakdown"]["positions"] == {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    assert report_file.is_file()
