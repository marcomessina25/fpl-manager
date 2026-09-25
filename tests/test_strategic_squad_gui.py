"""Tests for Strategic Squad Studio GUI endpoints in FPL Manager."""

import json
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
import pytest

from fpl_manager.gui.server import create_gui_server
from fpl_manager.squad_state import CurrentSquadState, load_current_squad, save_current_squad
from fpl_manager.storage import SnapshotStore, utc_timestamp


@pytest.fixture
def strategic_gui_server(tmp_path: Path):
    """Starts a real GUI server on a local loopback port for testing strategic squad endpoints."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "fpl.sqlite3"

    store = SnapshotStore(db_path)
    store.initialize()

    teams = [
        {"id": 1, "name": "Arsenal", "short_name": "ARS"},
        {"id": 2, "name": "Liverpool", "short_name": "LIV"},
        {"id": 3, "name": "Manchester City", "short_name": "MCI"},
        {"id": 4, "name": "Chelsea", "short_name": "CHE"},
        {"id": 5, "name": "Tottenham", "short_name": "TOT"},
        {"id": 6, "name": "Aston Villa", "short_name": "AVL"},
    ]

    elements = []
    # 4 GKP (pos 1), 10 DEF (pos 2), 10 MID (pos 3), 6 FWD (pos 4) = 30 players
    positions = [1] * 4 + [2] * 10 + [3] * 10 + [4] * 6
    for idx, pos_id in enumerate(positions, 1):
        team_id = ((idx - 1) % len(teams)) + 1
        elements.append({
            "id": idx,
            "web_name": f"P{idx}_{pos_id}",
            "team": team_id,
            "element_type": pos_id,
            "now_cost": 50,  # 5.0m each
            "status": "a",
            "total_points": 50 + idx,
            "form": "4.5",
            "ep_this": "5.0",
            "ep_next": "5.0",
        })

    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 2, "team_a": 3, "team_h_difficulty": 2, "team_a_difficulty": 4, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 3, "event": 3, "team_h": 3, "team_a": 4, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 4, "event": 4, "team_h": 5, "team_a": 6, "team_h_difficulty": 2, "team_a_difficulty": 3, "kickoff_time": "2026-09-10T15:00:00Z", "finished": False},
        {"id": 5, "event": 5, "team_h": 1, "team_a": 6, "team_h_difficulty": 2, "team_a_difficulty": 4, "kickoff_time": "2026-09-17T15:00:00Z", "finished": False},
    ]

    bootstrap = {"teams": teams, "elements": elements}
    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    # Initial 15-man squad: 2 GKP, 5 DEF, 5 MID, 3 FWD
    init_pids = tuple([1, 2] + list(range(5, 10)) + list(range(15, 20)) + list(range(25, 28)))
    base_squad = CurrentSquadState(
        player_ids=init_pids,
        purchase_prices_tenths={p: 50 for p in init_pids},
        bank_tenths=250,
        free_transfers=1,
        chips_remaining=("wildcard", "freehit", "benchboost", "triplecaptain"),
        season="2026/27",
        gameweek=2,
    )
    save_current_squad(config_dir / "current_squad.json", base_squad)

    server, port = create_gui_server(
        host="127.0.0.1",
        port=9400,
        database_path=db_path,
        config_dir=config_dir,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)

    base_url = f"http://127.0.0.1:{port}"
    yield {
        "url": base_url,
        "config_dir": config_dir,
        "db_path": db_path,
    }

    server.shutdown()
    server.server_close()


def test_api_strategic_squad_config(strategic_gui_server: dict) -> None:
    url = strategic_gui_server["url"]
    with urllib.request.urlopen(f"{url}/api/strategic-squad/config") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "modes" in data
        assert "initial" in data["modes"]
        assert "wildcard" in data["modes"]
        assert "free_hit" in data["modes"]
        assert "strategies" in data
        assert "balanced" in data["strategies"]
        assert "ceiling" in data["strategies"]
        assert "maximum_ev" in data["strategies"]
        assert "players" in data
        assert len(data["players"]) == 30
        first_p = data["players"][0]
        assert "id" in first_p
        assert "name" in first_p
        assert "position" in first_p
        assert "pos_abbr" in first_p
        assert "price_fmt" in first_p


def test_api_strategic_squad_get(strategic_gui_server: dict) -> None:
    url = strategic_gui_server["url"]
    with urllib.request.urlopen(f"{url}/api/strategic-squad?mode=initial&horizon=4&strategy=balanced") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["mode"] == "initial"
        assert len(data["squad"]) == 15
        assert len(data["starters"]) == 11
        assert len(data["bench"]) == 4
        assert "captain" in data
        assert "candidates" in data
        assert len(data["candidates"]) >= 1


def test_api_strategic_squad_get_with_constraints(strategic_gui_server: dict) -> None:
    url = strategic_gui_server["url"]
    # Lock player 3 (GKP) and exclude player 1 (GKP)
    with urllib.request.urlopen(f"{url}/api/strategic-squad?mode=initial&lock=3&exclude=1") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        squad_ids = [p["id"] for p in data["squad"]]
        assert 3 in squad_ids
        assert 1 not in squad_ids


def test_api_strategic_squad_optimize_post(strategic_gui_server: dict) -> None:
    url = strategic_gui_server["url"]
    payload = {
        "mode": "wildcard",
        "horizon": 3,
        "strategy": "ceiling",
        "budget": 100.0,
        "locked_player_ids": [4],
        "excluded_player_ids": [2],
        "preferred_player_ids": [6],
    }
    req = urllib.request.Request(
        f"{url}/api/strategic-squad/optimize",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["mode"] == "wildcard"
        squad_ids = [p["id"] for p in data["squad"]]
        assert 4 in squad_ids
        assert 2 not in squad_ids


def test_api_strategic_squad_reoptimize_post(strategic_gui_server: dict) -> None:
    url = strategic_gui_server["url"]
    # Step 1: get a baseline candidate
    with urllib.request.urlopen(f"{url}/api/strategic-squad?mode=initial&horizon=3") as resp:
        base_data = json.loads(resp.read().decode("utf-8"))
        prev_cand = base_data.get("selected_candidate") or base_data

    # Step 2: reoptimize with an extra locked player
    p_to_lock = 10
    payload = {
        "mode": "initial",
        "horizon": 3,
        "strategy": "balanced",
        "locked_player_ids": [p_to_lock],
        "excluded_player_ids": [],
        "preferred_player_ids": [],
        "previous_candidate": prev_cand,
    }
    req = urllib.request.Request(
        f"{url}/api/strategic-squad/reoptimize",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "constraint_impact" in data
            assert "opportunity_cost" in data["constraint_impact"]
            squad_ids = [p["id"] for p in data["squad"]]
            assert p_to_lock in squad_ids
    except urllib.error.HTTPError as err:
        err_msg = err.read().decode("utf-8")
        pytest.fail(f"HTTPError {err.code}: {err_msg}")


def test_api_strategic_squad_apply_post(strategic_gui_server: dict) -> None:
    url = strategic_gui_server["url"]
    config_dir = strategic_gui_server["config_dir"]

    # Request an initial squad
    with urllib.request.urlopen(f"{url}/api/strategic-squad?mode=initial") as resp:
        cand_data = json.loads(resp.read().decode("utf-8"))

    apply_payload = {
        "mode": "initial",
        "gameweek": 1,
        "candidate": cand_data,
        "season": "2026/27",
    }
    req = urllib.request.Request(
        f"{url}/api/strategic-squad/apply",
        data=json.dumps(apply_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        apply_res = json.loads(resp.read().decode("utf-8"))
        assert apply_res["success"] is True
        assert apply_res["mode"] == "initial"

    # Verify current squad file is updated
    updated_squad = load_current_squad(config_dir / "current_squad.json")
    assert len(updated_squad.player_ids) == 15
    for pid in [p["id"] for p in cand_data["squad"]]:
        assert pid in updated_squad.player_ids
