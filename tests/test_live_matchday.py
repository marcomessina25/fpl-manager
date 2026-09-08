"""Tests for Live Matchday Points & Rank Tracker."""

from contextlib import closing
import json
from pathlib import Path
import pytest

from fpl_manager.decision_log import log_decision_from_current_squad
from fpl_manager.live_matchday import get_live_gameweek_matchday_summary
from fpl_manager.storage import SnapshotStore, utc_timestamp


@pytest.fixture
def live_matchday_env(tmp_path: Path) -> tuple[Path, Path]:
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
            {"id": 2, "name": "Gameweek 2", "deadline_time": "2026-08-22T10:00:00Z", "is_current": True, "finished": False},
        ],
        "elements": [],
    }

    # 15 players:
    # 1, 2: GKP
    # 3, 4, 5, 6, 7: DEF
    # 8, 9, 10, 11, 12: MID
    # 13, 14, 15: FWD
    for p_id in range(1, 16):
        pos_id = 1 if p_id <= 2 else (2 if p_id <= 7 else (3 if p_id <= 12 else 4))
        bootstrap["elements"].append({
            "id": p_id,
            "web_name": f"Player_{p_id}",
            "team": ((p_id - 1) % 5) + 1,
            "element_type": pos_id,
            "now_cost": 50,
            "status": "a",
            "chance_of_playing_next_round": 100,
            "news": "",
            "total_points": 20,
            "selected_by_percent": 20.0,
        })

    # Fixtures: Team 1 vs Team 2 (finished), Team 3 vs Team 4 (finished), Team 5 vs Team 1 (finished)
    fixtures = [
        {"id": 1, "event": 2, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-22T11:30:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 3, "team_a": 4, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-22T14:00:00Z", "finished": True},
        {"id": 3, "event": 2, "team_h": 5, "team_a": 1, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-22T16:30:00Z", "finished": True},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    squad_data = {
        "season": "2026/27",
        "free_transfers": 1,
        "bank_tenths": 10,
        "chips_remaining": ["wildcard", "bench_boost", "triple_captain"],
        "player_ids": list(range(1, 16)),
        "purchase_prices_tenths": {str(i): 50 for i in range(1, 16)},
        "gameweek": 2,
    }
    squad_path.write_text(json.dumps(squad_data, indent=2), encoding="utf-8")

    return db_path, squad_path


def test_live_matchday_basic_score(live_matchday_env: tuple[Path, Path]) -> None:
    db_path, squad_path = live_matchday_env
    store = SnapshotStore(db_path)

    # Save live stats for all players
    # Starters: 1 (GKP), 3,4,5 (DEF), 8,9,10,11 (MID), 13,14,15 (FWD) -> 3-4-3
    # Bench: 2 (GKP), 6 (DEF), 7 (DEF), 12 (MID)
    live_elements = []
    for pid in range(1, 16):
        pts = pid  # each player gets their id as points
        live_elements.append({
            "id": pid,
            "stats": {
                "total_points": pts,
                "minutes": 90,
                "goals_scored": 1 if pid in (13, 14) else 0,
                "assists": 1 if pid == 8 else 0,
                "clean_sheets": 1 if pid <= 5 else 0,
                "goals_conceded": 0,
                "bonus": 2 if pid == 13 else 0,
                "bps": 25,
            }
        })

    store.save_gameweek_scores(2, {"elements": live_elements}, utc_timestamp())

    # Log lineup decision: Captain = 13 (FWD), Vice = 8 (MID)
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    bench = [2, 6, 7, 12]
    log_decision_from_current_squad(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=13,
        vice_captain_id=8,
        transfer_hits=1,  # 1 hit = -4
        overwrite=True,
    )

    summary = get_live_gameweek_matchday_summary(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        save_reports=False,
    )

    assert summary["gameweek"] == 2
    assert summary["transfer_hits"] == 1
    assert summary["hit_cost"] == 4

    # Starters points sum:
    # 1 + 3 + 4 + 5 + 8 + 9 + 10 + 11 + (13*2) + 14 + 15
    # sum of starters = 1 + 3 + 4 + 5 + 8 + 9 + 10 + 11 + 14 + 15 = 80 + 13*2 = 106
    assert summary["gross_points"] == 106
    assert summary["net_points"] == 102
    assert summary["captain"]["id"] == 13
    assert summary["captain"]["multiplier"] == 2
    assert summary["captain"]["promoted_from_vice"] is False
    assert len(summary["autosubs"]) == 0
    assert "Live Score" in summary["markdown"]


def test_live_matchday_gk_autosub(live_matchday_env: tuple[Path, Path]) -> None:
    db_path, squad_path = live_matchday_env
    store = SnapshotStore(db_path)

    # Starter GK (1) played 0 minutes, match finished.
    # Bench GK (2) played 90 minutes and got 7 points.
    live_elements = [
        {"id": 1, "stats": {"total_points": 0, "minutes": 0, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 0}},
        {"id": 2, "stats": {"total_points": 7, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 1, "goals_conceded": 0, "bonus": 1, "bps": 26}},
    ]
    for pid in range(3, 16):
        live_elements.append({
            "id": pid,
            "stats": {"total_points": 3, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 1, "bonus": 0, "bps": 10}
        })
    store.save_gameweek_scores(2, {"elements": live_elements}, utc_timestamp())

    starters = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    bench = [2, 6, 7, 12]
    log_decision_from_current_squad(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=13,
        vice_captain_id=8,
        overwrite=True,
    )

    summary = get_live_gameweek_matchday_summary(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        save_reports=False,
    )

    assert len(summary["autosubs"]) == 1
    sub = summary["autosubs"][0]
    assert sub["out"]["id"] == 1
    assert sub["in"]["id"] == 2
    assert sub["in"]["points"] == 7

    # Starter 1 should be replaced by starter 2 in active starters
    active_starter_ids = [p["id"] for p in summary["starters"]]
    assert 2 in active_starter_ids
    assert 1 not in active_starter_ids


def test_live_matchday_outfield_autosub_formation_legality(live_matchday_env: tuple[Path, Path]) -> None:
    db_path, squad_path = live_matchday_env
    store = SnapshotStore(db_path)

    # Lineup: 3 DEF (3, 4, 5), 4 MID (8, 9, 10, 11), 3 FWD (13, 14, 15)
    # Bench order: Bench 1 = MID 12 (points 6, played 90), Bench 2 = DEF 6 (points 4, played 90), Bench 3 = DEF 7
    # Starter DEF 3 played 0 minutes and match finished.
    # If we sub in MID 12, formation becomes 2 DEF - 5 MID - 3 FWD which is ILLEGAL (min 3 DEF).
    # Autosub must skip MID 12 and sub in DEF 6 instead!
    live_elements = [
        {"id": 1, "stats": {"total_points": 2, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 10}},
        {"id": 2, "stats": {"total_points": 0, "minutes": 0, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 0}},
        {"id": 3, "stats": {"total_points": 0, "minutes": 0, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 0}},  # played 0
        {"id": 4, "stats": {"total_points": 2, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 10}},
        {"id": 5, "stats": {"total_points": 2, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 10}},
        {"id": 6, "stats": {"total_points": 4, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 15}},  # DEF on bench pos 2
        {"id": 7, "stats": {"total_points": 1, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 5}},
        {"id": 8, "stats": {"total_points": 3, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 10}},
        {"id": 9, "stats": {"total_points": 3, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 10}},
        {"id": 10, "stats": {"total_points": 3, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 10}},
        {"id": 11, "stats": {"total_points": 3, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 10}},
        {"id": 12, "stats": {"total_points": 6, "minutes": 90, "goals_scored": 1, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 20}},  # MID on bench pos 1
        {"id": 13, "stats": {"total_points": 5, "minutes": 90, "goals_scored": 1, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 20}},
        {"id": 14, "stats": {"total_points": 5, "minutes": 90, "goals_scored": 1, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 20}},
        {"id": 15, "stats": {"total_points": 5, "minutes": 90, "goals_scored": 1, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 20}},
    ]
    store.save_gameweek_scores(2, {"elements": live_elements}, utc_timestamp())

    starters = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    # Bench: GK (2), MID 12 (1st outfield), DEF 6 (2nd outfield), DEF 7 (3rd outfield)
    bench = [2, 12, 6, 7]

    log_decision_from_current_squad(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=13,
        vice_captain_id=8,
        overwrite=True,
    )

    summary = get_live_gameweek_matchday_summary(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        save_reports=False,
    )

    assert len(summary["autosubs"]) == 1
    sub = summary["autosubs"][0]
    assert sub["out"]["id"] == 3
    # Crucial assertion: player 6 (DEF) was chosen, NOT player 12 (MID), because 3 DEF are required!
    assert sub["in"]["id"] == 6
    assert sub["in"]["points"] == 4


def test_live_matchday_captain_promotion(live_matchday_env: tuple[Path, Path]) -> None:
    db_path, squad_path = live_matchday_env
    store = SnapshotStore(db_path)

    # Captain 13 played 0 minutes and match finished
    # Vice-captain 8 played 90 minutes and got 10 points
    live_elements = [
        {"id": 13, "stats": {"total_points": 0, "minutes": 0, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 0}},
        {"id": 8, "stats": {"total_points": 10, "minutes": 90, "goals_scored": 1, "assists": 1, "clean_sheets": 0, "goals_conceded": 0, "bonus": 3, "bps": 35}},
    ]
    for pid in [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 14, 15]:
        live_elements.append({
            "id": pid,
            "stats": {"total_points": 2, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 10}
        })
    store.save_gameweek_scores(2, {"elements": live_elements}, utc_timestamp())

    starters = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    bench = [2, 6, 7, 12]

    log_decision_from_current_squad(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=13,
        vice_captain_id=8,
        overwrite=True,
    )

    summary = get_live_gameweek_matchday_summary(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        save_reports=False,
    )

    assert summary["captain"]["promoted_from_vice"] is True
    assert summary["captain"]["id"] == 8
    # Vice captain should get 2x points = 20 pts
    assert summary["captain"]["points"] == 20

    cap_starter = next(p for p in summary["starters"] if p["id"] == 8)
    assert cap_starter["points"] == 20
    assert cap_starter["multiplier"] == 2
    assert "CAPTAIN" in cap_starter["role"]


def test_live_matchday_triple_captain_and_bench_boost(live_matchday_env: tuple[Path, Path]) -> None:
    db_path, squad_path = live_matchday_env
    store = SnapshotStore(db_path)

    live_elements = []
    for pid in range(1, 16):
        live_elements.append({
            "id": pid,
            "stats": {"total_points": 5, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 10}
        })
    store.save_gameweek_scores(2, {"elements": live_elements}, utc_timestamp())

    starters = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    bench = [2, 6, 7, 12]

    # 1. Test Triple Captain
    log_decision_from_current_squad(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=13,
        vice_captain_id=8,
        chip_played="triple_captain",
        overwrite=True,
    )

    summary_tc = get_live_gameweek_matchday_summary(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        save_reports=False,
    )
    assert summary_tc["chip_played"] == "triple_captain"
    assert summary_tc["captain"]["multiplier"] == 3
    # Starters: 10 non-cap * 5 = 50, Captain = 5 * 3 = 15 -> 65
    assert summary_tc["gross_points"] == 65

    # 2. Test Bench Boost
    log_decision_from_current_squad(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=13,
        vice_captain_id=8,
        chip_played="bench_boost",
        overwrite=True,
    )

    summary_bb = get_live_gameweek_matchday_summary(
        gameweek=2,
        squad_path=squad_path,
        database_path=db_path,
        save_reports=False,
    )
    assert summary_bb["chip_played"] == "bench_boost"
    # All 15 players count: 14 players * 5 + 1 captain (2x * 5 = 10) = 70 + 10 = 80
    assert summary_bb["gross_points"] == 80
    assert all(b["counted_in_total"] is True for b in summary_bb["bench"])
