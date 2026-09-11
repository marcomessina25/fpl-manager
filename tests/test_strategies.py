"""Unit tests for sequential simulation engine and baseline strategies (V0.7.2)."""

from pathlib import Path
import pytest

from fpl_manager.backtest.engine import (
    initialize_greedy_squad,
    run_sequential_simulation,
    select_best_lineup,
    simulate_autosubs_and_score,
)
from fpl_manager.backtest.strategies import NoTransferStrategy, SimpleXpStrategy
from fpl_manager.historical.ingestion import generate_mock_season
from fpl_manager.historical.models import GameweekOutcome, Position
from fpl_manager.historical.reconstruction import reconstruct_features_and_project
from fpl_manager.historical.snapshots import build_historical_snapshot
from fpl_manager.rules import validate_starting_lineup, validate_squad
from fpl_manager.models import Player


def test_select_best_lineup_formation_legality(tmp_path: Path) -> None:
    season_dir = tmp_path / "mock_season"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=3, num_teams=6, players_per_team=5)

    snap = build_historical_snapshot(season_dir, 1)
    projs = reconstruct_features_and_project(snap)
    squad_ids, _, _ = initialize_greedy_squad(snap, projs, budget_tenths=1000)

    assert len(squad_ids) == 15

    starters, bench, cap_id, vc_id, pred_xp = select_best_lineup(squad_ids, projs)
    assert len(starters) == 11
    assert len(bench) == 4
    assert cap_id in starters
    assert vc_id in starters
    assert cap_id != vc_id

    # Verify formation legality using production validator
    proj_map = {p.player_id: p for p in projs}
    squad_models = [
        Player(
            id=pid,
            name=proj_map[pid].web_name,
            position=proj_map[pid].position,
            team_id=proj_map[pid].team_id,
            price_tenths=proj_map[pid].price_tenths,
        )
        for pid in squad_ids
    ]
    val_res = validate_starting_lineup(squad_models, starters)
    assert val_res.is_valid is True, f"Formation invalid: {val_res.errors}"


def test_simulate_autosubs_and_captain_promotion() -> None:
    # 1 GKP (id 1), 3 DEF (ids 2, 3, 4), 5 MID (ids 5, 6, 7, 8, 9), 2 FWD (ids 10, 11)
    starting_ids = list(range(1, 12))
    # Bench: id 12 (DEF), id 13 (MID), id 14 (FWD), id 15 (GKP)
    bench_ids = [12, 13, 14, 15]

    positions = {
        1: Position.GOALKEEPER,
        2: Position.DEFENDER, 3: Position.DEFENDER, 4: Position.DEFENDER,
        5: Position.MIDFIELDER, 6: Position.MIDFIELDER, 7: Position.MIDFIELDER, 8: Position.MIDFIELDER, 9: Position.MIDFIELDER,
        10: Position.FORWARD, 11: Position.FORWARD,
        12: Position.DEFENDER, 13: Position.MIDFIELDER, 14: Position.FORWARD, 15: Position.GOALKEEPER,
    }

    # Scenario: Captain (id 11) played 0 mins. Vice-captain (id 10) scored 6 pts in 90 mins.
    # Starter Defender id 4 played 0 mins. Bench defender id 12 played 90 mins and scored 5 pts.
    outcomes = {
        1: GameweekOutcome("2023-24", 1, 1, 90, 6),
        2: GameweekOutcome("2023-24", 1, 2, 90, 6),
        3: GameweekOutcome("2023-24", 1, 3, 90, 6),
        4: GameweekOutcome("2023-24", 1, 4, 0, 0),    # DEF played 0 mins
        5: GameweekOutcome("2023-24", 1, 5, 90, 3),
        6: GameweekOutcome("2023-24", 1, 6, 90, 3),
        7: GameweekOutcome("2023-24", 1, 7, 90, 3),
        8: GameweekOutcome("2023-24", 1, 8, 90, 3),
        9: GameweekOutcome("2023-24", 1, 9, 90, 3),
        10: GameweekOutcome("2023-24", 1, 10, 90, 6), # VC
        11: GameweekOutcome("2023-24", 1, 11, 0, 0),   # C played 0 mins
        12: GameweekOutcome("2023-24", 1, 12, 90, 5), # Bench DEF
        13: GameweekOutcome("2023-24", 1, 13, 90, 4), # Bench MID
        14: GameweekOutcome("2023-24", 1, 14, 90, 2), # Bench FWD
        15: GameweekOutcome("2023-24", 1, 15, 0, 0),  # Bench GKP
    }

    gross_pts, autosubs, cap_promoted = simulate_autosubs_and_score(
        starting_ids=starting_ids,
        bench_ids=bench_ids,
        captain_id=11,
        vice_captain_id=10,
        outcomes=outcomes,
        player_positions=positions,
    )

    assert cap_promoted is True
    assert (4, 12) in autosubs  # id 4 subbed out for id 12 (DEF for DEF, keeping min 3 DEF)
    assert (11, 14) in autosubs # id 11 subbed out for id 14 (FWD for FWD, keeping max 5 MID)
    # Expected points:
    # Starters points: 1(6) + 2(6) + 3(6) + 12(5) + 5(3) + 6(3) + 7(3) + 8(3) + 9(3) + 10(6*2=12) + 14(2) = 52 pts
    assert gross_pts == 52


def test_no_transfer_baseline_simulation(tmp_path: Path) -> None:
    season_dir = tmp_path / "mock_season"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=4, num_teams=6, players_per_team=5)

    strategy = NoTransferStrategy()
    sim = run_sequential_simulation(season_dir, strategy, start_gw=1, end_gw=4)

    assert sim.strategy_name == "No-Transfer Baseline"
    assert sim.gameweeks_played == 4
    assert sim.total_transfers == 0
    assert sim.total_hits == 0
    assert sim.total_net_points > 0
    assert len(sim.history) == 4

    # Verify squad never changed
    init_squad = sim.history[0].squad_after
    for gw_res in sim.history:
        assert gw_res.squad_after == init_squad
        assert gw_res.transfers == ()


def test_simple_xp_strategy_simulation(tmp_path: Path) -> None:
    season_dir = tmp_path / "mock_season"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=4, num_teams=6, players_per_team=5)

    strategy = SimpleXpStrategy(min_gain_threshold=0.10)
    sim = run_sequential_simulation(season_dir, strategy, start_gw=1, end_gw=4)

    assert sim.strategy_name == "Simple xP Baseline"
    assert sim.gameweeks_played == 4
    assert sim.total_net_points > 0
    assert len(sim.history) == 4


def test_optimizer_strategy_simulation(tmp_path: Path) -> None:
    from fpl_manager.backtest.strategies import OptimizerStrategy

    season_dir = tmp_path / "mock_season"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=4, num_teams=6, players_per_team=5)

    strategy = OptimizerStrategy(max_transfers=1, min_net_gain=0.10)
    sim = run_sequential_simulation(season_dir, strategy, start_gw=1, end_gw=4)

    assert "Production Optimizer" in sim.strategy_name
    assert sim.gameweeks_played == 4
    assert sim.total_net_points > 0
    assert len(sim.history) == 4


def test_llm_advisor_strategy_and_comparison(tmp_path: Path) -> None:
    from fpl_manager.backtest.engine import compare_simulations
    from fpl_manager.backtest.strategies import LLMAdvisorStrategy, OptimizerStrategy

    season_dir = tmp_path / "mock_season"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=3, num_teams=6, players_per_team=5)

    # 1. Test LLM strategy with invalid recommendation: must reject, increment invalid count, and fall back safely
    def mock_invalid_advisor(gameweek, squad_ids, proposed_transfers, projections):
        # Recommend an invalid transfer (player 9999 doesn't exist)
        return {"transfers": [(squad_ids[0], 9999)]}

    llm_strat_invalid = LLMAdvisorStrategy(
        advisor_engine=mock_invalid_advisor,
        provider="mock-llm",
        model="gpt-test",
    )
    sim_invalid = run_sequential_simulation(season_dir, llm_strat_invalid, start_gw=1, end_gw=3)

    assert llm_strat_invalid.invalid_recommendations_count > 0
    assert len(llm_strat_invalid.decision_logs) == 3
    # Check that invalid decision was flagged and fallback occurred
    invalid_log = next(log for log in llm_strat_invalid.decision_logs if not log.is_valid)
    assert invalid_log.validation_error is not None
    assert invalid_log.executed_transfers == invalid_log.deterministic_transfers

    # 2. Test compare_simulations
    opt_strat = OptimizerStrategy(max_transfers=1)
    sim_opt = run_sequential_simulation(season_dir, opt_strat, start_gw=1, end_gw=3)

    comp = compare_simulations(sim_opt, sim_invalid)
    assert comp["gameweeks"] == 3
    assert "strategy_a" in comp
    assert "strategy_b" in comp
    assert "net_difference" in comp


