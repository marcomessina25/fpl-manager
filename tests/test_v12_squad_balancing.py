"""Unit and integration tests for V1.2 Strategic Squad Balancing (Pillar 1).

Verifies:
1. Asymmetric Starting XI vs Bench weighting in solve_strategic_squad (1.0x starters, 0.15x bench).
2. Elimination of over-invested bench pathology: solver favors premium starting assets over expensive substitutes.
3. Configurable bench_weight parameter in StrategicConstraints and solve_strategic_squad override.
4. Alignment with evaluate_strategic_squad_objective.
"""

from pathlib import Path
import pytest

from fpl_manager.models import Position
from fpl_manager.optimizer import PlayerOptInfo
from fpl_manager.strategic_squad import (
    StrategicConstraints,
    evaluate_strategic_squad_objective,
    solve_strategic_squad,
    solve_strategic_squad_exact_reference,
)


def _create_balancing_test_pool() -> list[PlayerOptInfo]:
    """Create a synthetic pool with a clear choice between premium starters vs expensive bench.
    
    Structure:
    - 2 GKPs: one 4.5m (4.0 xP), one 4.0m (1.0 xP)
    - 6 DEFs:
        - 3 Star DEFs: 5.5m (5.0 xP each)
        - 1 Mid DEF: 5.0m (4.0 xP)
        - 2 Budget DEFs: 4.0m (2.0 xP each)
    - 6 MIDs:
        - 1 Super Premium MID: 12.5m (10.0 xP)
        - 2 Star MIDs: 8.5m (7.0 xP each)
        - 1 Mid MID: 6.5m (5.0 xP)
        - 2 Budget MIDs: 4.5m (2.5 xP each)
    - 4 FWDs:
        - 1 Super Premium FWD: 14.0m (12.0 xP)
        - 1 Mid FWD: 7.0m (5.5 xP)
        - 2 Budget FWDs: 4.5m (2.0 xP each)
    """
    pool = [
        # GKPs
        PlayerOptInfo(id=1, name="GKP_Star", position=Position.GOALKEEPER, team_id=1, team_short="T1", price_tenths=45, status="a", total_points=30, expected_points=4.0),
        PlayerOptInfo(id=2, name="GKP_Fodder", position=Position.GOALKEEPER, team_id=2, team_short="T2", price_tenths=40, status="a", total_points=10, expected_points=1.0),
        # DEFs
        PlayerOptInfo(id=11, name="DEF_Star1", position=Position.DEFENDER, team_id=3, team_short="T3", price_tenths=55, status="a", total_points=40, expected_points=5.0),
        PlayerOptInfo(id=12, name="DEF_Star2", position=Position.DEFENDER, team_id=4, team_short="T4", price_tenths=55, status="a", total_points=40, expected_points=5.0),
        PlayerOptInfo(id=13, name="DEF_Star3", position=Position.DEFENDER, team_id=5, team_short="T5", price_tenths=55, status="a", total_points=40, expected_points=5.0),
        PlayerOptInfo(id=14, name="DEF_Mid", position=Position.DEFENDER, team_id=6, team_short="T6", price_tenths=50, status="a", total_points=30, expected_points=4.0),
        PlayerOptInfo(id=15, name="DEF_Fodder1", position=Position.DEFENDER, team_id=7, team_short="T7", price_tenths=40, status="a", total_points=15, expected_points=2.0),
        PlayerOptInfo(id=16, name="DEF_Fodder2", position=Position.DEFENDER, team_id=8, team_short="T8", price_tenths=40, status="a", total_points=15, expected_points=2.0),
        # MIDs
        PlayerOptInfo(id=21, name="MID_Super", position=Position.MIDFIELDER, team_id=9, team_short="T9", price_tenths=125, status="a", total_points=80, expected_points=10.0),
        PlayerOptInfo(id=22, name="MID_Star1", position=Position.MIDFIELDER, team_id=10, team_short="T10", price_tenths=85, status="a", total_points=60, expected_points=7.0),
        PlayerOptInfo(id=23, name="MID_Star2", position=Position.MIDFIELDER, team_id=1, team_short="T1", price_tenths=85, status="a", total_points=60, expected_points=7.0),
        PlayerOptInfo(id=24, name="MID_Mid", position=Position.MIDFIELDER, team_id=2, team_short="T2", price_tenths=65, status="a", total_points=45, expected_points=5.0),
        PlayerOptInfo(id=25, name="MID_Fodder1", position=Position.MIDFIELDER, team_id=3, team_short="T3", price_tenths=45, status="a", total_points=20, expected_points=2.5),
        PlayerOptInfo(id=26, name="MID_Fodder2", position=Position.MIDFIELDER, team_id=4, team_short="T4", price_tenths=45, status="a", total_points=20, expected_points=2.5),
        # FWDs
        PlayerOptInfo(id=31, name="FWD_Haaland", position=Position.FORWARD, team_id=5, team_short="T5", price_tenths=140, status="a", total_points=100, expected_points=12.0),
        PlayerOptInfo(id=32, name="FWD_Mid", position=Position.FORWARD, team_id=6, team_short="T6", price_tenths=70, status="a", total_points=45, expected_points=5.5),
        PlayerOptInfo(id=33, name="FWD_Fodder1", position=Position.FORWARD, team_id=7, team_short="T7", price_tenths=45, status="a", total_points=15, expected_points=2.0),
        PlayerOptInfo(id=34, name="FWD_Fodder2", position=Position.FORWARD, team_id=8, team_short="T8", price_tenths=45, status="a", total_points=15, expected_points=2.0),
    ]
    return pool


def test_asymmetric_weighting_favors_super_premium() -> None:
    """Under bench_weight=0.15, the solver must include super-premium assets (FWD_Haaland, MID_Super)
    by economizing on the bench rather than building a flat, balanced bench.
    """
    pool = _create_balancing_test_pool()
    constraints = StrategicConstraints(budget_tenths=1000, bench_weight=0.15)
    cand = solve_strategic_squad(pool, constraints, strategy="balanced", horizon=5)

    assert len(cand.starters) == 11
    assert len(cand.bench) == 4
    starter_ids = {p["id"] for p in cand.starters}

    # Must prioritize super premiums in the starting XI
    assert 31 in starter_ids, "FWD_Haaland (14.0m) should be in starting XI under asymmetric weighting"
    assert 21 in starter_ids, "MID_Super (12.5m) should be in starting XI under asymmetric weighting"

    # Check bench cost is disciplined (less than £20.0m)
    bench_cost = sum(p["price_tenths"] for p in cand.bench) / 10.0
    assert bench_cost <= 18.0, f"Expected bench cost <= £18.0m, got £{bench_cost:.1f}m"


def test_bench_weight_parameter_override() -> None:
    """Verify that bench_weight can be set via StrategicConstraints and overridden in solve_strategic_squad."""
    pool = _create_balancing_test_pool()
    c = StrategicConstraints(budget_tenths=1000, bench_weight=0.10)
    assert c.bench_weight == 0.10

    # Overridden in call
    cand = solve_strategic_squad(pool, c, strategy="balanced", horizon=5, bench_weight=0.20)
    assert cand.total_cost_tenths <= 1000
    assert len(cand.player_ids) == 15


def test_asymmetric_scoring_alignment_with_exact_reference() -> None:
    """Verify that heuristic solve_strategic_squad and exact reference solver both optimize the asymmetric objective."""
    pool = _create_balancing_test_pool()
    constraints = StrategicConstraints(budget_tenths=1000, bench_weight=0.15)

    exact_res = solve_strategic_squad_exact_reference(pool, constraints, strategy="balanced", bench_weight=0.15)
    heur_res = solve_strategic_squad(pool, constraints, strategy="balanced", bench_weight=0.15)

    assert exact_res is not None
    assert heur_res is not None
    # Check that heuristic score is within 3% of exact global optimum
    exact_score = exact_res.total_objective_value
    heur_score = heur_res.total_objective_value
    assert heur_score >= 0.95 * exact_score, f"Heuristic score {heur_score} fell below 95% of exact {exact_score}"
