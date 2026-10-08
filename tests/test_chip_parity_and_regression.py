"""Integration parity and regression tests between live and historical chip recommendation pipelines."""

import json
from pathlib import Path
import pytest

from fpl_manager.chip_strategy import (
    SeasonalChipInventory,
    SeasonalChipPolicy,
    recommend_chip_strategy,
)
from fpl_manager.expected_points import ExpectedPointsProjection
from fpl_manager.historical.models import (
    HistoricalGameweekSnapshot,
    HistoricalPlayerState,
    Position,
)
from fpl_manager.simulation.chip_optimizer import (
    ChipOpportunityOptimizer,
    extract_season_fixture_topology,
)
from fpl_manager.simulation.session import HistoricalSimulationSession
from fpl_manager.storage import SnapshotStore, utc_timestamp


def test_parity_optimizer_candidate_ranking_in_live_and_simulation():
    """Verify that both live and historical pathways utilize identical opportunity valuations."""
    opt_c1 = ChipOpportunityOptimizer(variant="c1_linear_decay")
    opt_c2 = ChipOpportunityOptimizer(variant="c2_ev_planner")

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
            web_name=f"Player_{pid}",
            position=Position.MIDFIELDER,
            team_id=((pid - 1) % 5) + 1,
            team_short="ARS",
            price_tenths=60,
            status="a",
            availability_pct=100.0,
            base_xp_per_match=4.5 if pid != 13 else 9.0,
            gameweek=15,
            fixtures=(),
            expected_points=4.5 if pid != 13 else 9.0,
        )
        for pid in squad_ids
    ]

    # Evaluate opportunities through optimizer
    available = ["bench_boost", "triple_captain", "free_hit", "wildcard"]
    opps_c2 = opt_c2.evaluate_all_opportunities(15, available, squad_ids, snap, projs)
    
    # 1. Triple Captain immediate EV must equal top captain projected points
    assert opps_c2["triple_captain"].immediate_ev == pytest.approx(9.0, 0.1)

    # 2. Bench Boost immediate EV must equal lowest 4 squad players sum
    # Bench players have 4.5 pts each -> 4 * 4.5 = 18.0 pts
    assert opps_c2["bench_boost"].immediate_ev == pytest.approx(18.0, 0.1)

    # 3. Decision recommendation from SeasonalChipPolicy(use_optimizer=True) matches optimizer
    policy_c1 = SeasonalChipPolicy(use_optimizer=True, optimizer_variant="c1_linear_decay")
    inv = SeasonalChipInventory(
        wildcard_w1=True, free_hit_w1=True, triple_captain_w1=True, bench_boost_w1=True
    )
    pol_rec = policy_c1.evaluate_gameweek_chip(15, inv, squad_ids, snap, projs)
    opt_rec = opt_c1.evaluate_gameweek_chip(15, available, squad_ids, snap, projs)

    assert pol_rec == opt_rec, f"Policy rec {pol_rec} != Optimizer rec {opt_rec}"


def test_parity_live_api_and_simulation_session_schema(tmp_path: Path):
    """Verify live recommend_chip_strategy and historical simulation session share identical metadata fields."""
    db_path = tmp_path / "fpl.sqlite3"
    squad_path = tmp_path / "current_squad.json"

    store = SnapshotStore(db_path)
    store.initialize()

    bootstrap = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Liverpool", "short_name": "LIV"},
        ],
        "elements": [],
    }
    for p_id in range(1, 16):
        bootstrap["elements"].append({
            "id": p_id,
            "web_name": f"P_{p_id}",
            "team": 1 if p_id <= 8 else 2,
            "element_type": 3,
            "now_cost": 60,
            "status": "a",
            "total_points": 30,
            "selected_by_percent": "10.0",
        })

    fixtures = [
        {"id": 1, "event": 10, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": False},
        {"id": 2, "event": 11, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": False},
    ]
    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    squad_path.write_text(
        json.dumps({
            "season": "2026/27",
            "free_transfers": 1,
            "bank_tenths": 10,
            "player_ids": list(range(1, 16)),
            "purchase_prices_tenths": {str(i): 60 for i in range(1, 16)},
        }),
        encoding="utf-8",
    )

    # 1. Live recommendation
    live_res = recommend_chip_strategy(
        squad_path=squad_path,
        database_path=db_path,
        start_gw=10,
        end_gw=12,
    )

    # Verify live recommended schedule candidate metadata keys
    for cand in live_res.get("recommended_schedule", []):
        assert "immediate_ev" in cand
        assert "future_opportunity" in cand
        assert "net_utility" in cand
        assert "confidence" in cand

    # 2. Historical simulation recommendation
    sim = HistoricalSimulationSession.create(
        session_id="test_schema_parity",
        season="2023-24",
        start_gw=10,
        config_dir=tmp_path / "sims",
    )
    sim_recs = sim.get_recommendations()
    assert "recommended_chip" in sim_recs
    assert "recommended_chip_opportunity" in sim_recs


def test_regression_c0_vs_c1_resolves_wildcard_hoarding():
    """Verify on a deteriorated squad state that C1 deploys Wildcard while legacy C0 hoards."""
    squad_ids = list(range(1, 16))
    snap = HistoricalGameweekSnapshot(
        season="2023-24",
        gameweek=12,
        deadline_time="",
        finished_gameweeks=11,
        players=(),
        teams=(),
        fixtures=(),
    )
    # Deteriorated squad: 3 players injured/collapsed
    projs = []
    for pid in squad_ids:
        if pid in (1, 2, 3):
            # Collapsed / zero minutes
            p = ExpectedPointsProjection(
                player_id=pid,
                web_name=f"Injured_{pid}",
                position=Position.DEFENDER,
                team_id=1,
                team_short="ARS",
                price_tenths=50,
                status="i",
                availability_pct=0.0,
                base_xp_per_match=0.0,
                gameweek=12,
                fixtures=(),
                expected_points=0.0,
            )
        else:
            p = ExpectedPointsProjection(
                player_id=pid,
                web_name=f"Player_{pid}",
                position=Position.MIDFIELDER,
                team_id=2,
                team_short="LIV",
                price_tenths=65,
                status="a",
                availability_pct=100.0,
                base_xp_per_match=5.0,
                gameweek=12,
                fixtures=(),
                expected_points=5.0,
            )
        projs.append(p)

    opt_c0 = ChipOpportunityOptimizer(variant="c0_baseline")
    opt_c1 = ChipOpportunityOptimizer(variant="c1_linear_decay")

    # Only Wildcard available
    available = ["wildcard"]

    dec_c0 = opt_c0.evaluate_gameweek_chip(12, available, squad_ids, snap, projs)
    dec_c1 = opt_c1.evaluate_gameweek_chip(12, available, squad_ids, snap, projs)

    # Legacy C0 requires >= 4 deteriorated players -> does not trigger (hoards)
    assert dec_c0 is None, "Legacy C0 unexpectedly triggered Wildcard!"

    # Dynamic C1 scales required collapsed threshold with remaining window (rem_fraction ~ 0.42 -> wc_thresh = max(1, int(4*0.42)) = 1)
    # 3 collapsed >= 1 -> triggers Wildcard!
    assert dec_c1 == "wildcard", "C1 failed to trigger Wildcard for deteriorated squad!"
