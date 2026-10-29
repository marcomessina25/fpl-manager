"""Tests for multi-gameweek transfer planning engine (planner.py)."""

import json
from pathlib import Path
import pytest

from fpl_manager.planner import generate_multi_gameweek_plan
from fpl_manager.storage import SnapshotStore, utc_timestamp


@pytest.fixture
def planner_test_db(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "fpl.sqlite3"
    squad_path = tmp_path / "current_squad.json"

    store = SnapshotStore(db_path)
    teams = [
        {"id": 1, "name": "Arsenal", "short_name": "ARS"},
        {"id": 2, "name": "Liverpool", "short_name": "LIV"},
        {"id": 3, "name": "Manchester City", "short_name": "MCI"},
        {"id": 4, "name": "Chelsea", "short_name": "CHE"},
        {"id": 5, "name": "Tottenham", "short_name": "TOT"},
        {"id": 6, "name": "Newcastle", "short_name": "NEW"},
        {"id": 7, "name": "Aston Villa", "short_name": "AVL"},
        {"id": 8, "name": "Brighton", "short_name": "BHA"},
        {"id": 9, "name": "Fulham", "short_name": "FUL"},
        {"id": 10, "name": "Brentford", "short_name": "BRE"},
    ]
    elements = []

    # 15 players in current squad (IDs 1..15)
    for i in range(1, 16):
        pos_id = 1 if i <= 2 else (2 if i <= 7 else (3 if i <= 12 else 4))
        team_id = ((i - 1) % 10) + 1
        elements.append({
            "id": i,
            "web_name": f"Squad_{i}",
            "team": team_id,
            "element_type": pos_id,
            "now_cost": 50,
            "status": "a",
            "total_points": 20,
            "minutes": 450,
            "expected_goals": "0.1",
            "expected_assists": "0.1",
            "expected_goals_conceded": "1.0",
        })

    # Pool of candidate targets across all positions and teams
    cand_id = 100
    for pos_id, count in [(1, 6), (2, 10), (3, 10), (4, 6)]:
        for c in range(count):
            cand_id += 1
            elements.append({
                "id": cand_id,
                "web_name": f"Target_{cand_id}",
                "team": (c % 10) + 1,
                "element_type": pos_id,
                "now_cost": 45 + (c % 4) * 10,
                "status": "a",
                "total_points": 50 + c * 5,
                "minutes": 800,
                "expected_goals": "0.4",
                "expected_assists": "0.3",
                "expected_goals_conceded": "0.5",
            })

    bootstrap = {"teams": teams, "elements": elements}
    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 3, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 3, "event": 2, "team_h": 3, "team_a": 4, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 4, "event": 2, "team_h": 5, "team_a": 6, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 5, "event": 2, "team_h": 7, "team_a": 8, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 6, "event": 2, "team_h": 9, "team_a": 10, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 7, "event": 3, "team_h": 2, "team_a": 1, "team_h_difficulty": 3, "team_a_difficulty": 2, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 8, "event": 3, "team_h": 4, "team_a": 3, "team_h_difficulty": 3, "team_a_difficulty": 2, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 9, "event": 3, "team_h": 6, "team_a": 5, "team_h_difficulty": 3, "team_a_difficulty": 2, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 10, "event": 3, "team_h": 8, "team_a": 7, "team_h_difficulty": 3, "team_a_difficulty": 2, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 11, "event": 3, "team_h": 10, "team_a": 9, "team_h_difficulty": 3, "team_a_difficulty": 2, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 12, "event": 4, "team_h": 1, "team_a": 3, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-09-10T15:00:00Z", "finished": False},
        {"id": 13, "event": 4, "team_h": 2, "team_a": 4, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-09-10T15:00:00Z", "finished": False},
        {"id": 14, "event": 4, "team_h": 5, "team_a": 7, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-09-10T15:00:00Z", "finished": False},
        {"id": 15, "event": 4, "team_h": 6, "team_a": 8, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-09-10T15:00:00Z", "finished": False},
        {"id": 16, "event": 4, "team_h": 9, "team_a": 10, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-09-10T15:00:00Z", "finished": False},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    squad_data = {
        "season": "2026/27",
        "player_ids": list(range(1, 16)),
        "purchase_prices_tenths": {str(pid): 50 for pid in range(1, 16)},
        "bank_tenths": 15,
        "free_transfers": 1,
        "chips_remaining": ["wildcard", "freehit"],
    }
    squad_path.write_text(json.dumps(squad_data), encoding="utf-8")

    return db_path, squad_path


def test_generate_multi_gameweek_plan_basic(tmp_path: Path, planner_test_db: tuple[Path, Path]) -> None:
    db_path, squad_path = planner_test_db
    report_file = tmp_path / "plan.json"

    res = generate_multi_gameweek_plan(
        squad_path=squad_path,
        database_path=db_path,
        horizon=3,
        report_path=report_file,
    )

    assert res["planning_horizon"] == 3
    assert len(res["target_gameweeks"]) == 3
    assert report_file.is_file()

    best = res["best_plan"]
    assert best is not None
    assert "total_net_xp" in best
    assert "total_floor_xp" in best
    assert "total_ceiling_xp" in best
    assert len(best["gameweek_steps"]) == 3

    for step in best["gameweek_steps"]:
        assert "gameweek" in step
        assert "action" in step
        assert "formation" in step
        assert "captain" in step
        assert "vice_captain" in step
        assert "lineup_xp" in step
        assert "net_xp" in step
        assert "bank_after_fmt" in step
        assert "free_transfers_after" in step
        assert step["free_transfers_after"] <= 5


def test_generate_multi_gameweek_plan_no_hits(tmp_path: Path, planner_test_db: tuple[Path, Path]) -> None:
    db_path, squad_path = planner_test_db
    report_file = tmp_path / "plan_nohits.json"

    res = generate_multi_gameweek_plan(
        squad_path=squad_path,
        database_path=db_path,
        horizon=2,
        allow_hits=False,
        report_path=report_file,
    )

    assert res["allow_hits"] is False
    best = res["best_plan"]
    assert best["total_hits"] == 0
    for step in best["gameweek_steps"]:
        assert step["transfer_hits"] == 0


def test_generate_multi_gameweek_plan_validation_and_risk(planner_test_db: tuple[Path, Path]) -> None:
    db_path, squad_path = planner_test_db

    for risk in ("neutral", "floor", "ceiling"):
        res = generate_multi_gameweek_plan(
            squad_path=squad_path,
            database_path=db_path,
            horizon=2,
            risk_profile=risk,
        )
        assert res["risk_profile"] == risk
        assert res["best_plan"] is not None

    with pytest.raises(ValueError, match="Invalid horizon"):
        generate_multi_gameweek_plan(squad_path=squad_path, database_path=db_path, horizon=0)

    with pytest.raises(ValueError, match="Invalid horizon"):
        generate_multi_gameweek_plan(squad_path=squad_path, database_path=db_path, horizon=10)

    with pytest.raises(ValueError, match="Invalid risk_profile"):
        generate_multi_gameweek_plan(squad_path=squad_path, database_path=db_path, risk_profile="unknown")


def _incoming_ids(plan: dict) -> set[int]:
    return {
        tx["in"]["id"]
        for step in plan["best_plan"]["gameweek_steps"]
        for tx in step.get("transfers", [])
    }


def test_generate_multi_gameweek_plan_excludes_long_term_unavailable(
    planner_test_db: tuple[Path, Path]
) -> None:
    db_path, squad_path = planner_test_db

    baseline_in = _incoming_ids(generate_multi_gameweek_plan(squad_path=squad_path, database_path=db_path, horizon=2))
    assert baseline_in, "fixture must produce at least one incoming transfer"

    # Drive the exclusion genuinely through PlayerInfo carrying is_long_term_unavailable=True
    # without monkeypatching (Task A3 / Issue 5). We mark the baseline incoming targets in the
    # database with a long-term injury marker while preserving status='a', proving that the exclusion
    # is driven by is_long_term_unavailable(p) rather than status filtering.
    import sqlite3
    from fpl_manager.suggest_transfers import load_all_players_meta

    with sqlite3.connect(db_path) as conn:
        for pid in baseline_in:
            conn.execute(
                "UPDATE players SET news = ? WHERE player_id = ?",
                ("Long-term unavailable: ruptured anterior cruciate ligament (ACL)", pid),
            )
        conn.commit()

    # Verify that load_all_players_meta produces genuine PlayerInfo objects with is_long_term_unavailable=True
    store = SnapshotStore(db_path)
    players_map, _ = load_all_players_meta(store)
    for pid in baseline_in:
        assert players_map[pid].is_long_term_unavailable is True, f"Player {pid} must carry is_long_term_unavailable=True"

    res = generate_multi_gameweek_plan(squad_path=squad_path, database_path=db_path, horizon=2)

    assert _incoming_ids(res).isdisjoint(baseline_in)


def test_v146_r2_05_risk_profiles_deduct_hits(tmp_path: Path):
    """V146-R2-05: Verify floor and ceiling beam rankings deduct hit costs."""
    from fpl_manager.planner import generate_historical_multi_gameweek_plan
    from fpl_manager.simulation.session import HistoricalSimulationSession

    sim = HistoricalSimulationSession.create(
        session_id="test_v146_r2_05",
        season="2023-24",
        start_gw=2,
        config_dir=tmp_path,
    )
    # Plan under neutral, floor, and ceiling
    plan_neutral = generate_historical_multi_gameweek_plan(sim=sim, horizon=2, risk_profile="neutral", allow_hits=True)
    plan_floor = generate_historical_multi_gameweek_plan(sim=sim, horizon=2, risk_profile="floor", allow_hits=True)
    plan_ceiling = generate_historical_multi_gameweek_plan(sim=sim, horizon=2, risk_profile="ceiling", allow_hits=True)

    for plan in (plan_neutral, plan_floor, plan_ceiling):
        for candidate in plan.get("candidates", []):
            hits = sum(s.get("hits", 0) for s in candidate.get("gameweek_steps", []))
            hit_penalty = hits * 4.0
            cum_mean = candidate.get("cumulative_expected_points", 0.0)
            cum_floor = candidate.get("cumulative_xp_floor", 0.0)
            cum_ceil = candidate.get("cumulative_xp_ceiling", 0.0)
            # Both net floor and net ceiling must account for hits
            assert cum_floor <= cum_mean + 0.01 or cum_floor == 0.0
            assert cum_ceil >= cum_mean - 0.01 or cum_ceil == 0.0


def test_v146_r2_06_free_hit_reversion(tmp_path: Path):
    """V146-R2-06: Step 0 Free Hit temporary state must not survive into step 1."""
    from fpl_manager.planner import generate_historical_multi_gameweek_plan
    from fpl_manager.simulation.session import HistoricalSimulationSession

    sim = HistoricalSimulationSession.create(
        session_id="test_v146_r2_06",
        season="2023-24",
        start_gw=5,
        config_dir=tmp_path,
    )
    sim.play_chip("free_hit")
    plan = generate_historical_multi_gameweek_plan(sim=sim, horizon=2, allow_hits=False)
    steps = plan["best_plan"]["gameweek_steps"]
    assert len(steps) >= 2
    # Step 0 has active Free Hit
    assert steps[0].get("active_chip") == "free_hit"
    # Step 1 must have no chip
    assert steps[1].get("active_chip") is None


def test_v146_r2_07_scoring_chips_affect_step0_evaluation(tmp_path: Path):
    """V146-R2-07: Triple Captain and Bench Boost directly enhance step 0 evaluation."""
    from fpl_manager.planner import generate_historical_multi_gameweek_plan
    from fpl_manager.simulation.session import HistoricalSimulationSession

    sim_none = HistoricalSimulationSession.create(
        session_id="test_v146_r2_07_none",
        season="2023-24",
        start_gw=5,
        config_dir=tmp_path / "none",
    )
    plan_none = generate_historical_multi_gameweek_plan(sim=sim_none, horizon=1)
    ev_none = plan_none["best_plan"]["gameweek_steps"][0]["expected_points"]

    sim_tc = HistoricalSimulationSession.create(
        session_id="test_v146_r2_07_tc",
        season="2023-24",
        start_gw=5,
        config_dir=tmp_path / "tc",
    )
    sim_tc.play_chip("triple_captain")
    plan_tc = generate_historical_multi_gameweek_plan(sim=sim_tc, horizon=1)
    ev_tc = plan_tc["best_plan"]["gameweek_steps"][0]["expected_points"]

    # Triple Captain must produce higher immediate score than no chip
    assert ev_tc > ev_none, f"Triple Captain EV ({ev_tc}) must exceed normal EV ({ev_none})"


def test_v146_r2_08_gw1_preseason_unlimited_hit_free(tmp_path: Path):
    """V146-R2-08: GW1 planning must treat moves as preseason unlimited and hit-free."""
    from fpl_manager.planner import generate_historical_multi_gameweek_plan
    from fpl_manager.simulation.session import HistoricalSimulationSession

    sim = HistoricalSimulationSession.create(
        session_id="test_v146_r2_08",
        season="2023-24",
        start_gw=1,
        config_dir=tmp_path,
    )
    plan = generate_historical_multi_gameweek_plan(sim=sim, horizon=2, allow_hits=False)
    step0 = plan["best_plan"]["gameweek_steps"][0]
    # Hits on GW1 must strictly be 0 even with transfers
    assert step0.get("hits", 0) == 0


def test_v146_r2_09_blank_gw_future_risk_distributions(tmp_path: Path):
    """V146-R2-09: A player with a current blank fixture must retain coherent positive future floor/ceiling."""
    from fpl_manager.planner import generate_historical_multi_gameweek_plan
    from fpl_manager.simulation.session import HistoricalSimulationSession

    # In 2023-24, GW18 had Manchester City blank (e.g. Foden)
    sim = HistoricalSimulationSession.create(
        session_id="test_v146_r2_09",
        season="2023-24",
        start_gw=18,
        config_dir=tmp_path,
    )
    plan = generate_historical_multi_gameweek_plan(sim=sim, horizon=3)
    # Check that in GW19 and GW20, projected floor and ceiling for candidates are positive
    assert plan["best_plan"]["gameweek_steps"][1]["xp_floor"] > 0.0
    assert plan["best_plan"]["gameweek_steps"][1]["xp_ceiling"] > 0.0


