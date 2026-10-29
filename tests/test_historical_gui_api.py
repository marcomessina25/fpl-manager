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


def test_api_historical_strategic_squad_lifecycle(test_server) -> None:
    base_url, _ = test_server

    # 1. Test /api/strategic-squad/config for historical season 2023-24
    with urllib.request.urlopen(f"{base_url}/api/strategic-squad/config?season=2023-24&gameweek=1") as r:
        assert r.status == 200
        cfg = json.loads(r.read())
        assert cfg["season"] == "2023-24"
        assert cfg["current_gameweek"] == 1
        assert len(cfg["players"]) > 500
        # Verify historical players from 2023-24 exist
        player_names = {p["name"] for p in cfg["players"]}
        assert "Erling Haaland" in player_names
        assert "Harry Kane" in player_names  # Kane was registered before departure in 2023-24 GW1

    # 2. Test /api/strategic-squad/optimize for historical season
    opt_req = urllib.request.Request(
        f"{base_url}/api/strategic-squad/optimize",
        data=json.dumps({
            "season": "2023-24",
            "gameweek": 1,
            "mode": "initial",
            "horizon": 5,
            "strategy": "balanced",
            "budget": 100.0,
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(opt_req) as r:
        assert r.status == 200
        opt_res = json.loads(r.read())
        assert opt_res["season"] == "2023-24"
        assert opt_res["mode"] == "initial"
        assert len(opt_res["squad"]) == 15
        assert len(opt_res["starters"]) == 11
        assert len(opt_res["bench"]) == 4
        assert opt_res["total_cost_tenths"] <= 1000
        assert "strategic_candidates" in opt_res

    # 3. Test /api/strategic-squad/reoptimize for historical season
    reopt_req = urllib.request.Request(
        f"{base_url}/api/strategic-squad/reoptimize",
        data=json.dumps({
            "season": "2023-24",
            "gameweek": 1,
            "mode": "initial",
            "horizon": 5,
            "strategy": "balanced",
            "budget": 100.0,
            "previous_candidate": opt_res["selected_candidate"],
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(reopt_req) as r:
        assert r.status == 200
        reopt_res = json.loads(r.read())
        assert len(reopt_res["squad"]) == 15
        assert "constraint_impact" in reopt_res

    # 4. Test /api/strategic-squad/apply into active historical simulation
    create_req = urllib.request.Request(
        f"{base_url}/api/historical/simulations/create",
        data=json.dumps({
            "session_id": "test_strat_sim_01",
            "season": "2023-24",
            "start_gw": 1,
            "starting_strategy": "v1.2.5",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(create_req) as r:
        assert r.status == 200

    apply_req = urllib.request.Request(
        f"{base_url}/api/strategic-squad/apply",
        data=json.dumps({
            "season": "2023-24",
            "session_id": "test_strat_sim_01",
            "mode": "initial",
            "gameweek": 1,
            "candidate": opt_res["selected_candidate"],
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(apply_req) as r:
        assert r.status == 200
        apply_res = json.loads(r.read())
        assert apply_res["success"] is True
        assert apply_res["session_id"] == "test_strat_sim_01"
        assert len(apply_res["squad"]) == 15


def test_api_historical_plan_and_transfers_parity(test_server) -> None:
    base_url, _ = test_server

    # Create a historical simulation
    sid = "test_parity_sim_01"
    create_req = urllib.request.Request(
        f"{base_url}/api/historical/simulations/create",
        data=json.dumps({
            "session_id": sid,
            "season": "2023-24",
            "start_gw": 1,
            "starting_strategy": "v1.2.5",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(create_req) as r:
        assert r.status == 200

    # Test /api/transfers combinatorial solve with session_id (should not be capped at 5)
    with urllib.request.urlopen(f"{base_url}/api/transfers?session_id={sid}&transfers=1&gameweeks=3&risk=balanced&engine=v1.3.5") as r:
        assert r.status == 200
        tx_data = json.loads(r.read())
        assert "top_suggestions" in tx_data
        # Historical time machine must not cap suggestions to 5 anymore
        assert len(tx_data["top_suggestions"]) > 5
        assert len(tx_data["top_suggestions"]) <= 30
        first_opt = tx_data["top_suggestions"][0]
        assert "outgoing" in first_opt
        assert "incoming" in first_opt
        assert "lineup_xp_delta" in first_opt
        assert "reason_breakdown" in first_opt
        assert "transfer_reason_breakdown" in tx_data

    # Test /api/transfers with explicit limit/max_results query parameter
    with urllib.request.urlopen(f"{base_url}/api/transfers?session_id={sid}&transfers=1&gameweeks=3&limit=8") as r:
        assert r.status == 200
        tx_data_lim = json.loads(r.read())
        assert len(tx_data_lim["top_suggestions"]) == 8

    # Test /api/plan with session_id (verifying fix for Planner error: 'id')
    with urllib.request.urlopen(f"{base_url}/api/plan?session_id={sid}&horizon=3&risk=balanced&no_hits=true") as r:
        assert r.status == 200
        plan_data = json.loads(r.read())
        assert "best_plan" in plan_data
        best = plan_data["best_plan"]
        assert "gameweek_steps" in best
        assert len(best["gameweek_steps"]) == 3
        step0 = best["gameweek_steps"][0]
        assert "gameweek" in step0
        assert step0["gameweek"] == 1
        assert "captain" in step0
        assert "lineup_xp" in step0

    # Test /api/historical/simulations/<sid>/chips (verifying full deployment roadmap)
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}/chips?start_gw=1") as r:
        assert r.status == 200
        chips_data = json.loads(r.read())
        assert "recommended_schedule" in chips_data
        assert chips_data["segment"] in ("1-19", "1 - 19")
        assert len(chips_data["recommended_schedule"]) > 0


def test_api_historical_decisions_isolation(test_server) -> None:
    base_url, _ = test_server

    sid = "test_decisions_sim_01"
    create_req = urllib.request.Request(
        f"{base_url}/api/historical/simulations/create",
        data=json.dumps({
            "session_id": sid,
            "season": "2023-24",
            "start_gw": 1,
            "starting_strategy": "v1.2.5",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(create_req) as r:
        assert r.status == 200

    # Initial decision is created on squad initialization
    with urllib.request.urlopen(f"{base_url}/api/decisions?session_id={sid}") as r:
        assert r.status == 200
        d_init = json.loads(r.read())
        assert len(d_init["decisions"]) == 1
        assert d_init["decisions"][0]["gameweek"] == 1

    # Log a decision for this simulation session
    log_req = urllib.request.Request(
        f"{base_url}/api/decisions",
        data=json.dumps({
            "session_id": sid,
            "gameweek": 1,
            "captain": "Erling Haaland",
            "vice_captain": "Bukayo Saka",
            "chip": "3xc",
            "notes": "Historical test captaincy",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(log_req) as r:
        assert r.status == 200
        log_res = json.loads(r.read())
        assert log_res["success"] is True

    # Retrieve decisions for this session
    with urllib.request.urlopen(f"{base_url}/api/decisions?session_id={sid}") as r:
        assert r.status == 200
        d_res = json.loads(r.read())
        assert len(d_res["decisions"]) == 1
        dec = d_res["decisions"][0]
        assert dec["gameweek"] == 1
        assert dec["captain_name"] == "Erling Haaland"
        assert dec["vice_captain_name"] == "Bukayo Saka"
        assert dec["chip_played"] == "triple_captain"
        assert dec["notes"] == "Historical test captaincy"


def test_api_strategic_squad_apply_wildcard_historical(test_server) -> None:
    base_url, _ = test_server
    sid = "test_strat_wildcard_sim"

    # 1. Create simulation session
    create_req = urllib.request.Request(
        f"{base_url}/api/historical/simulations/create",
        data=json.dumps({
            "session_id": sid,
            "season": "2023-24",
            "start_gw": 1,
            "starting_strategy": "v1.2.5",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(create_req) as r:
        assert r.status == 200

    # Verify initial squad selection decision logged for GW1
    with urllib.request.urlopen(f"{base_url}/api/decisions?session_id={sid}") as r:
        assert r.status == 200
        d_res = json.loads(r.read())
        assert len(d_res["decisions"]) == 1
        assert "Initial squad selection" in d_res["decisions"][0]["notes"]

    # Run GW1
    with urllib.request.urlopen(urllib.request.Request(
        f"{base_url}/api/historical/simulations/{sid}/run-gw",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )) as r:
        assert r.status == 200

    # Now at GW2. Fetch session data
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}") as r:
        sess_data = json.loads(r.read())
        assert sess_data["current_gw"] == 2
        orig_squad = [p["player_id"] for p in sess_data["squad"]]

    # Fetch snapshot players to create an overhauled wildcard squad
    from fpl_manager.historical.snapshots import build_historical_snapshot
    from pathlib import Path
    snap = build_historical_snapshot(Path("data/historical/2023-24"), 2)
    # Pick a legal replacement for a defender
    orig_bench = [p["player_id"] for p in sess_data["squad"] if p["is_bench"]]
    out_id = orig_bench[0]
    out_p = next(p for p in snap.players if p.player_id == out_id)
    rem_ids = [pid for pid in orig_squad if pid != out_id]
    rem_team_counts: dict[int, int] = {}
    for pid in rem_ids:
        tp = next(p for p in snap.players if p.player_id == pid)
        rem_team_counts[tp.team_id] = rem_team_counts.get(tp.team_id, 0) + 1
    cand_p = next(
        p for p in snap.players
        if p.position == out_p.position
        and p.player_id not in orig_squad
        and p.price_tenths <= out_p.price_tenths + sess_data.get("bank_tenths", 0)
        and rem_team_counts.get(p.team_id, 0) < 3
    )

    new_squad_ids = [cand_p.player_id if pid == out_id else pid for pid in orig_squad]
    starters = [p for p in sess_data["squad"] if p["is_starter"]]
    bench = [p for p in sess_data["squad"] if p["is_bench"]]
    new_bench = [cand_p.player_id if p["player_id"] == out_id else p["player_id"] for p in bench]

    apply_payload = {
        "session_id": sid,
        "mode": "wildcard",
        "gameweek": 2,
        "season": "2023-24",
        "candidate": {
            "player_ids": new_squad_ids,
            "starters": [{"id": p["player_id"]} for p in starters],
            "bench": [{"id": pid} for pid in new_bench],
            "captain": {"id": starters[0]["player_id"]},
            "vice_captain": {"id": starters[1]["player_id"]},
            "bank_remaining_tenths": 5,
            "strategy": "balanced",
            "predicted_lineup_xp": 55.5,
        },
    }

    # Apply wildcard squad from Strategic Studio
    apply_req = urllib.request.Request(
        f"{base_url}/api/strategic-squad/apply",
        data=json.dumps(apply_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(apply_req) as r:
        assert r.status == 200
        apply_res = json.loads(r.read())
        assert apply_res["success"] is True
        assert apply_res["active_chip"] == "wildcard_1"
        assert len(apply_res["transfers_staged"]) == 1

    # Verify decision logger shows Wildcard for GW2
    with urllib.request.urlopen(f"{base_url}/api/decisions?session_id={sid}") as r:
        d_res = json.loads(r.read())
        gw2_dec = next((d for d in d_res["decisions"] if d["gameweek"] == 2), None)
        assert gw2_dec is not None
        assert gw2_dec["chip_played"] == "wildcard_1"
        assert len(gw2_dec["transfers"]) == 1

    # Run GW2 matchday
    with urllib.request.urlopen(urllib.request.Request(
        f"{base_url}/api/historical/simulations/{sid}/run-gw",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )) as r:
        res = json.loads(r.read())
        gw2_res = res["resolution"]
        assert gw2_res["chip_used"] == "wildcard_1"
        assert gw2_res["transfer_hits"] == 0
        assert len(gw2_res["transfers_executed"]) == 1

    # Verify wildcard_1 was consumed in session state
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}") as r:
        final_sess = json.loads(r.read())
        assert "wildcard_1" not in final_sess["chips_remaining"]
        assert final_sess["chips_used"].get("wildcard_1") == 2
        assert final_sess["active_chip"] is None


def test_api_transfers_staged_awareness_and_idempotency(test_server) -> None:
    """Validate that API transfer staging is idempotent and that GET /api/transfers evaluates effective staged squad."""
    base_url, _ = test_server
    sid = "test_staged_aware_sim"

    # Create simulation
    create_req = urllib.request.Request(
        f"{base_url}/api/historical/simulations/create",
        data=json.dumps({
            "session_id": sid,
            "season": "2023-24",
            "start_gw": 1,
            "starting_strategy": "v1.2.5",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(create_req) as r:
        assert r.status == 200

    # Get session squad
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}") as r:
        sess = json.loads(r.read())
        squad = sess["squad"]
        squad_ids = {p["id"] for p in squad}
        out_player = squad[0]

    # Find same position replacement from pool from same club (safe for 3-player quota)
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}/players") as r:
        pool_data = json.loads(r.read())
        pool_players = pool_data["players"]
        cand = next(
            p for p in pool_players
            if p["position"] == out_player["position"]
            and p["id"] not in squad_ids
            and p["price_tenths"] <= out_player["selling_price_tenths"]
            and p["team_id"] == out_player["team_id"]
        )

    # 1. Stage transfer via POST
    tx_req = urllib.request.Request(
        f"{base_url}/api/historical/simulations/{sid}/transfers",
        data=json.dumps({"out_id": out_player["id"], "in_id": cand["id"]}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(tx_req) as r:
        assert r.status == 200
        res = json.loads(r.read())
        assert len(res["transfers_staged"]) == 1

    # 2. Stage SAME transfer again (assert idempotency, does not error out)
    tx_req2 = urllib.request.Request(
        f"{base_url}/api/historical/simulations/{sid}/transfers",
        data=json.dumps({"out_id": out_player["id"], "in_id": cand["id"]}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(tx_req2) as r:
        assert r.status == 200
        res2 = json.loads(r.read())
        assert len(res2["transfers_staged"]) == 1

    # 3. Query GET /api/transfers with session_id
    with urllib.request.urlopen(f"{base_url}/api/transfers?session_id={sid}&transfers=1&gameweeks=3&risk=neutral") as r:
        assert r.status == 200
        tx_data = json.loads(r.read())
        assert "transfers_staged" in tx_data
        assert len(tx_data["transfers_staged"]) == 1
        # The solver must NOT suggest the already staged move
        top = tx_data.get("top_suggestions", [])
        for sugg in top:
            outs = [o["id"] for o in sugg["outgoing"]]
            ins = [i["id"] for i in sugg["incoming"]]
            # Cannot propose selling out_player to buy cand again
            assert not (out_player["id"] in outs and cand["id"] in ins)


def test_api_historical_lineup_navigation(test_server) -> None:
    base_url, _ = test_server
    sid = "test_lineup_nav_sim_01"

    create_req = urllib.request.Request(
        f"{base_url}/api/historical/simulations/create",
        data=json.dumps({
            "session_id": sid,
            "season": "2023-24",
            "start_gw": 1,
            "starting_strategy": "v1.2.5",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(create_req) as r:
        assert r.status == 200

    # 1. At GW1 (unplayed), query lineup for GW1
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}/lineup?gw=1") as r:
        assert r.status == 200
        l1 = json.loads(r.read())
        assert l1["gameweek"] == 1
        assert l1["is_past"] is False
        assert l1["gross_points"] is None
        assert len(l1["starters"]) == 11
        assert len(l1["bench"]) == 4
        # At unplayed GW1, players have expected_points (xP)
        for p in l1["starters"]:
            assert "expected_points" in p

    # 2. Advance to GW2
    run_req = urllib.request.Request(
        f"{base_url}/api/historical/simulations/{sid}/run-gw",
        data=json.dumps({}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(run_req) as r:
        assert r.status == 200
        res = json.loads(r.read())
        assert res["resolution"]["gameweek"] == 1

    # 3. Now session is at GW2. Query past GW1 lineup
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}/lineup?gw=1") as r:
        assert r.status == 200
        l1_past = json.loads(r.read())
        assert l1_past["gameweek"] == 1
        assert l1_past["is_past"] is True
        assert l1_past["gross_points"] is not None
        assert l1_past["net_points"] is not None
        assert len(l1_past["starters"]) == 11
        assert len(l1_past["bench"]) == 4
        # Past starters have actual scores and positions
        for p in l1_past["starters"]:
            assert "points" in p
            assert "minutes" in p
            assert p["pos_abbr"] in ("GKP", "DEF", "MID", "FWD")

    # 4. Query active GW2 lineup
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}/lineup?gw=2") as r:
        assert r.status == 200
        l2_active = json.loads(r.read())
        assert l2_active["gameweek"] == 2
        assert l2_active["is_past"] is False
        assert l2_active["gross_points"] is None
        for p in l2_active["starters"]:
            assert "expected_points" in p

    # 5. Zero future leakage: Gameweek 3 is in the future
    try:
        urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}/lineup?gw=3")
        assert False, "Expected 500 error for future gameweek access"
    except urllib.error.HTTPError as err:
        assert err.code == 500


def test_api_historical_season_ended_lifecycle(test_server) -> None:
    base_url, _ = test_server
    sid = "test_season_over_sim_01"

    # 1. Create simulation at GW 38
    create_req = urllib.request.Request(
        f"{base_url}/api/historical/simulations/create",
        data=json.dumps({
            "session_id": sid,
            "season": "2023-24",
            "start_gw": 38,
            "starting_strategy": "v1.2.5",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(create_req) as r:
        assert r.status == 200
        created = json.loads(r.read())
        assert created["current_gw"] == 38

    # 2. Run GW 38
    run_req = urllib.request.Request(
        f"{base_url}/api/historical/simulations/{sid}/run-gw",
        data=json.dumps({}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(run_req) as r:
        assert r.status == 200
        res = json.loads(r.read())
        sess = res["session"]
        assert sess["is_completed"] is True
        assert sess["status"] == "completed"

    # 3. Check GET simulation details
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}") as r:
        assert r.status == 200
        details = json.loads(r.read())
        assert details["is_completed"] is True
        assert details["status"] == "completed"

    # 4. Check simulations list
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations") as r:
        assert r.status == 200
        sims_data = json.loads(r.read())
        target = next((s for s in sims_data["simulations"] if s["session_id"] == sid), None)
        assert target is not None
        assert target["is_completed"] is True

    # 5. Check GW 38 lineup: is_past must be True with actual scores
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}/lineup?gw=38") as r:
        assert r.status == 200
        l38 = json.loads(r.read())
        assert l38["gameweek"] == 38
        assert l38["is_past"] is True
        assert l38["gross_points"] is not None
        assert l38["net_points"] is not None
        for p in l38["starters"]:
            assert "points" in p

    # 6. Check Transfers solver reports season_ended
    with urllib.request.urlopen(f"{base_url}/api/transfers?session_id={sid}") as r:
        assert r.status == 200
        tx = json.loads(r.read())
        assert tx.get("season_ended") is True

    # 7. Check Multi-GW Planner reports season_ended
    with urllib.request.urlopen(f"{base_url}/api/plan?session_id={sid}") as r:
        assert r.status == 200
        pl = json.loads(r.read())
        assert pl.get("season_ended") is True

    # 8. Check Chips reports season_ended
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}/chips") as r:
        assert r.status == 200
        ch = json.loads(r.read())
        assert ch.get("season_ended") is True

    # 9. Check Recommendations reports season_ended
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}/recommendations") as r:
        assert r.status == 200
        recs = json.loads(r.read())
        assert recs.get("season_ended") is True


def test_v146_02_17_19_unit_regressions(monkeypatch) -> None:
    """Verify V146-02 (horizon=1 rescore), V146-17 (blank GW 0.0 xP), and V146-19 (explicit C0 policy)."""
    from fpl_manager.chip_strategy import SeasonalChipPolicy
    from fpl_manager.models import Position
    from fpl_manager.suggest_transfers import PlayerInfo, rescore_transfer_candidates

    # V146-19: Explicit use_optimizer=False must remain False even when FPL_CHIP_OPTIMIZER=1
    monkeypatch.setenv("FPL_CHIP_OPTIMIZER", "1")
    pol_c0 = SeasonalChipPolicy(use_optimizer=False)
    assert pol_c0.use_optimizer is False
    pol_c1 = SeasonalChipPolicy(use_optimizer=True)
    assert pol_c1.use_optimizer is True
    pol_default = SeasonalChipPolicy()
    assert pol_default.use_optimizer is True

    # V146-02 & V146-17: rescore_transfer_candidates with horizon=1 and blank GW (missing key in non-empty gw_breakdown_xp)
    squad: list[PlayerInfo] = []
    for idx in range(1, 16):
        pos = (
            Position.GOALKEEPER if idx <= 2
            else (Position.DEFENDER if idx <= 7 else (Position.MIDFIELDER if idx <= 12 else Position.FORWARD))
        )
        squad.append(
            PlayerInfo(
                id=idx,
                name=f"P{idx}",
                position=pos,
                team_id=(idx % 7) + 1,
                team_short=f"T{(idx % 7) + 1}",
                price_tenths=50,
                status="a",
                total_points=20,
                expected_points=3.0,
                gw_xp=0.0 if idx == 15 else 3.0,
                horizon_xp=3.0,
                # Player 15 has a non-empty gw_breakdown_xp that omits GW 10 (blank GW 10 -> must be 0.0, not 3.0)
                gw_breakdown_xp={11: 3.0} if idx == 15 else {10: 3.0, 11: 3.0},
            )
        )
    in_cand = PlayerInfo(
        id=99,
        name="InStar",
        position=Position.FORWARD,
        team_id=9,
        team_short="T9",
        price_tenths=50,
        status="a",
        total_points=40,
        expected_points=6.0,
        gw_xp=6.0,
        horizon_xp=6.0,
        gw_breakdown_xp={10: 6.0},
    )
    players_map = {p.id: p for p in squad}
    players_map[99] = in_cand
    raw_results = [
        {
            "outgoing": [{"id": 15, "name": "P15", "position": "FORWARD", "team": "T2", "price_tenths": 50, "selling_price_tenths": 50, "xp": 0.0}],
            "incoming": [{"id": 99, "name": "InStar", "position": "FORWARD", "team": "T9", "price_tenths": 50, "xp": 6.0}],
            "transfer_hits": 0,
            "hit_cost": 0,
            "bank_after_tenths": 0,
            "bank_after_fmt": "£0.0m",
            "xp_delta": 6.0,
            "score": 6.0,
        }
    ]
    projections_by_gw = {
        10: {p.id: float(p.gw_breakdown_xp.get(10, 0.0)) for p in players_map.values()},
    }
    rescored = rescore_transfer_candidates(
        raw_results=raw_results,
        squad_players=squad,
        players_map=players_map,
        projections_by_gw=projections_by_gw,
        eff_horizon=1,
    )
    assert len(rescored) == 1
    assert rescored[0]["lineup_xp_delta"] > 0
    assert rescored[0]["gw1_lineup_xp_delta"] > 0
    assert rescored[0]["reason_breakdown"]["multi_horizon_gain"] == 0.0
    assert "reason_breakdown" in rescored[0]


def test_v146_03_09_15_api_guards_and_atomic_rollbacks(test_server) -> None:
    """Verify V146-03 (Undo guard), V146-09 (atomic plan step-0 rollback), and V146-15 (provenance guard)."""
    base_url, _ = test_server

    # 1. V146-03: Historical Undo without session_id must fail with 400 and never fall through to live Undo
    undo_req = urllib.request.Request(
        f"{base_url}/api/decisions/undo",
        data=json.dumps({"mode": "historical", "session_id": ""}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(undo_req)
        assert False, "Expected HTTP 400 when undoing historical mode without session_id"
    except urllib.error.HTTPError as err:
        assert err.code == 400

    # Create a simulation session
    sid = "test_v146_guards_sim"
    create_req = urllib.request.Request(
        f"{base_url}/api/historical/simulations/create",
        data=json.dumps({
            "session_id": sid,
            "season": "2023-24",
            "start_gw": 1,
            "starting_strategy": "v1.2.5",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(create_req) as r:
        assert r.status == 200
        init_sess = json.loads(r.read())
        init_squad_ids = [p["id"] for p in init_sess["squad"]]

    # 2. V146-15: Cross-mode / cross-session strategic candidate must be rejected with HTTP 400
    bad_strat_req = urllib.request.Request(
        f"{base_url}/api/strategic-squad/apply",
        data=json.dumps({
            "session_id": sid,
            "mode": "wildcard",
            "gameweek": 1,
            "season": "2023-24",
            "candidate": {
                "player_ids": init_squad_ids,
                "starters": [{"id": pid} for pid in init_squad_ids[:11]],
                "bench": [{"id": pid} for pid in init_squad_ids[11:]],
                "captain": {"id": init_squad_ids[0]},
                "vice_captain": {"id": init_squad_ids[1]},
                "provenance": {"app_mode": "live", "season": "2026/27", "session_id": None, "gameweek": 1},
            },
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(bad_strat_req)
        assert False, "Expected HTTP 400 for live provenance candidate applied to historical session"
    except urllib.error.HTTPError as err:
        assert err.code == 400

    # 3. V146-09: Atomic Step-0 Apply rollback when lineup validation fails after staging a valid transfer
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}/players") as r:
        pool = json.loads(r.read())["players"]
    out_p = init_sess["squad"][0]
    in_p = next(
        p for p in pool
        if p["position"] == out_p["position"]
        and p["id"] not in set(init_squad_ids)
        and p["price_tenths"] <= out_p["selling_price_tenths"]
        and p["team_id"] == out_p["team_id"]
    )
    atomic_fail_req = urllib.request.Request(
        f"{base_url}/api/historical/simulations/{sid}/apply-plan-step",
        data=json.dumps({
            "gameweek": 1,
            "transfers": [{"out_id": out_p["id"], "in_id": in_p["id"]}],
            "starting_ids": init_squad_ids[:5],  # Invalid: only 5 starters!
            "bench_ids": init_squad_ids[11:],
            "captain_id": init_squad_ids[0],
            "vice_captain_id": init_squad_ids[1],
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(atomic_fail_req)
        assert False, "Expected HTTP 400 for invalid starter count in apply-plan-step"
    except urllib.error.HTTPError as err:
        assert err.code == 400

    # Verify the valid transfer was rolled back and transfers_staged is still empty
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}") as r:
        after_sess = json.loads(r.read())
        assert after_sess["transfers_staged"] == []
        assert [p["id"] for p in after_sess["squad"]] == init_squad_ids


def test_v146_05_08_18_planner_no_future_leakage_and_squad_sensitive_chips(test_server, monkeypatch) -> None:
    """Verify V146-05/08 (historical beam search planner never loads future GW snapshots) and V146-18 (squad-sensitive chip roadmap)."""
    import fpl_manager.historical.snapshots as snap_mod

    base_url, _ = test_server
    sid = "test_v146_plan_chips_sim"
    create_req = urllib.request.Request(
        f"{base_url}/api/historical/simulations/create",
        data=json.dumps({
            "session_id": sid,
            "season": "2023-24",
            "start_gw": 2,
            "starting_strategy": "v1.2.5",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(create_req) as r:
        assert r.status == 200

    orig_build = snap_mod.build_historical_snapshot
    requested_gws: list[int] = []

    def _guarded_build(season_dir, gameweek, *args, **kwargs):
        requested_gws.append(int(gameweek))
        if int(gameweek) > 2:
            raise AssertionError(f"Future leakage detected: build_historical_snapshot called for GW{gameweek} > current_gw=2")
        return orig_build(season_dir, gameweek, *args, **kwargs)

    monkeypatch.setattr(snap_mod, "build_historical_snapshot", _guarded_build)

    with urllib.request.urlopen(f"{base_url}/api/plan?session_id={sid}&horizon=4&risk=neutral&no_hits=false") as r:
        assert r.status == 200
        plan_rep = json.loads(r.read())
        assert plan_rep["optimization_metadata"]["algorithm"] == "beam_search_multi_gw"
        steps = plan_rep["best_plan"]["gameweek_steps"]
        assert len(steps) == 4
        assert len(steps[0]["starting_ids"]) == 11
        assert len(steps[0]["bench_ids"]) == 4
    assert all(g <= 2 for g in requested_gws)

    # V146-18: Chip roadmap valuations must change when squad changes
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}/chips?start_gw=2") as r:
        chips_before = json.loads(r.read())
        sched_before = {s["chip"]: s["immediate_ev"] for s in chips_before["recommended_schedule"]}
        assert all(s["confidence"] != 0.88 for s in chips_before["recommended_schedule"])

    # Stage a transfer swapping a high-price starter for a low-price bench fodder to alter squad xP
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}") as r:
        sess = json.loads(r.read())
    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}/players") as r:
        pool = json.loads(r.read())["players"]
    squad_ids = {p["id"] for p in sess["squad"]}
    expensive_starter = max((p for p in sess["squad"] if p["is_starter"]), key=lambda x: x["current_price_tenths"])
    cheap_in = min(
        (
            p for p in pool
            if p["position"] == expensive_starter["position"]
            and p["id"] not in squad_ids
            and p["team_id"] == expensive_starter["team_id"]
        ),
        key=lambda x: x["expected_points"],
    )
    with urllib.request.urlopen(urllib.request.Request(
        f"{base_url}/api/historical/simulations/{sid}/transfers",
        data=json.dumps({"out_id": expensive_starter["id"], "in_id": cheap_in["id"]}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )) as r:
        assert r.status == 200

    with urllib.request.urlopen(f"{base_url}/api/historical/simulations/{sid}/chips?start_gw=2") as r:
        chips_after = json.loads(r.read())
        sched_after = {s["chip"]: s["immediate_ev"] for s in chips_after["recommended_schedule"]}
        assert sched_before != sched_after


@pytest.mark.parametrize("operation", ["get", "optimize", "reoptimize"])
@pytest.mark.parametrize("explicit_budget", [False, True])
def test_historical_studio_preserves_retained_prices_with_budget(
    test_server, monkeypatch: pytest.MonkeyPatch, operation: str, explicit_budget: bool
) -> None:
    from types import SimpleNamespace
    from urllib.parse import urlencode
    from src.fpl_manager.models import Position
    from src.fpl_manager.suggest_transfers import PlayerInfo

    positions = (
        [Position.GOALKEEPER] * 2 + [Position.DEFENDER] * 5
        + [Position.MIDFIELDER] * 5 + [Position.FORWARD] * 3
    )
    players = {
        i: PlayerInfo(
            id=i, name=f"P{i}", position=position, team_id=(i - 1) % 5 + 1,
            team_short=f"T{(i - 1) % 5 + 1}", price_tenths=50, status="a",
            total_points=20, expected_points=4, gw_xp=4, horizon_xp=4,
            gw_breakdown_xp={5: 4},
        )
        for i, position in enumerate(positions, 1)
    }
    session = SimpleNamespace(
        season="2023-24", squad_ids=list(players),
        purchase_prices_tenths={str(i): 40 for i in players}, bank_tenths=100,
    )
    monkeypatch.setattr("src.fpl_manager.gui.server.build_historical_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(
        "src.fpl_manager.gui.server.load_historical_players_meta", lambda *a, **k: (players, {})
    )
    monkeypatch.setattr(
        "src.fpl_manager.gui.server.HistoricalSimulationSession.load", lambda *a, **k: session
    )
    base_url, _ = test_server
    body = {
        "season": "2023-24", "session_id": "retained-price-test", "gameweek": 5,
        "mode": "wildcard", "horizon": 1, "strategy": "balanced",
        "locked_player_ids": list(players),
    }
    if explicit_budget:
        body["budget"] = 77.5
    if operation == "get":
        query = {key: value for key, value in body.items() if key != "locked_player_ids"}
        query["locks"] = ",".join(str(i) for i in players)
        request = f"{base_url}/api/strategic-squad?{urlencode(query)}"
    else:
        request = urllib.request.Request(
            f"{base_url}/api/strategic-squad/{operation}",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json"},
        )
    with urllib.request.urlopen(request) as response:
        candidate = json.loads(response.read())
    assert set(candidate["player_ids"]) == set(players)
    assert candidate["total_cost_tenths"] == 675
    assert candidate["bank_remaining_tenths"] == 100


@pytest.mark.parametrize("risk,expected_id", [("neutral", 102), ("floor", 101), ("ceiling", 102)])
def test_historical_transfer_api_honors_risk_after_rescoring(
    test_server, monkeypatch: pytest.MonkeyPatch, risk: str, expected_id: int
) -> None:
    from types import SimpleNamespace
    from src.fpl_manager.models import Position
    from src.fpl_manager.suggest_transfers import PlayerInfo

    positions = (
        [Position.GOALKEEPER] * 2 + [Position.DEFENDER] * 5
        + [Position.MIDFIELDER] * 5 + [Position.FORWARD] * 3
    )
    players = {
        i: PlayerInfo(
            id=i, name=f"P{i}", position=position, team_id=(i - 1) % 5 + 1,
            team_short=f"T{(i - 1) % 5 + 1}", price_tenths=50, status="a",
            total_points=20, expected_points=4, gw_xp=4, xp_floor=3, xp_ceiling=5,
            gw_breakdown_xp={5: 4},
        )
        for i, position in enumerate(positions, 1)
    }
    for pid, name, mean, floor, ceiling in (
        (101, "Safe", 4.5, 4, 5), (102, "Volatile", 10, 1, 20)
    ):
        players[pid] = PlayerInfo(
            id=pid, name=name, position=Position.FORWARD, team_id=pid,
            team_short=f"T{pid}", price_tenths=50, status="a", total_points=20,
            expected_points=mean, gw_xp=mean, xp_floor=floor, xp_ceiling=ceiling,
            gw_breakdown_xp={5: mean},
        )
    session = SimpleNamespace(
        session_id="risk-test", season="2023-24", current_gw=5, is_completed=False,
        historical_dir=Path("data") / "historical", squad_ids=list(range(1, 16)),
        purchase_prices_tenths={str(i): 50 for i in range(1, 16)},
        bank_tenths=0, free_transfers=1, transfers_staged=[], get_current_snapshot=lambda: None,
    )
    monkeypatch.setattr(
        "src.fpl_manager.gui.server.HistoricalSimulationSession.load", lambda *a, **k: session
    )
    monkeypatch.setattr(
        "src.fpl_manager.gui.server.load_historical_players_meta", lambda *a, **k: (players, {})
    )
    monkeypatch.setattr(
        "src.fpl_manager.gui.server.analyze_historical_fixtures", lambda *a, **k: ({}, {})
    )
    base_url, _ = test_server
    with urllib.request.urlopen(
        f"{base_url}/api/transfers?session_id=risk-test&gameweeks=1&risk={risk}"
    ) as response:
        result = json.loads(response.read())
    assert result["risk_profile"] == risk
    assert result["top_suggestions"][0]["incoming"][0]["id"] == expected_id
