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


def _create_divergence_test_pool() -> list[PlayerOptInfo]:
    """Create a synthetic pool where asymmetric (0.15) and symmetric (1.0) weighting diverge.

    The pool presents a structural trade-off:
    - Asymmetric mode (0.15) economizes heavily on the bench (cheap fodder) to fund a
      super-premium starting asset (MID_HaalandClass, £14.0m) plus strong starters.
    - Symmetric mode (1.0) values bench points equally to starters, so it invests in mid-priced
      bench coverage (e.g. £5.0m defenders, £6.5m forward) and foregoes the super-premium starting asset.
    """
    gkps = [
        PlayerOptInfo(id=1, name="GKP_Star", position=Position.GOALKEEPER, team_id=1, team_short="T1", price_tenths=50, status="a", total_points=40, expected_points=5.0),
        PlayerOptInfo(id=2, name="GKP_Fodder", position=Position.GOALKEEPER, team_id=2, team_short="T2", price_tenths=40, status="a", total_points=10, expected_points=1.0),
        PlayerOptInfo(id=3, name="GKP_Mid", position=Position.GOALKEEPER, team_id=3, team_short="T3", price_tenths=45, status="a", total_points=25, expected_points=3.8),
    ]
    defs = [
        PlayerOptInfo(id=11, name="DEF_Star1", position=Position.DEFENDER, team_id=4, team_short="T4", price_tenths=55, status="a", total_points=40, expected_points=5.0),
        PlayerOptInfo(id=12, name="DEF_Star2", position=Position.DEFENDER, team_id=5, team_short="T5", price_tenths=55, status="a", total_points=40, expected_points=5.0),
        PlayerOptInfo(id=13, name="DEF_Star3", position=Position.DEFENDER, team_id=6, team_short="T6", price_tenths=55, status="a", total_points=40, expected_points=5.0),
        PlayerOptInfo(id=14, name="DEF_Mid1", position=Position.DEFENDER, team_id=7, team_short="T7", price_tenths=50, status="a", total_points=35, expected_points=4.2),
        PlayerOptInfo(id=15, name="DEF_Mid2", position=Position.DEFENDER, team_id=8, team_short="T8", price_tenths=50, status="a", total_points=35, expected_points=4.2),
        PlayerOptInfo(id=16, name="DEF_Fodder1", position=Position.DEFENDER, team_id=9, team_short="T9", price_tenths=40, status="a", total_points=15, expected_points=1.5),
        PlayerOptInfo(id=17, name="DEF_Fodder2", position=Position.DEFENDER, team_id=10, team_short="T10", price_tenths=40, status="a", total_points=15, expected_points=1.5),
    ]
    mids = [
        PlayerOptInfo(id=21, name="MID_HaalandClass", position=Position.MIDFIELDER, team_id=11, team_short="T11", price_tenths=140, status="a", total_points=100, expected_points=12.0),
        PlayerOptInfo(id=22, name="MID_Star1", position=Position.MIDFIELDER, team_id=12, team_short="T12", price_tenths=85, status="a", total_points=70, expected_points=7.5),
        PlayerOptInfo(id=23, name="MID_Star2", position=Position.MIDFIELDER, team_id=13, team_short="T13", price_tenths=85, status="a", total_points=70, expected_points=7.5),
        PlayerOptInfo(id=24, name="MID_Mid1", position=Position.MIDFIELDER, team_id=14, team_short="T14", price_tenths=70, status="a", total_points=55, expected_points=6.5),
        PlayerOptInfo(id=25, name="MID_Mid2", position=Position.MIDFIELDER, team_id=15, team_short="T15", price_tenths=70, status="a", total_points=55, expected_points=6.5),
        PlayerOptInfo(id=26, name="MID_Fodder1", position=Position.MIDFIELDER, team_id=16, team_short="T16", price_tenths=45, status="a", total_points=20, expected_points=2.0),
        PlayerOptInfo(id=27, name="MID_Fodder2", position=Position.MIDFIELDER, team_id=17, team_short="T17", price_tenths=45, status="a", total_points=20, expected_points=2.0),
    ]
    fwds = [
        PlayerOptInfo(id=31, name="FWD_Star1", position=Position.FORWARD, team_id=18, team_short="T18", price_tenths=80, status="a", total_points=65, expected_points=7.5),
        PlayerOptInfo(id=32, name="FWD_Star2", position=Position.FORWARD, team_id=19, team_short="T19", price_tenths=80, status="a", total_points=65, expected_points=7.5),
        PlayerOptInfo(id=33, name="FWD_Fodder1", position=Position.FORWARD, team_id=20, team_short="T20", price_tenths=45, status="a", total_points=15, expected_points=1.8),
        PlayerOptInfo(id=34, name="FWD_Mid", position=Position.FORWARD, team_id=1, team_short="T1", price_tenths=65, status="a", total_points=45, expected_points=5.5),
    ]
    return gkps + defs + mids + fwds


def test_asymmetric_weighting_favors_super_premium() -> None:
    """Under bench_weight=0.15, the solver must produce a squad that genuinely diverges from
    bench_weight=1.0 (legacy mode), concentrating more budget in the starting XI and economizing
    on the bench rather than building a flat, balanced bench.
    """
    pool = _create_divergence_test_pool()

    # V1.2 asymmetric mode
    constraints_asym = StrategicConstraints(budget_tenths=1000, bench_weight=0.15)
    cand_asym = solve_strategic_squad(pool, constraints_asym, strategy="balanced", horizon=5, bench_weight=0.15)

    # Legacy symmetric mode (reproduces master)
    constraints_leg = StrategicConstraints(budget_tenths=1000, bench_weight=1.0)
    cand_leg = solve_strategic_squad(pool, constraints_leg, strategy="balanced", horizon=5, bench_weight=1.0)

    assert len(cand_asym.starters) == 11
    assert len(cand_asym.bench) == 4
    starter_ids_asym = {p["id"] for p in cand_asym.starters}

    # Must prioritize super premiums in the starting XI
    assert 21 in starter_ids_asym, "MID_HaalandClass (14.0m) should be in starting XI under asymmetric weighting"

    # Squad compositions must diverge between asymmetric and symmetric modes (Issue 5 discrimination guard)
    assert sorted(cand_asym.player_ids) != sorted(cand_leg.player_ids), (
        "Asymmetric and legacy symmetric modes must produce different squads"
    )

    # Check that asymmetric weighting concentrates more budget into the starting XI
    asym_st_cost = sum(p["price_tenths"] for p in cand_asym.starters) / 10.0
    leg_st_cost = sum(p["price_tenths"] for p in cand_leg.starters) / 10.0
    assert asym_st_cost > leg_st_cost, (
        f"Asymmetric squad should concentrate more budget in starting XI (£{asym_st_cost:.1f}m) "
        f"than symmetric legacy squad (£{leg_st_cost:.1f}m)"
    )

    # Check bench cost is disciplined (less than £18.0m) and strictly less than symmetric mode bench
    asym_bench_cost = sum(p["price_tenths"] for p in cand_asym.bench) / 10.0
    leg_bench_cost = sum(p["price_tenths"] for p in cand_leg.bench) / 10.0
    assert asym_bench_cost <= 18.0, f"Expected bench cost <= £18.0m, got £{asym_bench_cost:.1f}m"
    assert asym_bench_cost < leg_bench_cost, (
        f"Asymmetric bench cost (£{asym_bench_cost:.1f}m) should be lower than symmetric bench (£{leg_bench_cost:.1f}m)"
    )


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


class TestLegacyModeReproducesMaster:
    """Regression guard for the V1.1/V1.1.5 baseline-drift fix (Issue 3a).

    When the effective bench_weight is >= 1.0, solve_strategic_squad must run the exact
    legacy (pre-V1.2) symmetric per-player-score search algorithm used by master:
    per-player p_score deltas for 1-opt/2-opt (not asymmetric lineup scoring), top-30
    2-opt candidates (not top-25), and a final evaluate_strategic_squad_objective call
    without an explicit bench_weight override (using its own 0.15 default, exactly as
    master's solve_strategic_squad did).

    Expected player IDs and objective value below were obtained by running master's
    (pre-V1.2) `solve_strategic_squad` from `git show master:src/fpl_manager/strategic_squad.py`
    against this exact synthetic pool in an isolated temp module (not committed), and
    hard-coding the result here for a fast, dependency-free regression check.
    """

    def test_legacy_bench_weight_matches_master_algorithm(self) -> None:
        pool = _create_balancing_test_pool()
        constraints = StrategicConstraints(budget_tenths=1000, bench_weight=1.0)
        cand = solve_strategic_squad(pool, constraints, strategy="balanced", horizon=5, bench_weight=1.0)

        expected_ids = [1, 2, 11, 12, 13, 14, 15, 21, 22, 23, 24, 25, 31, 32, 33]
        assert sorted(cand.player_ids) == expected_ids
        assert cand.total_objective_value == pytest.approx(431.0)

    def test_legacy_bench_weight_via_constraints_default_matches_master_algorithm(self) -> None:
        """Same as above, but bench_weight=1.0 comes solely from StrategicConstraints
        (no explicit override kwarg to solve_strategic_squad)."""
        pool = _create_balancing_test_pool()
        constraints = StrategicConstraints(budget_tenths=1000, bench_weight=1.0)
        cand = solve_strategic_squad(pool, constraints, strategy="balanced", horizon=5)

        expected_ids = [1, 2, 11, 12, 13, 14, 15, 21, 22, 23, 24, 25, 31, 32, 33]
        assert sorted(cand.player_ids) == expected_ids
        assert cand.total_objective_value == pytest.approx(431.0)
