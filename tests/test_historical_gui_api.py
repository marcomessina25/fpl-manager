"""Integration tests for historical simulation GUI REST API endpoints (V1.4)."""

import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import urllib.request
import pytest

from src.fpl_manager.gui.server import FPLRequestHandler, ThreadingHTTPServer


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def test_server():
    port = _get_free_port()
    with tempfile.TemporaryDirectory() as td:
        temp_config = Path(td) / "config"
        temp_config.mkdir(parents=True, exist_ok=True)

        class CustomHandler(FPLRequestHandler):
            config_dir = temp_config

        server = ThreadingHTTPServer(("127.0.0.1", port), CustomHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.2)
        base_url = f"http://127.0.0.1:{port}"
        yield base_url, temp_config
        server.shutdown()


def test_api_historical_seasons(test_server) -> None:
    base_url, _ = test_server
    with urllib.request.urlopen(f"{base_url}/api/historical/seasons") as r:
        assert r.status == 200
        data = json.loads(r.read())
        assert "seasons" in data
        assert "2023-24" in data["seasons"]
        assert "2022-23" in data["seasons"]


def test_api_historical_overview_zero_leakage(test_server) -> None:
    base_url, _ = test_server
    with urllib.request.urlopen(f"{base_url}/api/historical/overview?season=2023-24&gameweek=5") as r:
        assert r.status == 200
        data = json.loads(r.read())
        assert data["season"] == "2023-24"
        assert data["gameweek"] == 5
        assert len(data["standings"]) == 20
        assert len(data["past_results"]) > 0
        assert len(data["upcoming_fixtures"]) == 10

        # Assert no score leakage on upcoming fixtures
        for fix in data["upcoming_fixtures"]:
            assert "team_h_score" not in fix
            assert "team_a_score" not in fix


def test_api_historical_simulations_lifecycle(test_server) -> None:
    base_url, _ = test_server

    # 1. Create simulation
    create_req = urllib.request.Request(
        f"{base_url}/api/historical/simulations/create",
        data=json.dumps({
            "session_id": "test_api_sim_01",
            "season": "2023-24",
            "start_gw": 1,
            "starting_strategy": "v1.2.5",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(create_req) as r:
        assert r.status == 200
        created = json.loads(r.read())
        assert created["session_id"] == "test_api_sim_01"
        assert created["current_gw"] == 1
        assert len(created["squad"]) == 15

    # 2. Get recommendations
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/test_api_sim_01/recommendations") as r:
        assert r.status == 200
        recs = json.loads(r.read())
        assert recs["gameweek"] == 1
        assert "predicted_lineup_xp" in recs

    # 3. Step gameweek
    run_req = urllib.request.Request(
        f"{base_url}/api/historical/simulations/test_api_sim_01/run-gw",
        data=json.dumps({}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(run_req) as r:
        assert r.status == 200
        res = json.loads(r.read())
        assert res["resolution"]["gameweek"] == 1
        assert res["resolution"]["net_points"] > 0
        assert res["session"]["current_gw"] == 2

    # 4. Get report
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/test_api_sim_01/report") as r:
        assert r.status == 200
        rep = json.loads(r.read())
        assert rep["session_id"] == "test_api_sim_01"
        assert rep["gameweeks_completed"] == 1
