"""Tests for pre-deadline decision logging and audit trail system."""

import json
from pathlib import Path
import pytest

from fpl_manager.cli import main
from fpl_manager.decision_log import (
    get_gameweek_decision,
    list_decisions,
    log_decision_from_current_squad,
    parse_and_apply_transfers,
    record_actual_gameweek_score,
    record_gameweek_decision,
    resolve_player_id,
    resolve_player_ids_list,
)
from fpl_manager.storage import SnapshotStore, utc_timestamp


@pytest.fixture
def decision_test_env(tmp_path: Path) -> tuple[Path, Path]:
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

    # 17 players:
    # 2 GKP (ids 1, 2)
    # 5 DEF (ids 3, 4, 5, 6, 7)
    # 5 MID (ids 8, 9, 10, 11, 12)
    # 5 FWD (ids 13, 14, 15, 16, 17)
    for p_id in range(1, 18):
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
            "team": 5 if p_id == 16 else (((p_id - 1) % 5) + 1),
            "element_type": pos_id,
            "now_cost": cost,
            "status": "a",
            "total_points": 25,
        })

    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 3, "team_a": 1, "team_h_difficulty": 2, "team_a_difficulty": 4, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 3, "event": 2, "team_h": 2, "team_a": 3, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-27T17:30:00Z", "finished": False},
        {"id": 4, "event": 2, "team_h": 4, "team_a": 5, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
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


def test_record_gameweek_decision_success(decision_test_env: tuple[Path, Path]) -> None:
    db_path, _ = decision_test_env
    squad_ids = list(range(1, 16))
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]
    bench = [2, 6, 7, 15]

    res = record_gameweek_decision(
        gameweek=2,
        squad_player_ids=squad_ids,
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=13,
        vice_captain_id=8,
        season="2026/27",
        chip_played=None,
        transfer_hits=0,
        notes="Captaincy on premium FWD 13",
        database_path=db_path,
        capture_recommendations=True,
    )

    assert res["gameweek"] == 2
    assert res["decision_id"] is not None
    assert res["captain_id"] == 13
    assert res["captain_name"] == "Player_13"
    assert res["vice_captain_id"] == 8
    assert res["predicted_lineup_xp"] > 0
    assert res["notes"] == "Captaincy on premium FWD 13"


def test_record_gameweek_decision_validations(decision_test_env: tuple[Path, Path]) -> None:
    db_path, _ = decision_test_env
    squad_ids = list(range(1, 16))
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]
    bench = [2, 6, 7, 15]

    # Invalid squad size
    with pytest.raises(ValueError, match="must have exactly 15"):
        record_gameweek_decision(
            gameweek=2,
            squad_player_ids=squad_ids[:14],
            starting_player_ids=starters,
            bench_player_ids=bench,
            captain_id=13,
            vice_captain_id=8,
            database_path=db_path,
        )

    # Captain not in starting XI
    with pytest.raises(ValueError, match="Captain ID 2 must be in the starting XI"):
        record_gameweek_decision(
            gameweek=2,
            squad_player_ids=squad_ids,
            starting_player_ids=starters,
            bench_player_ids=bench,
            captain_id=2,  # bench keeper
            vice_captain_id=8,
            database_path=db_path,
        )

    # Captain == VC
    with pytest.raises(ValueError, match="cannot be the same player"):
        record_gameweek_decision(
            gameweek=2,
            squad_player_ids=squad_ids,
            starting_player_ids=starters,
            bench_player_ids=bench,
            captain_id=13,
            vice_captain_id=13,
            database_path=db_path,
        )


def test_record_gameweek_duplicate_and_overwrite(decision_test_env: tuple[Path, Path]) -> None:
    db_path, _ = decision_test_env
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

    # Disallow accidental duplicate overwrite
    with pytest.raises(ValueError, match="Decision already logged"):
        record_gameweek_decision(
            gameweek=2,
            squad_player_ids=squad_ids,
            starting_player_ids=starters,
            bench_player_ids=bench,
            captain_id=8,
            vice_captain_id=13,
            database_path=db_path,
            overwrite=False,
        )

    # Overwrite when explicit
    res_updated = record_gameweek_decision(
        gameweek=2,
        squad_player_ids=squad_ids,
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=8,
        vice_captain_id=13,
        notes="Updated captaincy to Player_8",
        database_path=db_path,
        overwrite=True,
    )
    assert res_updated["captain_id"] == 8
    assert res_updated["notes"] == "Updated captaincy to Player_8"


def test_get_and_list_decisions(decision_test_env: tuple[Path, Path]) -> None:
    db_path, _ = decision_test_env
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
    record_gameweek_decision(
        gameweek=3,
        squad_player_ids=squad_ids,
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=8,
        vice_captain_id=13,
        database_path=db_path,
    )

    d2 = get_gameweek_decision(2, database_path=db_path)
    assert d2 is not None
    assert d2["gameweek"] == 2
    assert d2["captain_name"] == "Player_13"

    d_none = get_gameweek_decision(99, database_path=db_path)
    assert d_none is None

    all_d = list_decisions(database_path=db_path)
    assert len(all_d) == 2
    assert all_d[0]["gameweek"] == 2
    assert all_d[1]["gameweek"] == 3


def test_record_actual_gameweek_score(decision_test_env: tuple[Path, Path]) -> None:
    db_path, _ = decision_test_env
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

    # Missing decision
    with pytest.raises(ValueError, match="No decision found"):
        record_actual_gameweek_score(99, 65, database_path=db_path)

    updated = record_actual_gameweek_score(2, 72, database_path=db_path)
    assert updated["actual_points"] == 72


def test_log_decision_from_current_squad(decision_test_env: tuple[Path, Path]) -> None:
    db_path, squad_path = decision_test_env

    res = log_decision_from_current_squad(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        chip_played="triplecaptain",
        transfer_hits=1,
        notes="Triple captain punt",
        overwrite=True,
    )

    assert res["gameweek"] == 2
    assert res["chip_played"] == "triplecaptain"
    assert res["transfer_hits"] == 1
    assert len(res["starting_player_ids"]) == 11
    assert len(res["bench_player_ids"]) == 4
    assert res["captain_id"] in res["starting_player_ids"]


def test_decision_formatters() -> None:
    from fpl_manager.cli import format_decision_concise, format_decisions_list_concise

    decision = {
        "decision_id": 1,
        "gameweek": 2,
        "season": "2026/27",
        "captain_name": "Haaland",
        "vice_captain_name": "Salah",
        "predicted_lineup_xp": 62.4,
        "predicted_floor_xp": 45.0,
        "predicted_ceiling_xp": 80.0,
        "chip_played": "triplecaptain",
        "transfer_hits": 1,
        "actual_points": 74,
        "notes": "Targeting DGW",
    }
    concise = format_decision_concise(decision)
    assert "Gameweek 2" in concise
    assert "Haaland (C)" in concise
    assert "Salah (VC)" in concise
    assert "triplecaptain" in concise
    assert "Actual Score: 74" in concise

    summary = format_decisions_list_concise([decision])
    assert "GW2" in summary
    assert "Haaland" in summary
    assert "triplecaptain" in concise

    empty_summary = format_decisions_list_concise([])
    assert "No decisions logged yet." in empty_summary


def test_resolve_player_id_and_helpers(decision_test_env: tuple[Path, Path]) -> None:
    db_path, _ = decision_test_env
    store = SnapshotStore(db_path)

    # Int and str digits
    assert resolve_player_id(store, 3) == 3
    assert resolve_player_id(store, "3") == 3

    # Exact name
    assert resolve_player_id(store, "Player_3") == 3

    # Unknown
    with pytest.raises(ValueError, match="Could not resolve"):
        resolve_player_id(store, "Unknown_Player_999")

    # List resolving
    assert resolve_player_ids_list(store, None) == []
    assert resolve_player_ids_list(store, "") == []
    assert resolve_player_ids_list(store, [1, "2", "Player_3"]) == [1, 2, 3]
    assert resolve_player_ids_list(store, "1, 2, Player_3") == [1, 2, 3]


def test_parse_and_apply_transfers(decision_test_env: tuple[Path, Path]) -> None:
    db_path, _ = decision_test_env
    store = SnapshotStore(db_path)
    squad_ids = list(range(1, 16))

    # None / empty
    new_ids, records = parse_and_apply_transfers(store, squad_ids, None)
    assert new_ids == squad_ids
    assert records == []

    # Valid string transfer: OUT:IN
    new_ids, records = parse_and_apply_transfers(store, squad_ids, ["Player_15:Player_16"])
    assert 15 not in new_ids
    assert 16 in new_ids
    assert len(new_ids) == 15
    assert len(records) == 1
    assert records[0]["outgoing_id"] == 15
    assert records[0]["incoming_id"] == 16
    assert records[0]["outgoing_name"] == "Player_15"
    assert records[0]["incoming_name"] == "Player_16"

    # Outgoing not in squad
    with pytest.raises(ValueError, match="is not in your current squad"):
        parse_and_apply_transfers(store, squad_ids, ["Player_16:Player_17"])

    # Invalid format without colon
    with pytest.raises(ValueError, match="Invalid transfer format"):
        parse_and_apply_transfers(store, squad_ids, ["Player_15-Player_16"])


def test_log_decision_custom_lineup_and_transfers(decision_test_env: tuple[Path, Path]) -> None:
    db_path, squad_path = decision_test_env

    # 1. Custom starters & bench & captaincy
    custom_starters = [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]
    custom_bench = [2, 6, 7, 16]

    res = log_decision_from_current_squad(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        starting_player_ids=custom_starters,
        bench_player_ids=custom_bench,
        captain_id="Player_14",
        vice_captain_id="Player_13",
        transfers=["Player_15:Player_16"],
        overwrite=True,
    )
    assert res["gameweek"] == 2
    assert res["captain_id"] == 14
    assert res["captain_name"] == "Player_14"
    assert res["vice_captain_id"] == 13
    assert res["vice_captain_name"] == "Player_13"
    assert len(res["transfers"]) == 1
    assert res["transfers"][0]["incoming_id"] == 16

    # 2. Starting player not in squad error
    with pytest.raises(ValueError, match="not in the squad"):
        log_decision_from_current_squad(
            gameweek=2,
            squad_path=squad_path,
            database_path=db_path,
            starting_player_ids=[1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 17],  # 17 not in squad
            overwrite=True,
        )


def test_cli_log_decision_custom_options(
    decision_test_env: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path, squad_path = decision_test_env
    monkeypatch.setattr("fpl_manager.cli.DATABASE_PATH", db_path)

    args = [
        "log-decision",
        "--squad", str(squad_path),
        "--gameweek", "2",
        "--starters", "1,3,4,5,8,9,10,11,12,13,14",
        "--bench", "2,6,7,15",
        "--captain", "Player_13",
        "--vice-captain", "Player_8",
        "--notes", "CLI customized lineup",
        "--overwrite",
    ]
    main(args)
    captured = capsys.readouterr().out
    assert "Gameweek 2" in captured
    assert "Player_13 (C)" in captured
    assert "Player_8 (VC)" in captured
    assert "CLI customized lineup" in captured

    # Test CLI with transfer
    args_tx = [
        "log-decision",
        "--squad", str(squad_path),
        "--gameweek", "2",
        "-t", "Player_15:Player_16",
        "--captain", "Player_13",
        "--vice-captain", "Player_8",
        "--overwrite",
    ]
    main(args_tx)
    captured_tx = capsys.readouterr().out
    assert "Player_15 -> Player_16" in captured_tx


def test_past_gameweek_decision_allows_players_not_in_current_squad(decision_test_env: tuple[Path, Path]) -> None:
    db_path, squad_path = decision_test_env

    # Configure current squad as Gameweek 3
    # Player 15 (Amad equivalent) is NOT in current squad (was sold), Player 16 (Tielemans equivalent) is in squad
    gw3_players = list(range(1, 15)) + [16]
    squad_data = {
        "season": "2026/27",
        "gameweek": 3,
        "free_transfers": 2,
        "bank_tenths": 20,
        "player_ids": gw3_players,
        "purchase_prices_tenths": {str(i): 50 for i in gw3_players},
    }
    squad_path.write_text(json.dumps(squad_data, indent=2), encoding="utf-8")
    before_content = squad_path.read_text(encoding="utf-8")

    # 1. Log decision for past Gameweek 1 (where Player 15 was still in the starting lineup!)
    res_gw1 = log_decision_from_current_squad(
        gameweek=1,
        squad_path=squad_path,
        database_path=db_path,
        starting_player_ids=[1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 15],
        bench_player_ids=[2, 6, 7, 14],
        captain_id=13,
        vice_captain_id=8,
        overwrite=True,
    )
    assert res_gw1["gameweek"] == 1
    assert res_gw1["is_past_gameweek"] is True
    assert res_gw1["current_squad_updated"] is False
    assert 15 in res_gw1["starting_player_ids"]

    # 2. Log decision for past Gameweek 2 (2 < 3)
    # Outgoing transfer is Player 15 (who is NOT in current squad) -> Player 16
    res_gw2 = log_decision_from_current_squad(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        transfers=["Player_15:Player_16"],
        starting_player_ids=[1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 16],
        bench_player_ids=[2, 6, 7, 14],
        captain_id=13,
        vice_captain_id=8,
        overwrite=True,
    )

    assert res_gw2["gameweek"] == 2
    assert res_gw2["is_past_gameweek"] is True
    assert res_gw2["current_squad_updated"] is False
    assert 16 in res_gw2["starting_player_ids"]
    assert res_gw2["transfers"][0]["outgoing_name"] == "Player_15"
    assert res_gw2["transfers"][0]["incoming_name"] == "Player_16"

    # Verify current_squad.json is untouched
    after_content = squad_path.read_text(encoding="utf-8")
    assert before_content == after_content

    # Verify decisions are persisted in database
    db_dec1 = get_gameweek_decision(1, database_path=db_path)
    assert db_dec1 is not None
    assert 15 in db_dec1["starting_player_ids"]

    db_dec2 = get_gameweek_decision(2, database_path=db_path)
    assert db_dec2 is not None
    assert 16 in db_dec2["starting_player_ids"]


def test_current_gameweek_decision_updates_current_squad(decision_test_env: tuple[Path, Path]) -> None:
    db_path, squad_path = decision_test_env

    # Squad at GW3
    gw3_players = list(range(1, 16))
    squad_data = {
        "season": "2026/27",
        "gameweek": 3,
        "free_transfers": 1,
        "bank_tenths": 10,
        "player_ids": gw3_players,
        "purchase_prices_tenths": {str(i): 50 for i in gw3_players},
    }
    squad_path.write_text(json.dumps(squad_data, indent=2), encoding="utf-8")

    # Log decision for GW3 (current gameweek)
    res = log_decision_from_current_squad(
        gameweek=3,
        squad_path=squad_path,
        database_path=db_path,
        transfers=["Player_15:Player_16"],
        captain_id=13,
        vice_captain_id=8,
        overwrite=True,
    )

    assert res["gameweek"] == 3
    assert res["is_past_gameweek"] is False
    assert res["current_squad_updated"] is True

    # Check updated squad file on disk
    updated_raw = json.loads(squad_path.read_text(encoding="utf-8"))
    assert 15 not in updated_raw["player_ids"]
    assert 16 in updated_raw["player_ids"]
    assert "16" in updated_raw["purchase_prices_tenths"]
    assert "15" not in updated_raw["purchase_prices_tenths"]
    assert updated_raw["gameweek"] == 3


def test_cli_past_gameweek_and_squad_players(
    decision_test_env: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path, squad_path = decision_test_env
    monkeypatch.setattr("fpl_manager.cli.DATABASE_PATH", db_path)

    squad_data = {
        "season": "2026/27",
        "gameweek": 3,
        "free_transfers": 1,
        "bank_tenths": 10,
        "player_ids": list(range(1, 15)) + [16],
        "purchase_prices_tenths": {str(i): 50 for i in list(range(1, 15)) + [16]},
    }
    squad_path.write_text(json.dumps(squad_data, indent=2), encoding="utf-8")

    # Squad at GW1 had player 15 instead of 16
    custom_squad = "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15"
    args = [
        "log-decision",
        "--squad", str(squad_path),
        "--gameweek", "1",
        "--squad-players", custom_squad,
        "--captain", "Player_13",
        "--vice-captain", "Player_8",
        "--overwrite",
    ]
    main(args)
    captured = capsys.readouterr().out
    assert "Gameweek 1" in captured
    assert "Past gameweek (audit & evaluation only" in captured


def test_evaluate_past_logged_decision(decision_test_env: tuple[Path, Path]) -> None:
    from fpl_manager.evaluation import evaluate_gameweek_decision

    db_path, squad_path = decision_test_env

    # Squad at GW3
    squad_data = {
        "season": "2026/27",
        "gameweek": 3,
        "free_transfers": 1,
        "bank_tenths": 10,
        "player_ids": list(range(1, 16)),
        "purchase_prices_tenths": {str(i): 50 for i in range(1, 16)},
    }
    squad_path.write_text(json.dumps(squad_data, indent=2), encoding="utf-8")

    # Log decision for past GW2 with custom starters including Player 16
    log_decision_from_current_squad(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        transfers=["Player_15:Player_16"],
        starting_player_ids=[1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 16],
        bench_player_ids=[2, 6, 7, 14],
        captain_id=13,
        vice_captain_id=8,
        overwrite=True,
    )

    # Actual scores for players in GW2
    # Player 13 (C) scores 10 pts -> 20 pts (effective)
    # Other 10 starters score 4 pts each -> 40 pts
    # Total = 60 pts
    actual_scores = {13: 10, 8: 4, 16: 4, 1: 4, 3: 4, 4: 4, 5: 4, 9: 4, 10: 4, 11: 4, 12: 4}
    eval_res = evaluate_gameweek_decision(gameweek=2, actual_scores=actual_scores, database_path=db_path)

    assert eval_res["gameweek"] == 2
    assert eval_res["actual_lineup_score"] == 60
    assert eval_res["captaincy"]["captain_actual_points"] == 10


def test_undo_gameweek_changes(decision_test_env: tuple[Path, Path]) -> None:
    from fpl_manager.decision_log import undo_gameweek_changes
    from fpl_manager.squad_state import load_current_squad

    db_path, squad_path = decision_test_env

    # 1. Log GW 1 decision with base players 1..15
    log_decision_from_current_squad(
        gameweek=1,
        squad_path=squad_path,
        database_path=db_path,
        starting_player_ids=[1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14],
        bench_player_ids=[2, 6, 7, 15],
        captain_id=13,
        vice_captain_id=8,
        overwrite=True,
    )

    # 2. Log GW 2 decision: traded 15 -> 16
    log_decision_from_current_squad(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        transfers=["Player_15:Player_16"],
        starting_player_ids=[1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 16],
        bench_player_ids=[2, 6, 7, 14],
        captain_id=13,
        vice_captain_id=8,
        overwrite=True,
    )

    cur = load_current_squad(squad_path)
    assert 16 in cur.player_ids
    assert 15 not in cur.player_ids

    # 3. Undo GW 2 changes -> revert to GW 1
    res = undo_gameweek_changes(squad_path, gameweek=2, database_path=db_path)
    assert res["success"] is True
    assert res["reverted_to_gameweek"] == 1

    reverted = load_current_squad(squad_path)
    assert 15 in reverted.player_ids
    assert 16 not in reverted.player_ids
    assert reverted.free_transfers == 1

    # GW 2 decision is deleted
    assert get_gameweek_decision(2, database_path=db_path) is None
    # GW 1 decision remains
    assert get_gameweek_decision(1, database_path=db_path) is not None

    # Undoing when no previous gameweek exists raises ValueError
    with pytest.raises(ValueError, match="No previous gameweek is available"):
        undo_gameweek_changes(squad_path, gameweek=1, database_path=db_path)


def test_undo_gameweek_changes_price_preservation_and_no_ft_inflation(decision_test_env: tuple[Path, Path]) -> None:
    from fpl_manager.decision_log import undo_gameweek_changes, compute_expected_free_transfers
    from fpl_manager.squad_state import load_current_squad, save_current_squad, CurrentSquadState

    db_path, squad_path = decision_test_env

    # 1. Setup squad at GW1
    cur = load_current_squad(squad_path)
    squad_1 = CurrentSquadState(
        player_ids=cur.player_ids,
        purchase_prices_tenths=cur.purchase_prices_tenths,
        bank_tenths=cur.bank_tenths,
        free_transfers=1,
        chips_remaining=cur.chips_remaining,
        season=cur.season,
        gameweek=1,
    )
    save_current_squad(squad_path, squad_1)

    log_decision_from_current_squad(
        gameweek=1,
        squad_path=squad_path,
        database_path=db_path,
        starting_player_ids=[1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14],
        bench_player_ids=[2, 6, 7, 15],
        captain_id=13,
        vice_captain_id=8,
        overwrite=True,
    )

    # 2. Log GW 2 with 1 transfer: 15 -> 16 (both FWD, both Team 5)
    log_decision_from_current_squad(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        transfers=["Player_15:Player_16"],
        starting_player_ids=[1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14],
        bench_player_ids=[2, 6, 7, 16],
        captain_id=13,
        vice_captain_id=8,
        overwrite=True,
    )

    # Set custom purchase price for 16 (55 instead of default 60) to test preservation
    cur2 = load_current_squad(squad_path)
    p2 = dict(cur2.purchase_prices_tenths)
    p2[16] = 55
    squad_2 = CurrentSquadState(
        player_ids=cur2.player_ids,
        purchase_prices_tenths=p2,
        bank_tenths=cur2.bank_tenths,
        free_transfers=cur2.free_transfers,
        chips_remaining=cur2.chips_remaining,
        season=cur2.season,
        gameweek=2,
    )
    save_current_squad(squad_path, squad_2)

    # In GW2, 1 transfer was made with 1 FT. Free transfers entering GW3 should be 1.
    assert compute_expected_free_transfers(3, database_path=db_path) == 1

    # 3. In GW 3, make a transfer selling player 16 back for 15
    log_decision_from_current_squad(
        gameweek=3,
        squad_path=squad_path,
        database_path=db_path,
        transfers=["Player_16:Player_15"],
        starting_player_ids=[1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14],
        bench_player_ids=[2, 6, 7, 15],
        captain_id=13,
        vice_captain_id=8,
        overwrite=True,
    )

    # Saving decisions repeatedly for GW3 should NOT inflate free transfers!
    for _ in range(3):
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

    squad_after_saves = load_current_squad(squad_path)
    # FT should not have inflated to 4 or 5!
    assert squad_after_saves.free_transfers <= 1

    # 4. Now Undo GW3 changes!
    res = undo_gameweek_changes(squad_path, gameweek=3, database_path=db_path)
    assert res["success"] is True
    assert res["reverted_to_gameweek"] == 2

    reverted = load_current_squad(squad_path)
    # Player 16 is back in squad
    assert 16 in reverted.player_ids
    # Player 16's purchase price must be 55 (preserved), NOT 60 (snapshot market price)
    assert reverted.purchase_prices_tenths[16] == 55
    # Free transfers must be exactly 1!
    assert reverted.free_transfers == 1

    # 5. Repeated resets do NOT inflate free transfers to 2, 3, 4, 5
    for _ in range(3):
        res2 = undo_gameweek_changes(squad_path, gameweek=3, database_path=db_path)
        assert res2["free_transfers"] == 1
        reverted2 = load_current_squad(squad_path)
        assert reverted2.free_transfers == 1




