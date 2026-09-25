"""Tests for ML analysis, evaluation, and backtesting in V1.1 Strategic Squad Framework."""

from pathlib import Path
import pytest

from fpl_manager.backtest.strategic_analysis import (
    DATA_DIRECTORY,
    evaluate_starting_state,
    load_historical_strategic_players,
    run_constraint_sensitivity_analysis,
    run_error_attribution_analysis,
    run_horizon_sensitivity_analysis,
    run_initial_squad_backtest,
    run_prediction_decision_ablation,
    run_starting_state_ablation,
    run_strategic_profiles_analysis,
    run_wildcard_backtest,
)
from fpl_manager.strategic_squad import StrategicConstraints, solve_strategic_squad


@pytest.fixture
def sample_season_dir() -> Path:
    """Provides path to verified historical season dataset."""
    season_dir = DATA_DIRECTORY / "historical" / "2024-25"
    if not season_dir.exists():
        pytest.skip(f"Historical data directory not found: {season_dir}")
    return season_dir


def test_load_historical_strategic_players_no_leakage(sample_season_dir: Path) -> None:
    """Verify point-in-time player loading contains valid candidate pool without future leakage."""
    players, teams = load_historical_strategic_players(
        sample_season_dir,
        gameweek=1,
        horizon=5,
        predictor_version="v1.0.1",
    )
    assert len(players) >= 400
    assert len(teams) == 20

    # Verify positions and prices are valid
    pos_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for p in players:
        assert p.id > 0
        assert p.price_tenths > 0
        pos_counts[p.position.value] += 1
        # Multi-gameweek projections should cover horizon (GW1 to GW5)
        if hasattr(p, "multi_gw_xp") and p.multi_gw_xp:
            for gw in range(1, 6):
                assert gw in p.multi_gw_xp
                assert p.multi_gw_xp[gw] >= 0.0

    assert pos_counts[1] >= 40  # GKP
    assert pos_counts[2] >= 100  # DEF
    assert pos_counts[3] >= 100  # MID
    assert pos_counts[4] >= 50   # FWD


def test_evaluate_starting_state_metrics(sample_season_dir: Path) -> None:
    """Verify starting-state quality metrics calculation across expected, realized, and flexibility."""
    players, _ = load_historical_strategic_players(sample_season_dir, gameweek=1, horizon=5)
    constraints = StrategicConstraints(budget_tenths=1000, target_gameweeks=(1, 2, 3, 4, 5))
    cand = solve_strategic_squad(players, constraints, strategy="balanced", mode="initial")

    metrics = evaluate_starting_state(
        season_dir=sample_season_dir,
        squad_ids=cand.player_ids,
        start_gw=1,
        horizon=5,
        candidate=cand,
    )

    assert metrics["squad_size"] == 15
    assert metrics["squad_cost_tenths"] <= 1000
    assert metrics["bank_tenths"] >= 0
    assert "horizon_expected_points" in metrics
    assert "realized_horizon_points" in metrics
    assert "expected_vs_realized_delta" in metrics
    assert "captaincy_opportunity" in metrics
    assert "future_transfer_flexibility" in metrics
    assert "corrective_transfers_early" in metrics
    assert "gw_breakdown" in metrics
    assert len(metrics["gw_breakdown"]) == 5


def test_factorial_ablation_matrix(tmp_path: Path) -> None:
    """Verify 2x2x2 factorial ablation matrix and main effects decomposition."""
    res = run_starting_state_ablation(
        season="2024-25",
        horizon=3,
        end_gw=3,
        save_report=True,
        output_dir=tmp_path / "ablation",
    )

    assert res["season"] == "2024-25"
    assert "matrix" in res
    assert len(res["matrix"]) == 8  # 2^3 factorial cells
    assert "main_effects" in res
    main_effects = res["main_effects"]
    assert "starting_state_effect" in main_effects
    assert "predictor_effect" in main_effects
    assert "decision_engine_effect" in main_effects

    # Check report files written via report_path
    assert "report_path" in res
    assert Path(res["report_path"]).exists()
    assert Path(res["report_path"]).with_suffix(".json").exists()


def test_error_attribution_taxonomy(tmp_path: Path) -> None:
    """Verify counterfactual error attribution maps lost points to the 5 standard categories."""
    res = run_error_attribution_analysis(
        season="2024-25",
        horizon=3,
        end_gw=3,
        save_report=True,
        output_dir=tmp_path / "error_attrib",
    )

    assert res["season"] == "2024-25"
    assert "error_counts" in res
    assert "lost_points_by_category" in res

    categories = {
        "STARTING_STATE_ERROR",
        "PREDICTION_ERROR",
        "DECISION_ERROR",
        "INTERACTION_ERROR",
        "HARMLESS",
    }
    assert set(res["error_counts"].keys()) == categories
    assert set(res["lost_points_by_category"].keys()) == categories

    for cat in categories:
        assert res["error_counts"][cat] >= 0
        assert res["lost_points_by_category"][cat] >= 0

    assert "report_path" in res
    assert Path(res["report_path"]).exists()
    assert Path(res["report_path"]).with_suffix(".json").exists()


def test_constraint_sensitivity_analysis(tmp_path: Path) -> None:
    """Verify sensitivity to budget, locks, and exclusions."""
    res = run_constraint_sensitivity_analysis(
        season="2024-25",
        horizon=3,
        save_report=True,
        output_dir=tmp_path / "constraints",
    )

    assert res["season"] == "2024-25"
    assert "scenarios" in res
    scenarios = res["scenarios"]
    assert any("baseline" in s.lower() for s in scenarios.keys())
    assert any("bank" in s.lower() or "budget" in s.lower() for s in scenarios.keys())
    assert any("lock" in s.lower() for s in scenarios.keys())
    assert any("exclude" in s.lower() for s in scenarios.keys())

    for sc_name, sc_data in scenarios.items():
        assert "objective" in sc_data
        assert "opportunity_cost" in sc_data
        assert "net_points_gw10" in sc_data

    assert "report_path" in res
    assert Path(res["report_path"]).exists()
    assert Path(res["report_path"]).with_suffix(".json").exists()


def test_horizon_sensitivity_analysis(tmp_path: Path) -> None:
    """Verify performance variation across planning horizons."""
    res = run_horizon_sensitivity_analysis(
        season="2024-25",
        horizons=(1, 3),
        end_gw=3,
        save_report=True,
        output_dir=tmp_path / "horizons",
    )

    assert res["season"] == "2024-25"
    assert "horizons_evaluated" in res
    assert set(res["horizons_evaluated"]) == {1, 3}
    assert "data" in res
    assert 1 in res["data"]
    assert 3 in res["data"]

    assert "report_path" in res
    assert Path(res["report_path"]).exists()
    assert Path(res["report_path"]).with_suffix(".json").exists()


def test_strategic_profiles_and_wildcard_backtest(tmp_path: Path) -> None:
    """Verify strategic candidate profile evaluation and wildcard reconstruction."""
    prof_res = run_strategic_profiles_analysis(
        season="2024-25",
        horizon=3,
        end_gw=3,
        save_report=True,
        output_dir=tmp_path / "profiles",
    )
    assert "profiles" in prof_res
    assert "report_path" in prof_res
    assert Path(prof_res["report_path"]).exists()

    wc_res = run_wildcard_backtest(
        season="2024-25",
        wildcard_gw=5,
        horizon=3,
        window_len=3,
        save_report=True,
        output_dir=tmp_path / "wildcard",
    )
    assert "wildcard_gw" in wc_res
    assert "report_path" in wc_res
    assert Path(wc_res["report_path"]).exists()


def test_factorial_ablation_full_interactions_p03(tmp_path: Path) -> None:
    """Verify complete 2x2x2 factorial decomposition including pairwise and 3-way interactions (P0.3)."""
    res = run_starting_state_ablation(
        season="2024-25",
        horizon=3,
        end_gw=3,
        save_report=True,
        output_dir=tmp_path / "ablation",
    )

    assert "main_effects" in res
    assert "interactions" in res
    assert "reconstruction_verification" in res

    # Verify all effects and interactions are present
    assert "starting_state_effect" in res["main_effects"]
    assert "predictor_effect" in res["main_effects"]
    assert "decision_engine_effect" in res["main_effects"]

    assert "state_x_predictor" in res["interactions"]
    assert "state_x_decision_engine" in res["interactions"]
    assert "predictor_x_decision_engine" in res["interactions"]
    assert "state_x_predictor_x_decision_engine" in res["interactions"]

    # Verify orthogonal reconstruction
    assert res["reconstruction_verification"]["is_orthogonal"] is True
    assert res["reconstruction_verification"]["max_residual"] < 1e-6
    assert len(res["completed_cells"]) == 8
    assert len(res["missing_cells"]) == 0


def test_heuristic_error_diagnostics_p04(tmp_path: Path) -> None:
    """Verify error diagnostics are characterized as heuristic rules rather than counterfactual causal claims (P0.4)."""
    from fpl_manager.backtest.strategic_analysis import run_decision_error_diagnostics

    res = run_decision_error_diagnostics(
        season="2024-25",
        horizon=3,
        end_gw=3,
        save_report=True,
        output_dir=tmp_path / "diagnostics",
    )

    assert res["diagnostic_type"] == "heuristic"
    assert res["methodology"] == "heuristic_rule_based_attribution"
    assert "error_counts" in res
    assert "diagnostic_lost_points_by_category" in res

    # Verify markdown report does not use unsupported causal claims
    report_text = Path(res["report_path"]).read_text(encoding="utf-8")
    assert "Heuristic Decision Error Diagnostics" in report_text
    assert "not mathematically identified counterfactual causal attribution" in report_text


def test_strategic_initialization_no_silent_fallback_p02(sample_season_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that V1.1 strategic initialization failure raises StrategicInitializationError instead of silently falling back (P0.2)."""
    import fpl_manager.strategic_squad
    from fpl_manager.backtest.engine import run_sequential_simulation, StrategicInitializationError
    from fpl_manager.backtest.strategies import OptimizerStrategy

    opt_strat = OptimizerStrategy(max_transfers=1, decision_engine="v1.1")

    def mock_solve(*args, **kwargs):
        raise RuntimeError("Simulated solver failure")

    monkeypatch.setattr(fpl_manager.strategic_squad, "solve_strategic_squad", mock_solve)

    with pytest.raises(StrategicInitializationError, match="V1.1 strategic initialization failed"):
        run_sequential_simulation(
            season_dir=sample_season_dir,
            strategy=opt_strat,
            start_gw=1,
            end_gw=2,
            predictor_version="v1.1",
            decision_engine="v1.1",
        )

