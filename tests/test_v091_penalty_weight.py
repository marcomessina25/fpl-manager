"""Unit tests for V0.9.1 Multi-Year Penalty Weight Learning Instrumentation."""

import pytest

from fpl_manager.backtest.decision_engine import (
    DecisionEngineV09,
    calculate_lineup_risk_score,
    resolve_decision_engine,
)
from fpl_manager.expected_points import ExpectedPointsProjection
from fpl_manager.models import Position


def test_calculate_lineup_risk_score_equivalence():
    """Verify calculate_lineup_risk_score reproduces exact production formula at w=0.20."""
    # Production formula: xp * (0.80 + 0.20 * p_start)
    for xp in [2.0, 5.5, 8.0, 12.0]:
        for p_start in [0.0, 0.25, 0.50, 0.75, 0.90, 1.0]:
            prod_score = xp * (0.80 + 0.20 * p_start)
            func_score = calculate_lineup_risk_score(xp, p_start, penalty_weight=0.20)
            assert abs(func_score - prod_score) < 1e-9


def test_calculate_lineup_risk_score_w0():
    """Verify w=0.00 yields raw unconstrained expected points."""
    for xp in [1.5, 4.0, 7.2, 10.0]:
        for p_start in [0.0, 0.3, 0.6, 1.0]:
            score = calculate_lineup_risk_score(xp, p_start, penalty_weight=0.00)
            assert abs(score - xp) < 1e-9


def test_calculate_lineup_risk_score_weights():
    """Verify arbitrary weights w in [0.0, 0.5] match xp * (1 - w * (1 - p_start))."""
    xp = 6.0
    p_start = 0.40  # 1 - p_start = 0.60
    assert abs(calculate_lineup_risk_score(xp, p_start, 0.10) - (6.0 * (1.0 - 0.10 * 0.60))) < 1e-9
    assert abs(calculate_lineup_risk_score(xp, p_start, 0.30) - (6.0 * (1.0 - 0.30 * 0.60))) < 1e-9


def test_decision_engine_v09_resolution_and_defaults():
    """Verify DecisionEngineV09 defaults to w=0.20 and resolves _w strings."""
    eng_default = DecisionEngineV09()
    assert eng_default.lineup_penalty_weight == 0.20
    assert eng_default.name == "V0.9 Participation-Aware Decision Engine"

    eng_custom = DecisionEngineV09(lineup_penalty_weight=0.15)
    assert eng_custom.lineup_penalty_weight == 0.15
    assert "w=0.15" in eng_custom.name

    resolved = resolve_decision_engine("v0.9_w0.10")
    assert isinstance(resolved, DecisionEngineV09)
    assert abs(resolved.lineup_penalty_weight - 0.10) < 1e-6

    resolved_w0 = resolve_decision_engine("v09_w0.00")
    assert isinstance(resolved_w0, DecisionEngineV09)
    assert abs(resolved_w0.lineup_penalty_weight - 0.00) < 1e-6

    cfg = resolved.get_strategy_config("Optimizer")
    assert cfg["lineup_penalty_weight"] == 0.10


def test_lineup_selection_equivalence():
    """Verify DecisionEngineV09(lineup_penalty_weight=0.20) produces identical lineups to DecisionEngineV09()."""
    def make_p(pid, pos, xp, p_start):
        return ExpectedPointsProjection(
            player_id=pid,
            web_name=f"P{pid}",
            position=pos,
            team_id=1,
            team_short="ARS",
            price_tenths=50,
            status="a",
            availability_pct=1.0,
            base_xp_per_match=xp,
            gameweek=1,
            fixtures=(),
            expected_points=xp,
            expected_minutes=p_start * 85.0,
            start_probability=p_start,
            play_probability=min(1.0, p_start + 0.1),
        )

    projs = [
        make_p(1, Position.GOALKEEPER, 4.0, 0.95),
        make_p(2, Position.GOALKEEPER, 1.0, 0.05),
        make_p(3, Position.DEFENDER, 4.5, 0.95),
        make_p(4, Position.DEFENDER, 4.2, 0.95),
        make_p(5, Position.DEFENDER, 4.0, 0.95),
        make_p(6, Position.DEFENDER, 3.5, 0.60),
        make_p(7, Position.DEFENDER, 2.0, 0.20),
        make_p(8, Position.MIDFIELDER, 6.0, 0.95),
        make_p(9, Position.MIDFIELDER, 5.8, 0.90),
        make_p(10, Position.MIDFIELDER, 5.0, 0.85),
        make_p(11, Position.MIDFIELDER, 4.5, 0.70),
        make_p(12, Position.MIDFIELDER, 3.0, 0.30),
        make_p(13, Position.FORWARD, 7.5, 0.95),
        make_p(14, Position.FORWARD, 6.0, 0.80),
        make_p(15, Position.FORWARD, 4.0, 0.40),
    ]
    squad_ids = [p.player_id for p in projs]

    eng_prod = DecisionEngineV09()
    eng_w020 = DecisionEngineV09(lineup_penalty_weight=0.20)

    s_prod, b_prod, c_prod, vc_prod, xp_prod = eng_prod.select_lineup(squad_ids, projs)
    s_w020, b_w020, c_w020, vc_w020, xp_w020 = eng_w020.select_lineup(squad_ids, projs)

    assert s_prod == s_w020
    assert b_prod == b_w020
    assert c_prod == c_w020
    assert vc_prod == vc_w020
    assert xp_prod == xp_w020
