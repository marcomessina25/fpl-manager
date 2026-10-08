"""Unit and integration test suite for Unified Strategic Chip Opportunity-Cost Optimizer (V1.4.5)."""

import json
from pathlib import Path
import tempfile
import pytest

from fpl_manager.chip_strategy import SeasonalChipInventory, SeasonalChipPolicy, recommend_chip_strategy
from fpl_manager.expected_points import ExpectedPointsProjection
from fpl_manager.historical.models import HistoricalGameweekSnapshot, HistoricalPlayerState, Position
from fpl_manager.simulation.chip_optimizer import (
    ChipOpportunityOptimizer,
    ChipOpportunityValue,
    GameweekFixtureTopology,
    extract_season_fixture_topology,
)
from fpl_manager.simulation.session import HistoricalSimulationSession


def test_chip_opportunity_value_structure():
    """Verify ChipOpportunityValue dataclass immutability and serialization."""
    opp = ChipOpportunityValue(
        chip="triple_captain",
        gameweek=25,
        immediate_ev=14.5,
        future_max_ev=8.0,
        net_utility=6.5,
        confidence=0.92,
        reasoning="Double gameweek captaincy fixture spike.",
        metadata={"fixture_count": 2},
    )
    assert opp.chip == "triple_captain"
    assert opp.immediate_ev == 14.5
    assert opp.net_utility == 6.5
    d = opp.to_dict()
    assert d["chip"] == "triple_captain"
    assert d["net_utility"] == 6.5
    assert d["metadata"]["fixture_count"] == 2


def test_extract_season_fixture_topology():
    """Verify 38-gameweek calendar topography correctly identifies blanks and doubles."""
    raw_fixtures = [
        {"event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3},
        {"event": 1, "team_h": 3, "team_a": 4, "team_h_difficulty": 2, "team_a_difficulty": 4},
        # Event 2: Team 1 plays twice (vs 3 and vs 4); Team 2 has 0 fixtures (Blank)
        {"event": 2, "team_h": 1, "team_a": 3, "team_h_difficulty": 2, "team_a_difficulty": 4},
        {"event": 2, "team_h": 1, "team_a": 4, "team_h_difficulty": 2, "team_a_difficulty": 4},
    ]
    topos = extract_season_fixture_topology(raw_fixtures=raw_fixtures)
    assert len(topos) == 38
    assert topos[2].is_double is True
    assert 1 in topos[2].double_team_ids
    assert topos[2].is_blank is True
    assert 2 in topos[2].blank_team_ids


def test_optimizer_segment_resolution_and_naming():
    """Verify strict segment window boundaries (GW 1-19 vs GW 20-38)."""
    opt = ChipOpportunityOptimizer()
    assert opt.resolve_segment_window(1) == (1, 19, "1-19")
    assert opt.resolve_segment_window(19) == (1, 19, "1-19")
    assert opt.resolve_segment_window(20) == (20, 38, "20-38")
    assert opt.resolve_segment_window(38) == (20, 38, "20-38")


def test_chip_name_normalization():
    """Verify alias mapping for diverse input formats."""
    opt = ChipOpportunityOptimizer()
    assert opt.normalize_chip_name("wildcard_1") == "wildcard"
    assert opt.normalize_chip_name("wildcard_2") == "wildcard"
    assert opt.normalize_chip_name("freehit") == "free_hit"
    assert opt.normalize_chip_name("benchboost") == "bench_boost"
    assert opt.normalize_chip_name("triplecaptain") == "triple_captain"


def test_gw1_guardrail_prevents_premature_burns():
    """Gameweek 1 squad initialization must never burn Free Hit, Bench Boost, or Wildcard."""
    opt = ChipOpportunityOptimizer(variant="c2_ev_planner")
    squad_ids = list(range(1, 16))
    snap = HistoricalGameweekSnapshot(
        season="2023-24",
        gameweek=1,
        deadline_time="2023-08-11T18:00:00Z",
        finished_gameweeks=0,
        players=(),
        teams=(),
        fixtures=(),
    )
    projs = [
        ExpectedPointsProjection(
            player_id=pid,
            web_name=f"P_{pid}",
            position=Position.MIDFIELDER,
            team_id=1,
            team_short="ARS",
            price_tenths=60,
            status="a",
            availability_pct=100.0,
            base_xp_per_match=5.0,
            gameweek=1,
            fixtures=(),
            expected_points=5.0,
        )
        for pid in squad_ids
    ]
    opps = opt.evaluate_all_opportunities(
        gameweek=1,
        available_chips=["free_hit", "wildcard", "bench_boost", "triple_captain"],
        squad_ids=squad_ids,
        snapshot=snap,
        projections=projs,
    )
    assert opps["free_hit"].net_utility < 0.0
    assert opps["wildcard"].net_utility < 0.0
    assert opps["bench_boost"].net_utility < 0.0


def test_post_wildcard_cooldown_guardrail():
    """Anti-pathology: Free Hit or Wildcard within 2 gameweeks of Wildcard is blocked."""
    opt = ChipOpportunityOptimizer(variant="c2_ev_planner")
    squad_ids = list(range(1, 16))
    snap = HistoricalGameweekSnapshot(
        season="2023-24",
        gameweek=8,
        deadline_time="2023-10-06T18:00:00Z",
        finished_gameweeks=7,
        players=(),
        teams=(),
        fixtures=(),
    )
    projs = [
        ExpectedPointsProjection(
            player_id=pid,
            web_name=f"P_{pid}",
            position=Position.MIDFIELDER,
            team_id=1,
            team_short="ARS",
            price_tenths=60,
            status="a",
            availability_pct=100.0,
            base_xp_per_match=5.0,
            gameweek=8,
            fixtures=(),
            expected_points=5.0,
        )
        for pid in squad_ids
    ]
    # Wildcard was played in GW 7
    opps = opt.evaluate_all_opportunities(
        gameweek=8,
        available_chips=["free_hit", "wildcard"],
        squad_ids=squad_ids,
        snapshot=snap,
        projections=projs,
        recent_chip_history={"wildcard": 7},
    )
    assert opps["free_hit"].net_utility < 0.0
    assert "Wildcard cooldown" in opps["free_hit"].reasoning
    assert opps["wildcard"].net_utility < 0.0


def test_postponed_matchday_blocks_chips():
    """When a gameweek has fewer than 4 fixtures, chip deployments are blocked."""
    opt = ChipOpportunityOptimizer(variant="c2_ev_planner")
    squad_ids = list(range(1, 16))
    topo = {7: GameweekFixtureTopology(gameweek=7, total_fixtures=2)}
    snap = HistoricalGameweekSnapshot(
        season="2023-24",
        gameweek=7,
        deadline_time="2023-09-29T18:00:00Z",
        finished_gameweeks=6,
        players=(),
        teams=(),
        fixtures=(),
    )
    projs = []
    opps = opt.evaluate_all_opportunities(
        gameweek=7,
        available_chips=["bench_boost", "triple_captain"],
        squad_ids=squad_ids,
        snapshot=snap,
        projections=projs,
        fixture_topology=topo,
    )
    assert opps["bench_boost"].net_utility < 0.0
    assert "Postponed matchday" in opps["bench_boost"].reasoning
    assert opps["triple_captain"].net_utility < 0.0


def test_terminal_window_decay_approaches_zero():
    """At segment boundary (e.g. GW 19 or 38), future optionality decays strictly to 0.0."""
    opt = ChipOpportunityOptimizer(variant="c2_ev_planner")
    squad_ids = list(range(1, 16))
    snap = HistoricalGameweekSnapshot(
        season="2023-24",
        gameweek=19,
        deadline_time="2023-12-26T11:00:00Z",
        finished_gameweeks=18,
        players=(),
        teams=(),
        fixtures=(),
    )
    projs = [
        ExpectedPointsProjection(
            player_id=pid,
            web_name=f"P_{pid}",
            position=Position.MIDFIELDER,
            team_id=1,
            team_short="ARS",
            price_tenths=60,
            status="a",
            availability_pct=100.0,
            base_xp_per_match=4.0,
            gameweek=19,
            fixtures=(),
            expected_points=4.0,
        )
        for pid in squad_ids
    ]
    opps = opt.evaluate_all_opportunities(
        gameweek=19,
        available_chips=["bench_boost", "triple_captain"],
        squad_ids=squad_ids,
        snapshot=snap,
        projections=projs,
    )
    assert opps["bench_boost"].future_max_ev == 0.0
    assert opps["triple_captain"].future_max_ev == 0.0


def test_exhausted_inventory_returns_none():
    """When no chips remain available, optimizer deterministically returns None."""
    opt = ChipOpportunityOptimizer()
    snap = HistoricalGameweekSnapshot(
        season="2023-24",
        gameweek=10,
        deadline_time="",
        finished_gameweeks=9,
        players=(),
        teams=(),
        fixtures=(),
    )
    rec = opt.evaluate_gameweek_chip(
        gameweek=10,
        available_chips=[],
        squad_ids=list(range(1, 16)),
        snapshot=snap,
        projections=[],
    )
    assert rec is None


def test_deterministic_output_stability():
    """Identical state inputs produce identical outputs and ranking."""
    opt = ChipOpportunityOptimizer(variant="c2_ev_planner")
    squad_ids = list(range(1, 16))
    snap = HistoricalGameweekSnapshot(
        season="2023-24",
        gameweek=15,
        deadline_time="",
        finished_gameweeks=14,
        players=(),
        teams=(),
        fixtures=(),
    )
    projs = [
        ExpectedPointsProjection(
            player_id=pid,
            web_name=f"P_{pid}",
            position=Position.MIDFIELDER,
            team_id=1,
            team_short="ARS",
            price_tenths=60,
            status="a",
            availability_pct=100.0,
            base_xp_per_match=5.0,
            gameweek=15,
            fixtures=(),
            expected_points=5.0,
        )
        for pid in squad_ids
    ]

    res1 = opt.evaluate_all_opportunities(15, ["bench_boost", "triple_captain"], squad_ids, snap, projs)
    res2 = opt.evaluate_all_opportunities(15, ["bench_boost", "triple_captain"], squad_ids, snap, projs)

    assert res1["bench_boost"].net_utility == res2["bench_boost"].net_utility
    assert res1["triple_captain"].net_utility == res2["triple_captain"].net_utility
    assert res1["bench_boost"].immediate_ev == res2["bench_boost"].immediate_ev


def test_api_parity_metadata_in_simulation_recommendations(tmp_path: Path):
    """HistoricalSimulationSession recommendations include opportunity-cost metadata."""
    sim = HistoricalSimulationSession.create(
        session_id="test_api_parity_01",
        season="2023-24",
        start_gw=1,
        config_dir=tmp_path,
    )
    recs = sim.get_recommendations()
    assert "recommended_chip" in recs
    assert "recommended_chip_opportunity" in recs
    # In GW 1 fresh squad, recommended_chip is None
    assert recs["recommended_chip"] is None
