"""Tests for FPL Manager GUI server and REST API endpoints."""

import json
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
import pytest

from fpl_manager.cli import main
from fpl_manager.gui.server import create_gui_server, find_available_port
from fpl_manager.squad_state import CurrentSquadState, save_current_squad
from fpl_manager.storage import SnapshotStore, utc_timestamp


@pytest.fixture
def gui_test_server(tmp_path: Path):
    """Starts a real GUI server instance on a local loopback port for testing."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "fpl.sqlite3"

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

    for p_id in range(1, 18):
        pos_id = 1 if p_id <= 2 else (2 if p_id <= 7 else (3 if p_id <= 12 else 4))
        bootstrap["elements"].append({
            "id": p_id,
            "web_name": f"Player_{p_id}",
            "team": 5 if p_id == 16 else (((p_id - 1) % 5) + 1),
            "element_type": pos_id,
            "now_cost": 50,
            "status": "a",
            "total_points": 30,
        })

    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 2, "team_a": 3, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 3, "event": 3, "team_h": 1, "team_a": 4, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    # Create base squad
    base_squad = CurrentSquadState(
        player_ids=tuple(range(1, 16)),
        purchase_prices_tenths={p: 50 for p in range(1, 16)},
        bank_tenths=20,
        free_transfers=1,
        chips_remaining=("wildcard", "freehit", "benchboost", "triplecaptain"),
        season="2026/27",
        gameweek=2,
    )
    save_current_squad(config_dir / "current_squad.json", base_squad)

    # Start server
    server, port = create_gui_server(
        host="127.0.0.1",
        port=9100,
        database_path=db_path,
        config_dir=config_dir,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.05)

    base_url = f"http://127.0.0.1:{port}"
    yield base_url

    server.shutdown()
    server.server_close()


def test_find_available_port() -> None:
    port = find_available_port("127.0.0.1", 9200)
    assert 9200 <= port < 9210


def test_serve_static_files(gui_test_server: str) -> None:
    # Root index.html
    with urllib.request.urlopen(f"{gui_test_server}/") as resp:
        assert resp.status == 200
        assert "text/html" in resp.headers.get("Content-Type", "")
        content = resp.read().decode("utf-8")
        assert "FPL Manager Pro" in content

    # app.css
    with urllib.request.urlopen(f"{gui_test_server}/app.css") as resp:
        assert resp.status == 200
        assert "text/css" in resp.headers.get("Content-Type", "")
        css = resp.read().decode("utf-8")
        assert "pitch" in css

    # app.js
    with urllib.request.urlopen(f"{gui_test_server}/app.js") as resp:
        assert resp.status == 200
        assert "javascript" in resp.headers.get("Content-Type", "")
        js = resp.read().decode("utf-8")
        assert "loadTeams" in js


def test_api_health(gui_test_server: str) -> None:
    with urllib.request.urlopen(f"{gui_test_server}/api/health") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "ok"
        assert "version" in data


def test_api_teams_crud(gui_test_server: str) -> None:
    # 1. GET /api/teams
    with urllib.request.urlopen(f"{gui_test_server}/api/teams") as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["active_team_id"] == "default"
        assert len(data["teams"]) >= 1

    # 2. POST /api/teams/create
    create_req = urllib.request.Request(
        f"{gui_test_server}/api/teams/create",
        data=json.dumps({"name": "GUI Dream Team", "manager": "Test Manager", "activate": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(create_req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        assert res["team_id"] == "gui-dream-team"
        assert res["is_active"] is True

    # Verify active team switched
    with urllib.request.urlopen(f"{gui_test_server}/api/teams") as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["active_team_id"] == "gui-dream-team"

    # 3. POST /api/teams/switch back to default
    switch_req = urllib.request.Request(
        f"{gui_test_server}/api/teams/switch",
        data=json.dumps({"team_id": "default"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(switch_req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        assert res["team_id"] == "default"

    # 4. DELETE /api/teams/gui-dream-team
    del_req = urllib.request.Request(
        f"{gui_test_server}/api/teams/gui-dream-team",
        method="DELETE",
    )
    with urllib.request.urlopen(del_req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        assert res["deleted_team_id"] == "gui-dream-team"


def test_api_squad_and_lineup(gui_test_server: str) -> None:
    # GET /api/squad
    with urllib.request.urlopen(f"{gui_test_server}/api/squad") as resp:
        squad = json.loads(resp.read().decode("utf-8"))
        assert squad["squad_size"] == 15
        assert squad["financials"]["bank_tenths"] == 20

    # GET /api/lineup
    with urllib.request.urlopen(f"{gui_test_server}/api/lineup") as resp:
        lineup = json.loads(resp.read().decode("utf-8"))
        assert len(lineup["starters"]) == 11
        assert len(lineup["bench"]) == 4
        assert lineup["captain"] is not None
        assert lineup["vice_captain"] is not None


def test_api_transfers_and_wildcard(gui_test_server: str) -> None:
    # GET /api/transfers
    with urllib.request.urlopen(f"{gui_test_server}/api/transfers?transfers=1") as resp:
        tx = json.loads(resp.read().decode("utf-8"))
        assert "top_suggestions" in tx

    # GET /api/wildcard
    with urllib.request.urlopen(f"{gui_test_server}/api/wildcard") as resp:
        wc = json.loads(resp.read().decode("utf-8"))
        assert len(wc["starters"]) == 11
        assert len(wc["bench"]) == 4


def test_api_plan_and_chips(gui_test_server: str) -> None:
    # GET /api/plan
    with urllib.request.urlopen(f"{gui_test_server}/api/plan?horizon=3") as resp:
        plan = json.loads(resp.read().decode("utf-8"))
        assert plan["best_plan"] is not None

    # GET /api/chips
    with urllib.request.urlopen(f"{gui_test_server}/api/chips") as resp:
        chips = json.loads(resp.read().decode("utf-8"))
        assert "available_chips" in chips
        assert "recommended_schedule" in chips


def test_api_decisions_and_evaluation(gui_test_server: str) -> None:
    # POST /api/decisions
    dec_body = {
        "gameweek": 2,
        "starters": [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14],
        "bench": [2, 6, 7, 15],
        "captain": 13,
        "vice_captain": 8,
        "notes": "Test GUI decision",
        "overwrite": True,
    }
    post_req = urllib.request.Request(
        f"{gui_test_server}/api/decisions",
        data=json.dumps(dec_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(post_req) as resp:
        dec = json.loads(resp.read().decode("utf-8"))
        assert dec["gameweek"] == 2
        assert dec["captain_id"] == 13

    # GET /api/decisions
    with urllib.request.urlopen(f"{gui_test_server}/api/decisions") as resp:
        res = json.loads(resp.read().decode("utf-8"))
        assert len(res["decisions"]) >= 1

    # GET /api/evaluate
    with urllib.request.urlopen(f"{gui_test_server}/api/evaluate?gameweek=2") as resp:
        eval_res = json.loads(resp.read().decode("utf-8"))
        assert eval_res["gameweek"] == 2
        assert eval_res["captaincy"]["captain_id"] == 13


def test_api_players_search(gui_test_server: str) -> None:
    with urllib.request.urlopen(f"{gui_test_server}/api/players?search=Player_1") as resp:
        res = json.loads(resp.read().decode("utf-8"))
        assert len(res["players"]) >= 1


def test_api_players_all(gui_test_server: str) -> None:
    with urllib.request.urlopen(f"{gui_test_server}/api/players?all=true") as resp:
        res = json.loads(resp.read().decode("utf-8"))
        assert len(res["players"]) == 17
        sample = res["players"][0]
        assert "price_fmt" in sample
        assert "position" in sample


def test_api_execute_transfers(gui_test_server: str) -> None:
    body = {
        "transfers": [{"outgoing_id": 15, "incoming_id": 16}],
        "gameweek": 2,
    }
    req = urllib.request.Request(
        f"{gui_test_server}/api/transfers/execute",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        res = json.loads(resp.read().decode("utf-8"))
        assert res["success"] is True
        assert res["free_transfers"] == 0
        assert 16 in res["new_player_ids"]
        assert 15 not in res["new_player_ids"]


def test_api_historical_logged_lineup(gui_test_server: str) -> None:
    # 1. Log a custom past gameweek decision for GW2
    dec_body = {
        "gameweek": 2,
        "starters": [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14],
        "bench": [2, 6, 7, 15],
        "captain": 13,
        "vice_captain": 8,
        "actual_points": 68,
        "notes": "Historical GW2 logged state",
        "overwrite": True,
    }
    post_req = urllib.request.Request(
        f"{gui_test_server}/api/decisions",
        data=json.dumps(dec_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(post_req) as resp:
        assert resp.status == 200

    # 2. GET /api/lineup?gameweek=2 -> returns logged matchday state
    with urllib.request.urlopen(f"{gui_test_server}/api/lineup?gameweek=2") as resp:
        lineup = json.loads(resp.read().decode("utf-8"))
        assert lineup["is_logged"] is True
        assert lineup["gameweek"] == 2
        assert lineup["actual_points"] == 68
        assert lineup["captain"]["id"] == 13
        assert lineup["vice_captain"]["id"] == 8
        assert len(lineup["starters"]) == 11
        assert len(lineup["bench"]) == 4
        starter_ids = [p["id"] for p in lineup["starters"]]
        assert starter_ids == [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]

    # 3. GET /api/lineup?gameweek=2&mode=model -> returns model recommendation
    with urllib.request.urlopen(f"{gui_test_server}/api/lineup?gameweek=2&mode=model") as resp:
        model_lineup = json.loads(resp.read().decode("utf-8"))
        assert model_lineup["is_logged"] is False
        assert model_lineup["has_logged_decision"] is True
        assert len(model_lineup["starters"]) == 11

    # 4. GET /api/squad?gameweek=2 -> reconstructs squad from logged decision
    with urllib.request.urlopen(f"{gui_test_server}/api/squad?gameweek=2") as resp:
        squad_rep = json.loads(resp.read().decode("utf-8"))
        assert squad_rep["is_logged"] is True
        assert squad_rep["gameweek"] == 2
        assert squad_rep["squad_size"] == 15


def test_api_decisions_undo(gui_test_server: str) -> None:
    # First, log GW 1 decision with base squad 1..15
    gw1_body = {
        "gameweek": 1,
        "starters": [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14],
        "bench": [2, 6, 7, 15],
        "captain": 13,
        "vice_captain": 8,
        "overwrite": True,
    }
    req1 = urllib.request.Request(
        f"{gui_test_server}/api/decisions",
        data=json.dumps(gw1_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req1) as resp:
        assert resp.status == 200

    # Execute trade in GW 2: 15 -> 16
    tx_body = {
        "transfers": [{"outgoing_id": 15, "incoming_id": 16}],
        "gameweek": 2,
    }
    req_tx = urllib.request.Request(
        f"{gui_test_server}/api/transfers/execute",
        data=json.dumps(tx_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req_tx) as resp:
        assert resp.status == 200

    # Call undo endpoint for GW 2
    undo_body = {"gameweek": 2}
    req_undo = urllib.request.Request(
        f"{gui_test_server}/api/decisions/undo",
        data=json.dumps(undo_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req_undo) as resp:
        assert resp.status == 200
        undo_res = json.loads(resp.read().decode("utf-8"))
        assert undo_res["success"] is True
        assert undo_res["reverted_to_gameweek"] == 1
        assert 15 in undo_res["player_ids"]
        assert 16 not in undo_res["player_ids"]


def test_api_plan_steps(gui_test_server: str) -> None:
    with urllib.request.urlopen(f"{gui_test_server}/api/plan?horizon=3") as resp:
        assert resp.status == 200
        plan = json.loads(resp.read().decode("utf-8"))
        best = plan["best_plan"]
        assert best is not None
        assert "steps" in best
        assert "gameweek_steps" in best
        assert len(best["steps"]) == 3
        assert "cumulative_net_xp" in best
        first_step = best["steps"][0]
        assert "gameweek" in first_step
        assert "lineup_xp" in first_step


def test_api_player_details(gui_test_server: str) -> None:
    with urllib.request.urlopen(f"{gui_test_server}/api/player?id=1&gameweek=2") as resp:
        assert resp.status == 200
        p = json.loads(resp.read().decode("utf-8"))
        assert p["id"] == 1
        assert p["name"] == "Player_1"
        assert p["team_short"] == "ARS"
        assert p["position"] == "Goalkeeper"
        assert p["pos_abbr"] == "GKP"
        assert p["price_fmt"] == "£5.0m"
        assert "expected_goals" in p
        assert "expected_assists" in p
        assert "expected_points" in p
        assert "fixtures" in p
        assert len(p["fixtures"]) > 0


def test_api_wildcard_apply(gui_test_server: str) -> None:
    new_squad = list(range(1, 15)) + [16]
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]
    bench = [2, 6, 7, 16]
    body = {
        "gameweek": 2,
        "mode": "wildcard",
        "squad_ids": new_squad,
        "starter_ids": starters,
        "bench_ids": bench,
        "captain_id": 13,
        "vice_captain_id": 8,
        "bank_tenths": 15,
    }
    req = urllib.request.Request(
        f"{gui_test_server}/api/wildcard/apply",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        res = json.loads(resp.read().decode("utf-8"))
        assert res["success"] is True
        assert res["mode"] == "wildcard"
        assert 16 in res["squad_player_ids"]
        assert 15 not in res["squad_player_ids"]

    # Verify updated squad in /api/squad
    with urllib.request.urlopen(f"{gui_test_server}/api/squad") as resp:
        squad_rep = json.loads(resp.read().decode("utf-8"))
        pids = [p["id"] for p in squad_rep["players"]]
        assert 16 in pids
        assert 15 not in pids

    # Verify decision logged with chip_played = 'wildcard'
    with urllib.request.urlopen(f"{gui_test_server}/api/decisions?gameweek=2") as resp:
        dec_resp = json.loads(resp.read().decode("utf-8"))
        dec = dec_resp["decision"]
        assert dec is not None
        assert dec["chip_played"] == "wildcard"


def test_cli_gui_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["gui", "--help"])
    assert exc.value.code == 0
    out, _ = capsys.readouterr()
    assert "--port" in out
    assert "--no-browser" in out
