"""Unit and exact-reference tests for Strategic Squad Optimization Engine (V1.1 Pillar 1)."""

import json
from pathlib import Path
import pytest

from fpl_manager.models import Position
from fpl_manager.optimizer import PlayerOptInfo
from fpl_manager.planner import generate_multi_gameweek_plan
from fpl_manager.rules import validate_squad, validate_starting_lineup, Player
from fpl_manager.storage import SnapshotStore, utc_timestamp
from fpl_manager.strategic_squad import (
    StrategicConstraints,
    StrategicCandidate,
    analyze_constraint_impact,
    generate_strategic_candidates,
    reoptimize_strategic_squad,
    solve_strategic_squad,
    solve_strategic_squad_exact_reference,
)
from fpl_manager.suggest_transfers import (
    suggest_initial_squad,
    suggest_strategic_squad,
    suggest_wildcard,
)


@pytest.fixture
def strategic_test_db(tmp_path: Path) -> tuple[Path, Path]:
    """Create a realistic snapshot database with diverse players and teams."""
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
            "web_name": f"Current_{i}",
            "team": team_id,
            "element_type": pos_id,
            "now_cost": 50,
            "status": "a",
            "total_points": 25,
            "minutes": 450,
            "expected_goals": "0.1",
            "expected_assists": "0.1",
            "expected_goals_conceded": "1.0",
        })

    # Diverse pool of candidates across positions (IDs 101+)
    cand_id = 100
    for pos_id, count in [(1, 8), (2, 20), (3, 20), (4, 12)]:
        for c in range(count):
            cand_id += 1
            cost = 40 + (c % 8) * 10  # 4.0m to 11.0m
            pts = 30 + c * 4
            elements.append({
                "id": cand_id,
                "web_name": f"Target_{cand_id}",
                "team": (c % 10) + 1,
                "element_type": pos_id,
                "now_cost": cost,
                "status": "a" if c != 5 else "d",
                "total_points": pts,
                "minutes": 700 + c * 10,
                "expected_goals": str(round(0.1 + (c % 5) * 0.15, 2)),
                "expected_assists": str(round(0.05 + (c % 4) * 0.1, 2)),
                "expected_goals_conceded": "0.8",
            })

    bootstrap = {"teams": teams, "elements": elements}
    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 3, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 1, "team_a": 3, "team_h_difficulty": 3, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 3, "event": 3, "team_h": 2, "team_a": 4, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 4, "event": 4, "team_h": 3, "team_a": 5, "team_h_difficulty": 2, "team_a_difficulty": 3, "kickoff_time": "2026-09-10T15:00:00Z", "finished": False},
        {"id": 5, "event": 5, "team_h": 4, "team_a": 6, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-09-17T15:00:00Z", "finished": False},
        {"id": 6, "event": 6, "team_h": 5, "team_a": 7, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-09-24T15:00:00Z", "finished": False},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    squad_data = {
        "season": "2026/27",
        "player_ids": list(range(1, 16)),
        "purchase_prices_tenths": {str(pid): 50 for pid in range(1, 16)},
        "bank_tenths": 20,
        "free_transfers": 1,
        "chips_remaining": ["wildcard", "freehit"],
    }
    squad_path.write_text(json.dumps(squad_data), encoding="utf-8")

    return db_path, squad_path


def create_bounded_synthetic_pool() -> list[PlayerOptInfo]:
    """Create a small bounded synthetic pool (19 players across 6 clubs) for exact reference verification."""
    pool = [
        # Goalkeepers (need 2, 3 available across 3 clubs)
        PlayerOptInfo(id=1, name="GK_1", position=Position.GOALKEEPER, team_id=1, team_short="ARS", price_tenths=45, status="a", total_points=30, expected_points=4.0),
        PlayerOptInfo(id=2, name="GK_2", position=Position.GOALKEEPER, team_id=2, team_short="LIV", price_tenths=40, status="a", total_points=20, expected_points=3.5),
        PlayerOptInfo(id=3, name="GK_3", position=Position.GOALKEEPER, team_id=3, team_short="MCI", price_tenths=50, status="a", total_points=35, expected_points=4.5),

        # Defenders (need 5, 7 available across 7 clubs)
        PlayerOptInfo(id=4, name="DEF_1", position=Position.DEFENDER, team_id=1, team_short="ARS", price_tenths=50, status="a", total_points=40, expected_points=4.5),
        PlayerOptInfo(id=5, name="DEF_2", position=Position.DEFENDER, team_id=2, team_short="LIV", price_tenths=55, status="a", total_points=50, expected_points=5.0),
        PlayerOptInfo(id=6, name="DEF_3", position=Position.DEFENDER, team_id=3, team_short="MCI", price_tenths=60, status="a", total_points=55, expected_points=5.2),
        PlayerOptInfo(id=7, name="DEF_4", position=Position.DEFENDER, team_id=4, team_short="CHE", price_tenths=45, status="a", total_points=35, expected_points=3.8),
        PlayerOptInfo(id=8, name="DEF_5", position=Position.DEFENDER, team_id=5, team_short="TOT", price_tenths=40, status="a", total_points=30, expected_points=3.5),
        PlayerOptInfo(id=9, name="DEF_6", position=Position.DEFENDER, team_id=6, team_short="NEW", price_tenths=40, status="a", total_points=25, expected_points=3.0),
        PlayerOptInfo(id=20, name="DEF_7", position=Position.DEFENDER, team_id=7, team_short="BHA", price_tenths=40, status="a", total_points=25, expected_points=3.0),

        # Midfielders (need 5, 7 available across 7 clubs)
        PlayerOptInfo(id=10, name="MID_1", position=Position.MIDFIELDER, team_id=1, team_short="ARS", price_tenths=80, status="a", total_points=70, expected_points=6.5),
        PlayerOptInfo(id=11, name="MID_2", position=Position.MIDFIELDER, team_id=2, team_short="LIV", price_tenths=95, status="a", total_points=85, expected_points=7.5),
        PlayerOptInfo(id=12, name="MID_3", position=Position.MIDFIELDER, team_id=3, team_short="MCI", price_tenths=70, status="a", total_points=60, expected_points=5.5),
        PlayerOptInfo(id=13, name="MID_4", position=Position.MIDFIELDER, team_id=4, team_short="CHE", price_tenths=55, status="a", total_points=45, expected_points=4.2),
        PlayerOptInfo(id=14, name="MID_5", position=Position.MIDFIELDER, team_id=5, team_short="TOT", price_tenths=50, status="a", total_points=40, expected_points=4.0),
        PlayerOptInfo(id=15, name="MID_6", position=Position.MIDFIELDER, team_id=6, team_short="NEW", price_tenths=45, status="a", total_points=30, expected_points=3.2),
        PlayerOptInfo(id=21, name="MID_7", position=Position.MIDFIELDER, team_id=7, team_short="BHA", price_tenths=45, status="a", total_points=30, expected_points=3.5),

        # Forwards (need 3, 5 available across 5 clubs)
        PlayerOptInfo(id=16, name="FWD_1", position=Position.FORWARD, team_id=3, team_short="MCI", price_tenths=120, status="a", total_points=95, expected_points=8.5),
        PlayerOptInfo(id=17, name="FWD_2", position=Position.FORWARD, team_id=4, team_short="CHE", price_tenths=75, status="a", total_points=65, expected_points=6.0),
        PlayerOptInfo(id=18, name="FWD_3", position=Position.FORWARD, team_id=5, team_short="TOT", price_tenths=60, status="a", total_points=50, expected_points=5.0),
        PlayerOptInfo(id=19, name="FWD_4", position=Position.FORWARD, team_id=6, team_short="NEW", price_tenths=45, status="a", total_points=30, expected_points=3.5),
        PlayerOptInfo(id=22, name="FWD_5", position=Position.FORWARD, team_id=7, team_short="BHA", price_tenths=50, status="a", total_points=35, expected_points=4.0),
    ]
    return pool


# =========================================================================
# 1. Constraint Validation Tests
# =========================================================================

def test_constraints_validation_simultaneous_lock_and_exclude() -> None:
    pool = create_bounded_synthetic_pool()
    constraints = StrategicConstraints(
        budget_tenths=1000,
        locked_player_ids={9, 10},
        excluded_player_ids={10, 15},
    )
    errors = constraints.validate(pool)
    assert len(errors) > 0
    assert any("simultaneously locked and excluded" in e for e in errors)


def test_constraints_validation_position_quota_exceeded() -> None:
    pool = create_bounded_synthetic_pool()
    # Lock 3 GKP when quota is 2
    gkp_extra = PlayerOptInfo(id=99, name="GK_3", position=Position.GOALKEEPER, team_id=3, team_short="MCI", price_tenths=40, status="a", total_points=20)
    constraints = StrategicConstraints(
        budget_tenths=1000,
        locked_player_ids={1, 2, 99},
    )
    errors = constraints.validate(pool + [gkp_extra])
    assert any("exceeds position quota" in e for e in errors)


def test_constraints_validation_club_quota_exceeded() -> None:
    pool = create_bounded_synthetic_pool()
    # Team 1 (ARS) has players 1, 4, 10. Add a 4th ARS player and lock all 4.
    ars_4 = PlayerOptInfo(id=98, name="ARS_EXTRA", position=Position.FORWARD, team_id=1, team_short="ARS", price_tenths=45, status="a", total_points=20)
    constraints = StrategicConstraints(
        budget_tenths=1000,
        locked_player_ids={1, 4, 10, 98},
    )
    errors = constraints.validate(pool + [ars_4])
    assert any("exceeds max club limit" in e for e in errors)


def test_constraints_validation_budget_exceeded() -> None:
    pool = create_bounded_synthetic_pool()
    # Tight budget: 600 tenths (£60.0m), but locked players require 215 tenths, remaining 13 players need at least 13*40 = 520 tenths
    constraints = StrategicConstraints(
        budget_tenths=600,
        locked_player_ids={11, 16},  # 95 + 120 = 215 tenths; 215 + 13*40 = 735 > 600
    )
    errors = constraints.validate(pool)
    assert any("exceeds available budget" in e for e in errors)


# =========================================================================
# 2. Exact Reference Solver Tests
# =========================================================================

def test_exact_reference_solver_optimality() -> None:
    pool = create_bounded_synthetic_pool()
    constraints = StrategicConstraints(
        budget_tenths=1000,
        locked_player_ids={16},  # Lock Haaland-type FWD_1
        excluded_player_ids={19},  # Exclude FWD_4
        target_gameweeks=(1, 2, 3),
    )

    exact_res = solve_strategic_squad_exact_reference(pool, constraints, strategy="maximum_ev")
    assert exact_res is not None
    assert exact_res.is_exact_global_optimum is True
    assert exact_res.total_cost_tenths <= 1000
    assert 16 in exact_res.player_ids
    assert 19 not in exact_res.player_ids
    assert len(exact_res.player_ids) == 15
    assert exact_res.search_metadata["legal_combinations"] > 0


def test_exact_reference_solver_safety_budget() -> None:
    pool = create_bounded_synthetic_pool()
    constraints = StrategicConstraints(budget_tenths=1000)
    # Set tiny max_evaluations limit
    with pytest.raises(ValueError, match="Reference solver safety budget exceeded"):
        solve_strategic_squad_exact_reference(pool, constraints, max_evaluations=10)


# =========================================================================
# 3. Production Heuristic Solver Tests
# =========================================================================

def test_solve_strategic_squad_constraints_enforcement() -> None:
    pool = create_bounded_synthetic_pool()
    constraints = StrategicConstraints(
        budget_tenths=950,
        locked_player_ids={1, 16},  # Lock GK_1 and FWD_1
        excluded_player_ids={9, 10},  # Exclude DEF_6 and MID_1 (leaves 5 DEF and 5 MID)
        preferred_player_ids={12},  # Prefer MID_3
        target_gameweeks=(1, 2, 3, 4, 5),
    )

    cand = solve_strategic_squad(pool, constraints, strategy="balanced")
    assert cand.is_exact_global_optimum is False
    assert cand.total_cost_tenths <= 950
    assert 1 in cand.player_ids
    assert 16 in cand.player_ids
    assert 9 not in cand.player_ids
    assert 10 not in cand.player_ids
    assert len(cand.starters) == 11
    assert len(cand.bench) == 4
    assert cand.bench[0]["role"] == "GK_SUB"
    assert cand.captain["id"] != cand.vice_captain["id"]

    # Positional quota verification
    squad_positions = [p["position"] for p in cand.squad]
    assert squad_positions.count("GOALKEEPER") == 2
    assert squad_positions.count("DEFENDER") == 5
    assert squad_positions.count("MIDFIELDER") == 5
    assert squad_positions.count("FORWARD") == 3


# =========================================================================
# 4. Multi-Candidate Generation and Strategy Differentiation
# =========================================================================

def test_generate_strategic_candidates_diversity() -> None:
    pool = create_bounded_synthetic_pool()
    constraints = StrategicConstraints(
        budget_tenths=1000,
        target_gameweeks=(1, 2, 3, 4, 5),
    )

    cands = generate_strategic_candidates(
        candidate_pool=pool,
        constraints=constraints,
        strategies=["maximum_ev", "balanced", "floor", "ceiling", "flexibility"],
    )

    assert "maximum_ev" in cands
    assert "balanced" in cands
    assert "floor" in cands
    assert "ceiling" in cands
    assert "flexibility" in cands

    for strat, cand in cands.items():
        assert len(cand.player_ids) == 15
        assert cand.total_cost_tenths <= 1000
        assert cand.strategy == strat


# =========================================================================
# 5. Constraint Impact Analysis & Re-Optimization
# =========================================================================

def test_reoptimize_and_constraint_impact_analysis() -> None:
    pool = create_bounded_synthetic_pool()
    # Baseline: no locks
    base_constraints = StrategicConstraints(
        budget_tenths=1000,
        target_gameweeks=(1, 2, 3),
    )
    base_cand = solve_strategic_squad(pool, base_constraints, strategy="maximum_ev")

    # Add lock on player 15 (MID_6, low expected points 3.2)
    new_constraints = StrategicConstraints(
        budget_tenths=1000,
        locked_player_ids={15},
        target_gameweeks=(1, 2, 3),
    )
    new_cand, impact = reoptimize_strategic_squad(base_cand, pool, new_constraints)

    assert 15 in new_cand.player_ids
    assert 15 in impact["constraints_changed"]["added_locks"]
    assert "opportunity_cost" in impact
    assert "summary" in impact
    assert isinstance(impact["players_added"], list)
    assert isinstance(impact["players_removed"], list)


# =========================================================================
# 6. Service Integration Tests (suggest_initial_squad, wildcard, planner)
# =========================================================================

def test_suggest_initial_squad_workflow(strategic_test_db: tuple[Path, Path]) -> None:
    db_path, _ = strategic_test_db
    res = suggest_initial_squad(
        budget_millions=100.0,
        database_path=db_path,
        num_gameweeks=4,
        strategy="balanced",
    )

    assert res["mode"] == "initial"
    assert len(res["squad"]) == 15
    assert len(res["starters"]) == 11
    assert len(res["bench"]) == 4
    assert res["total_cost_tenths"] <= 1000
    assert "strategic_candidates" in res
    assert "maximum_ev" in res["strategic_candidates"]


def test_suggest_wildcard_with_locks(strategic_test_db: tuple[Path, Path]) -> None:
    db_path, squad_path = strategic_test_db
    res = suggest_wildcard(
        budget_millions=100.0,
        squad_path=squad_path,
        database_path=db_path,
        num_gameweeks=5,
        risk_profile="balanced",
        locked_player_ids=[105],
        strategic_engine=True,
    )

    assert 105 in res["player_ids"]
    assert len(res["squad"]) == 15
    assert res["total_cost_tenths"] <= 1000


def test_planner_integration_with_strategic_starting_squad(strategic_test_db: tuple[Path, Path]) -> None:
    db_path, _ = strategic_test_db
    init_res = suggest_initial_squad(
        budget_millions=100.0,
        database_path=db_path,
        num_gameweeks=3,
        strategy="maximum_ev",
    )

    squad_ids = init_res["player_ids"]
    bank_rem = init_res["bank_remaining_tenths"]

    plan = generate_multi_gameweek_plan(
        database_path=db_path,
        horizon=2,
        initial_squad_ids=squad_ids,
        initial_bank_tenths=bank_rem,
    )

    assert "best_plan" in plan
    assert plan["best_plan"] is not None
    assert len(plan["best_plan"]["gameweek_steps"]) == 2


# =========================================================================
# 7. V1.1 Hardening Tests (P0.1, P0.5, P1.1, P1.2)
# =========================================================================

def test_horizon_xp_aggregation_convention_p01() -> None:
    """Verify unambiguous horizon xP aggregation semantics (P0.1).

    Acceptance criteria:
    For a player with:
      GW1 = 5, GW2 = 6, GW3 = 7, GW4 = 8, GW5 = 9 (sum = 35)
    the 5-GW expected-point contribution must be exactly 35, NOT 175.
    Doubling the horizon does not accidentally multiply an already aggregated value.
    """
    from fpl_manager.suggest_transfers import PlayerInfo
    from fpl_manager.strategic_squad import compute_player_strategic_value

    # Case A: Player with explicit horizon_xp (already summed across 5 GWs)
    player_multi = PlayerInfo(
        id=999,
        name="Test Star",
        position=Position.MIDFIELDER,
        team_id=1,
        team_short="TST",
        price_tenths=80,
        status="a",
        total_points=50,
        expected_points=7.0,  # average per GW = 35 / 5
        gw_xp=7.0,
        horizon_xp=35.0,     # explicit sum: 5 + 6 + 7 + 8 + 9 = 35
        xp_floor=6.0,
        xp_ceiling=8.0,
        standard_deviation=1.0,
        horizon_floor=30.0,
        horizon_ceiling=40.0,
    )

    val_multi = compute_player_strategic_value(player_multi, strategy="maximum_ev", horizon_len=5)
    assert val_multi == 35.0, f"Expected exactly 35.0, got {val_multi}"

    # Case B: Player with 1-GW expected_points = 7.0 over horizon 1, 2, 5, 8
    player_single = PlayerInfo(
        id=998,
        name="Test Single",
        position=Position.MIDFIELDER,
        team_id=1,
        team_short="TST",
        price_tenths=80,
        status="a",
        total_points=50,
        expected_points=7.0,
        gw_xp=7.0,
        horizon_xp=0.0,  # not pre-aggregated
        xp_floor=6.0,
        xp_ceiling=8.0,
        standard_deviation=1.0,
    )

    val_h1 = compute_player_strategic_value(player_single, strategy="maximum_ev", horizon_len=1)
    val_h2 = compute_player_strategic_value(player_single, strategy="maximum_ev", horizon_len=2)
    val_h5 = compute_player_strategic_value(player_single, strategy="maximum_ev", horizon_len=5)
    val_h8 = compute_player_strategic_value(player_single, strategy="maximum_ev", horizon_len=8)

    assert val_h1 == 7.0
    assert val_h2 == 14.0
    assert val_h5 == 35.0
    assert val_h8 == 56.0


def test_measure_heuristic_optimality_gap_p11() -> None:
    """Measure production heuristic optimality gap against exact oracle on bounded pool (P1.1)."""
    from fpl_manager.suggest_transfers import PlayerInfo
    from fpl_manager.strategic_squad import measure_heuristic_optimality_gap

    # Create small bounded pool of 16 players (2 GKP, 5 DEF, 6 MID, 3 FWD)
    pool = []
    pid = 1
    # 2 GKP
    for _ in range(2):
        pool.append(PlayerInfo(id=pid, name=f"GKP_{pid}", position=Position.GOALKEEPER, team_id=pid, team_short=f"T{pid}", price_tenths=45, status="a", total_points=20, expected_points=3.5, gw_xp=3.5, horizon_xp=17.5))
        pid += 1
    # 5 DEF
    for _ in range(5):
        pool.append(PlayerInfo(id=pid, name=f"DEF_{pid}", position=Position.DEFENDER, team_id=pid, team_short=f"T{pid}", price_tenths=50, status="a", total_points=25, expected_points=4.0, gw_xp=4.0, horizon_xp=20.0))
        pid += 1
    # 6 MID (1 spare)
    for i in range(6):
        xp = 4.5 + i * 0.5
        pool.append(PlayerInfo(id=pid, name=f"MID_{pid}", position=Position.MIDFIELDER, team_id=pid, team_short=f"T{pid}", price_tenths=50 + i * 5, status="a", total_points=30, expected_points=xp, gw_xp=xp, horizon_xp=xp*5))
        pid += 1
    # 3 FWD
    for _ in range(3):
        pool.append(PlayerInfo(id=pid, name=f"FWD_{pid}", position=Position.FORWARD, team_id=pid, team_short=f"T{pid}", price_tenths=60, status="a", total_points=30, expected_points=5.0, gw_xp=5.0, horizon_xp=25.0))
        pid += 1

    constraints = StrategicConstraints(budget_tenths=1000)
    gap_metrics = measure_heuristic_optimality_gap(pool, constraints, strategy="maximum_ev")

    assert "exact_optimum" in gap_metrics
    assert "heuristic_value" in gap_metrics
    assert "absolute_gap" in gap_metrics
    assert "relative_gap" in gap_metrics
    assert gap_metrics["absolute_gap"] >= 0.0
    assert gap_metrics["relative_gap"] >= 0.0
    assert gap_metrics["heuristic_value"] <= gap_metrics["exact_optimum"] + 1e-4


def test_exact_reference_and_production_eligibility_alignment_p05() -> None:
    """Verify that unavailable players are excluded from both exact and heuristic solvers unless locked (P0.5)."""
    from fpl_manager.suggest_transfers import PlayerInfo

    pool = []
    pid = 1
    # 2 GKP
    for _ in range(2):
        pool.append(PlayerInfo(id=pid, name=f"GKP_{pid}", position=Position.GOALKEEPER, team_id=pid, team_short=f"T{pid}", price_tenths=45, status="a", total_points=20, expected_points=4.0, gw_xp=4.0, horizon_xp=20.0))
        pid += 1
    # 5 DEF
    for _ in range(5):
        pool.append(PlayerInfo(id=pid, name=f"DEF_{pid}", position=Position.DEFENDER, team_id=pid, team_short=f"T{pid}", price_tenths=45, status="a", total_points=20, expected_points=4.0, gw_xp=4.0, horizon_xp=20.0))
        pid += 1
    # 5 MID - including one injured player with high xP
    for i in range(4):
        pool.append(PlayerInfo(id=pid, name=f"MID_{pid}", position=Position.MIDFIELDER, team_id=pid, team_short=f"T{pid}", price_tenths=50, status="a", total_points=20, expected_points=4.0, gw_xp=4.0, horizon_xp=20.0))
        pid += 1
    # Injured MID (status 'i') with massive xP (trap player)
    injured_mid = PlayerInfo(id=pid, name="Injured_Trap", position=Position.MIDFIELDER, team_id=pid, team_short=f"T{pid}", price_tenths=50, status="i", total_points=100, expected_points=20.0, gw_xp=20.0, horizon_xp=100.0)
    pool.append(injured_mid)
    pid += 1
    # Healthy MID with modest xP
    healthy_mid = PlayerInfo(id=pid, name="Healthy_Mid", position=Position.MIDFIELDER, team_id=pid, team_short=f"T{pid}", price_tenths=50, status="a", total_points=20, expected_points=4.0, gw_xp=4.0, horizon_xp=20.0)
    pool.append(healthy_mid)
    pid += 1
    # 3 FWD
    for _ in range(3):
        pool.append(PlayerInfo(id=pid, name=f"FWD_{pid}", position=Position.FORWARD, team_id=pid, team_short=f"T{pid}", price_tenths=55, status="a", total_points=20, expected_points=4.0, gw_xp=4.0, horizon_xp=20.0))
        pid += 1

    constraints = StrategicConstraints(budget_tenths=1000)

    # 1. Without lock: injured player must NOT be in exact solver solution or heuristic solution
    exact_cand = solve_strategic_squad_exact_reference(pool, constraints)
    heur_cand = solve_strategic_squad(pool, constraints)

    assert exact_cand is not None
    assert injured_mid.id not in exact_cand.player_ids
    assert injured_mid.id not in heur_cand.player_ids

    # 2. With lock: injured player MUST be included in both
    locked_constraints = StrategicConstraints(budget_tenths=1000, locked_player_ids={injured_mid.id})
    exact_locked = solve_strategic_squad_exact_reference(pool, locked_constraints)
    heur_locked = solve_strategic_squad(pool, locked_constraints)

    assert exact_locked is not None
    assert injured_mid.id in exact_locked.player_ids
    assert injured_mid.id in heur_locked.player_ids


def test_profile_failure_tracking_p12() -> None:
    """Verify that failed strategic profiles are tracked and not silently dropped (P1.2)."""
    from fpl_manager.suggest_transfers import PlayerInfo

    # Create minimum viable pool
    pool = []
    pid = 1
    for pos, quota in [(Position.GOALKEEPER, 2), (Position.DEFENDER, 5), (Position.MIDFIELDER, 5), (Position.FORWARD, 3)]:
        for _ in range(quota):
            pool.append(PlayerInfo(id=pid, name=f"P_{pid}", position=pos, team_id=pid % 8 + 1, team_short=f"T{pid % 8 + 1}", price_tenths=50, status="a", total_points=20, expected_points=4.0, gw_xp=4.0, horizon_xp=20.0))
            pid += 1

    # Normal constraints: all succeed
    cands = generate_strategic_candidates(pool, constraints=StrategicConstraints(budget_tenths=1000))
    assert hasattr(cands, "requested_profiles")
    assert hasattr(cands, "successful_profiles")
    assert hasattr(cands, "failed_profiles")
    assert len(cands.failed_profiles) == 0
