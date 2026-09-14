"""Unit and integration tests for V0.9 Phase 6 (xP integration) and Phase 7 (Decision A/B)."""

from pathlib import Path
import pytest

from fpl_manager.backtest.engine import (
    GameweekDecisionResult,
    SimulationResult,
    run_decision_backtest,
    run_sequential_simulation,
)
from fpl_manager.backtest.reporting import format_decision_report
from fpl_manager.backtest.strategies import NoTransferStrategy, SimpleXpStrategy
from fpl_manager.expected_points import (
    project_gameweek,
    project_multi_gameweek_profiles,
    project_player_gameweek,
)
from fpl_manager.historical.ingestion import generate_mock_season
from fpl_manager.models import Position
from fpl_manager.storage import SnapshotStore, utc_timestamp


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "fpl_test.sqlite3"
    store = SnapshotStore(db_path)

    bootstrap = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Chelsea", "short_name": "CHE"},
        ],
        "elements": [
            {"id": 10, "web_name": "Saka", "team": 1, "element_type": 3, "now_cost": 100, "status": "a", "total_points": 25},
            {"id": 20, "web_name": "Palmer", "team": 2, "element_type": 3, "now_cost": 105, "status": "a", "total_points": 28},
        ],
    }

    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 4, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 2, "team_a": 1, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())
    return db_path


def test_project_gameweek_v09_default(test_db: Path) -> None:
    # Default should be v0.9
    projs = project_gameweek(gameweek=2, database_path=test_db)
    assert len(projs) == 2
    for p in projs:
        assert p.expected_points > 0.0
        assert p.expected_minutes > 0.0
        assert 0.0 <= p.start_probability <= 1.0
        assert 0.0 <= p.play_probability <= 1.0


def test_project_multi_gameweek_profiles_v09(test_db: Path) -> None:
    profiles = project_multi_gameweek_profiles(gameweeks=[2], database_path=test_db, predictor_version="v0.9")
    assert len(profiles) == 2
    for pid, prof in profiles.items():
        assert prof.expected_points > 0.0
        assert prof.expected_minutes > 0.0
        assert prof.fixtures_count == 1


def test_gameweek_decision_result_v09_metrics() -> None:
    res = GameweekDecisionResult(
        gameweek=1,
        squad_before=(1, 2),
        transfers=((1, 3),),
        squad_after=(2, 3),
        starting_ids=(2, 3),
        bench_ids=(),
        captain_id=2,
        vice_captain_id=3,
        predicted_lineup_xp=12.5,
        transfer_hits=0,
        gross_points=14,
        net_points=14,
        autosubs=(),
        captain_promoted=False,
        zero_min_starters=(2,),
        bench_regret_points=4,
        captain_zero_mins=True,
        transfers_gross_gain=6,
        transfers_net_gain=6,
    )
    assert res.zero_min_starters == (2,)
    assert res.bench_regret_points == 4
    assert res.captain_zero_mins is True
    assert res.transfers_gross_gain == 6
    assert res.transfers_net_gain == 6


def test_format_decision_report_ab_table() -> None:
    gw_res = GameweekDecisionResult(
        gameweek=1,
        squad_before=(),
        transfers=(),
        squad_after=(),
        starting_ids=(),
        bench_ids=(),
        captain_id=1,
        vice_captain_id=2,
        predicted_lineup_xp=45.0,
        transfer_hits=0,
        gross_points=50,
        net_points=50,
        autosubs=(),
        captain_promoted=False,
        zero_min_starters=(),
        bench_regret_points=5,
        captain_zero_mins=False,
        transfers_gross_gain=8,
        transfers_net_gain=8,
    )

    sim_v09 = SimulationResult(
        strategy_name="Optimizer",
        season="2023-24",
        start_gw=1,
        end_gw=1,
        gameweeks_played=1,
        total_net_points=50,
        total_gross_points=50,
        total_hits=0,
        total_transfers=1,
        final_bank_tenths=10,
        history=(gw_res,),
        total_zero_min_starters=0,
        captain_zero_min_count=0,
        total_bench_regret_points=5,
        total_transfer_gross_gain=8,
        total_transfer_net_gain=8,
        predictor_version="v0.9",
    )

    sim_v08 = SimulationResult(
        strategy_name="Optimizer",
        season="2023-24",
        start_gw=1,
        end_gw=1,
        gameweeks_played=1,
        total_net_points=42,
        total_gross_points=42,
        total_hits=0,
        total_transfers=1,
        final_bank_tenths=10,
        history=(gw_res,),
        total_zero_min_starters=1,
        captain_zero_min_count=1,
        total_bench_regret_points=12,
        total_transfer_gross_gain=0,
        total_transfer_net_gain=0,
        predictor_version="v0.8",
    )

    report = format_decision_report([sim_v09, sim_v08], season="2023-24", start_gw=1, end_gw=1)
    assert "Decision Quality, Transfer ROI & Participation Risk Decomposition" in report
    assert "`v0.9`" in report
    assert "`v0.8`" in report
    assert "+8 pts" in report


def test_run_decision_backtest_mock_season_v09(tmp_path: Path) -> None:
    season_dir = tmp_path / "mock_season"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=3, num_teams=6, players_per_team=5)

    sims = run_decision_backtest(
        season_dir=season_dir,
        strategy="notransfer",
        start_gw=1,
        end_gw=2,
        predictor_version="v0.9",
    )

    assert len(sims) == 1
    sim = sims[0]
    assert sim.predictor_version == "v0.9"
    assert sim.gameweeks_played == 2
    assert sim.total_net_points >= 0
    assert sim.total_zero_min_starters >= 0
    assert sim.total_bench_regret_points >= 0
