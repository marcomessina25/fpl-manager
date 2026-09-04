"""Unit and integration tests for official FPL live score fetching and caching."""

import io
import json
from pathlib import Path
from unittest.mock import patch
import urllib.error
import pytest

from fpl_manager.api import fetch_gameweek_live_data
from fpl_manager.cli import main
from fpl_manager.decision_log import record_gameweek_decision
from fpl_manager.evaluation import evaluate_gameweek_decision
from fpl_manager.scores import get_or_fetch_gameweek_scores, update_gameweek_scores
from fpl_manager.storage import SnapshotStore, utc_timestamp


@pytest.fixture
def scores_test_env(tmp_path: Path) -> tuple[Path, Path]:
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

    for p_id in range(1, 16):
        if p_id <= 2:
            pos_id = 1
            cost = 50
        elif p_id <= 7:
            pos_id = 2
            cost = 50
        elif p_id <= 12:
            pos_id = 3
            cost = 50
        else:
            pos_id = 4
            cost = 80

        bootstrap["elements"].append({
            "id": p_id,
            "web_name": f"Player_{p_id}",
            "team": ((p_id - 1) % 5) + 1,
            "element_type": pos_id,
            "now_cost": cost,
            "status": "a",
            "total_points": 20,
        })

    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 3, "team_a": 1, "team_h_difficulty": 2, "team_a_difficulty": 4, "kickoff_time": "2026-08-27T15:00:00Z", "finished": True},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    squad_data = {
        "season": "2026/27",
        "free_transfers": 1,
        "bank_tenths": 10,
        "player_ids": list(range(1, 16)),
        "purchase_prices_tenths": {str(i): 50 for i in range(1, 16)},
    }
    squad_path.write_text(json.dumps(squad_data, indent=2), encoding="utf-8")

    return db_path, squad_path


def test_fetch_gameweek_live_data_success() -> None:
    mock_payload = {
        "elements": [
            {
                "id": 1,
                "stats": {
                    "total_points": 8,
                    "minutes": 90,
                    "goals_scored": 1,
                    "assists": 0,
                    "clean_sheets": 1,
                    "goals_conceded": 0,
                    "bonus": 3,
                    "bps": 34,
                },
            }
        ]
    }
    mock_response = io.BytesIO(json.dumps(mock_payload).encode("utf-8"))

    with patch("fpl_manager.api.urlopen", return_value=mock_response):
        data = fetch_gameweek_live_data(1)
        assert "elements" in data
        assert len(data["elements"]) == 1
        assert data["elements"][0]["id"] == 1
        assert data["elements"][0]["stats"]["total_points"] == 8


def test_fetch_gameweek_live_data_error() -> None:
    with patch("fpl_manager.api.urlopen", side_effect=urllib.error.URLError("Network unreachable")):
        with pytest.raises(urllib.error.URLError):
            fetch_gameweek_live_data(1)


def test_storage_save_and_get_gameweek_scores(scores_test_env: tuple[Path, Path]) -> None:
    db_path, _ = scores_test_env
    store = SnapshotStore(db_path)

    sample_live = {
        "elements": [
            {"id": 1, "stats": {"total_points": 6, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 1, "goals_conceded": 0, "bonus": 1, "bps": 24}},
            {"id": 2, "stats": {"total_points": 2, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 2, "bonus": 0, "bps": 12}},
        ]
    }

    saved = store.save_gameweek_scores(event_id=2, live_data=sample_live, fetched_at=utc_timestamp())
    assert saved == 2

    cached = store.get_gameweek_scores(event_id=2)
    assert len(cached) == 2
    assert cached[1] == 6.0
    assert cached[2] == 2.0

    # Querying unrecorded gameweek
    empty = store.get_gameweek_scores(event_id=99)
    assert empty == {}


def test_get_or_fetch_gameweek_scores_caching(scores_test_env: tuple[Path, Path]) -> None:
    db_path, _ = scores_test_env
    store = SnapshotStore(db_path)

    # 1. Pre-seed DB cache
    store.save_gameweek_scores(
        event_id=2,
        live_data={
            "elements": [
                {"id": 13, "stats": {"total_points": 14, "minutes": 90, "goals_scored": 2, "assists": 0, "clean_sheets": 0, "goals_conceded": 1, "bonus": 3, "bps": 40}}
            ]
        },
        fetched_at=utc_timestamp(),
    )

    # 2. When cached, it should NOT make any network call
    with patch("fpl_manager.scores.fetch_gameweek_live_data") as mock_fetch:
        scores = get_or_fetch_gameweek_scores(2, database_path=db_path)
        assert 13 in scores
        assert scores[13] == 14.0
        mock_fetch.assert_not_called()


def test_get_or_fetch_gameweek_scores_network_fetch(scores_test_env: tuple[Path, Path]) -> None:
    db_path, _ = scores_test_env

    mock_live_payload = {
        "elements": [
            {
                "id": 14,
                "stats": {
                    "total_points": 9,
                    "minutes": 88,
                    "goals_scored": 1,
                    "assists": 1,
                    "clean_sheets": 0,
                    "goals_conceded": 1,
                    "bonus": 2,
                    "bps": 31,
                },
            }
        ]
    }

    with patch("fpl_manager.scores.fetch_gameweek_live_data", return_value=mock_live_payload) as mock_fetch:
        scores = get_or_fetch_gameweek_scores(2, database_path=db_path)
        mock_fetch.assert_called_once_with(2)
        assert 14 in scores
        assert scores[14] == 9.0

        # Verify it was saved to SQLite for subsequent calls
        store = SnapshotStore(db_path)
        cached = store.get_gameweek_scores(2)
        assert len(cached) == 1
        assert cached[14] == 9.0


def test_get_or_fetch_gameweek_scores_offline_fallback(scores_test_env: tuple[Path, Path]) -> None:
    db_path, _ = scores_test_env

    # Network error with no cache should cleanly return empty dict without crashing
    with patch("fpl_manager.scores.fetch_gameweek_live_data", side_effect=RuntimeError("Offline")):
        scores = get_or_fetch_gameweek_scores(3, database_path=db_path)
        assert scores == {}


def test_update_gameweek_scores(scores_test_env: tuple[Path, Path], tmp_path: Path) -> None:
    db_path, _ = scores_test_env
    raw_dir = tmp_path / "raw"

    mock_live_payload = {
        "elements": [
            {
                "id": 8,
                "stats": {"total_points": 11, "minutes": 90, "goals_scored": 1, "assists": 1, "clean_sheets": 1, "goals_conceded": 0, "bonus": 3, "bps": 38},
            }
        ]
    }

    with patch("fpl_manager.scores.RAW_DIRECTORY", raw_dir), patch("fpl_manager.scores.fetch_gameweek_live_data", return_value=mock_live_payload):
        res = update_gameweek_scores(2, database_path=db_path)
        assert res["gameweek"] == 2
        assert res["players_updated"] == 1
        assert any("event-2-live" in f.name for f in raw_dir.iterdir())


def test_evaluation_with_automated_scores(scores_test_env: tuple[Path, Path]) -> None:
    db_path, _ = scores_test_env
    squad_ids = list(range(1, 16))
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]
    bench = [2, 6, 7, 15]

    record_gameweek_decision(
        gameweek=2,
        squad_player_ids=squad_ids,
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=13,
        vice_captain_id=8,
        database_path=db_path,
    )

    # Pre-seed gameweek 2 live scores for starters and bench
    store = SnapshotStore(db_path)
    mock_payload = {
        "elements": [
            {"id": pid, "stats": {"total_points": 6 if pid == 13 else 4, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 1, "bonus": 0, "bps": 15}}
            for pid in squad_ids
        ]
    }
    store.save_gameweek_scores(2, mock_payload, utc_timestamp())

    # Run evaluate without explicit actual_scores (should auto-fetch from database)
    eval_res = evaluate_gameweek_decision(2, actual_scores=None, database_path=db_path)

    assert eval_res["decision_logged"] is True
    assert eval_res["actual_lineup_score"] > 0
    assert eval_res["captaincy"]["captain_actual_points"] == 6.0
    # Lineup: 10 starters * 4 + 1 captain * 6 * 2 (captain doubled) = 40 + 12 = 52.0
    assert eval_res["actual_lineup_score"] == 52.0


def test_cli_update_scores_and_auto_evaluate(
    scores_test_env: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path, _ = scores_test_env
    monkeypatch.setattr("fpl_manager.cli.DATABASE_PATH", db_path)

    mock_live_payload = {
        "elements": [
            {
                "id": pid,
                "stats": {"total_points": 5, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 1, "bonus": 0, "bps": 12},
            }
            for pid in range(1, 16)
        ]
    }

    # 1. Test update-scores CLI
    with patch("fpl_manager.scores.fetch_gameweek_live_data", return_value=mock_live_payload):
        main(["update-scores", "--gameweek", "2"])
        out = capsys.readouterr().out
        assert "Updated matchday scores for Gameweek 2" in out
        assert "15 players saved" in out

    # 2. Log decision for GW2
    squad_ids = list(range(1, 16))
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]
    bench = [2, 6, 7, 15]
    record_gameweek_decision(
        gameweek=2,
        squad_player_ids=squad_ids,
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=13,
        vice_captain_id=8,
        database_path=db_path,
    )

    # 3. Evaluate without passing --scores
    main(["evaluate", "--gameweek", "2"])
    out_eval = capsys.readouterr().out
    assert "Gameweek 2" in out_eval
    assert "Actual Score: 60.0" in out_eval
