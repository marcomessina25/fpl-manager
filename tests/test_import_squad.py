"""Tests for squad import utility script and CLI subcommand."""

import json
from pathlib import Path
import pytest

from fpl_manager.import_squad import import_squad_from_file
from fpl_manager.storage import SnapshotStore, utc_timestamp


@pytest.fixture
def mock_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "fpl.sqlite3"
    store = SnapshotStore(db_path)
    bootstrap = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Liverpool", "short_name": "LIV"},
            {"id": 3, "name": "Manchester City", "short_name": "MCI"},
        ],
        "elements": [
            {
                "id": 10,
                "web_name": "Raya",
                "team": 1,
                "element_type": 1,
                "now_cost": 55,
                "status": "a",
                "total_points": 100,
            },
            {
                "id": 20,
                "web_name": "Salah",
                "team": 2,
                "element_type": 3,
                "now_cost": 125,
                "status": "a",
                "total_points": 150,
            },
            {
                "id": 30,
                "web_name": "Silva",
                "team": 3,
                "element_type": 3,
                "now_cost": 80,
                "status": "a",
                "total_points": 80,
            },
            {
                "id": 31,
                "web_name": "B.Silva",
                "team": 3,
                "element_type": 3,
                "now_cost": 85,
                "status": "a",
                "total_points": 90,
            },
        ],
    }
    fixtures: list[dict] = []
    store.save_snapshot(bootstrap, fixtures, utc_timestamp())
    return db_path


def test_import_squad_success_and_failures(tmp_path: Path, mock_db: Path, capsys) -> None:
    players_file = tmp_path / "players.txt"
    squad_file = tmp_path / "current_squad.json"

    # players.txt contains:
    # 1. Exact match (Raya)
    # 2. Exact match (Salah)
    # 3. Exact match with web_name among multi-matches (Silva vs B.Silva -> 'Silva' matches web_name 'Silva' exactly)
    # 4. Unknown player (NonExistentPlayer)
    # 5. Comment line and blank lines
    players_content = """
# My squad draft
Raya
Salah
Silva
NonExistentPlayer

"""
    players_file.write_text(players_content, encoding="utf-8")

    result = import_squad_from_file(
        players_path=players_file,
        squad_path=squad_file,
        database_path=mock_db,
    )

    captured = capsys.readouterr()
    stdout_lines = captured.out.strip().splitlines()

    assert "importing id 10 player Raya team ARS price 55" in stdout_lines
    assert "importing id 20 player Salah team LIV price 125" in stdout_lines
    assert "importing id 30 player Silva team MCI price 80" in stdout_lines
    assert "failed importing player NonExistentPlayer" in stdout_lines

    assert result["player_ids"] == [10, 20, 30]
    assert result["purchase_prices_tenths"] == {
        "10": 55,
        "20": 125,
        "30": 80,
    }

    assert squad_file.is_file()
    saved_data = json.loads(squad_file.read_text(encoding="utf-8"))
    assert saved_data["player_ids"] == [10, 20, 30]


def test_import_squad_ambiguous_query(tmp_path: Path, mock_db: Path, capsys) -> None:
    players_file = tmp_path / "players.txt"
    squad_file = tmp_path / "current_squad.json"

    # Searching 'ilva' matches both 'Silva' and 'B.Silva', neither is an exact match for 'ilva'
    players_file.write_text("ilva\n", encoding="utf-8")

    result = import_squad_from_file(
        players_path=players_file,
        squad_path=squad_file,
        database_path=mock_db,
    )

    captured = capsys.readouterr()
    assert "failed importing player ilva" in captured.out.strip()
    assert result["player_ids"] == []


def test_import_squad_missing_players_file(tmp_path: Path, mock_db: Path) -> None:
    missing_file = tmp_path / "non_existent_players.txt"
    squad_file = tmp_path / "current_squad.json"

    with pytest.raises(RuntimeError, match="Players file not found"):
        import_squad_from_file(
            players_path=missing_file,
            squad_path=squad_file,
            database_path=mock_db,
        )
