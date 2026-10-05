"""Unit tests for V1.3.5 Optimizer Ablation Framework and Decision-Regret Decomposition."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from fpl_manager.backtest.decision_engine import resolve_decision_engine
from fpl_manager.backtest.optimizer_ablation import (
    ABLATION_VARIANTS,
    DecisionEngineAblation,
    DecisionRegretRecord,
    OptimizerAblationConfig,
    compute_gameweek_decision_regret,
)
from fpl_manager.expected_points import ExpectedPointsProjection
from fpl_manager.historical.models import (
    HistoricalFixture,
    HistoricalGameweekSnapshot,
    HistoricalPlayerState,
    Position,
)


class TestOptimizerAblationVariants(unittest.TestCase):
    """Test ablation configurations and factory mappings."""

    def test_canonical_variants_present(self):
        expected_keys = {"B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "Full"}
        self.assertTrue(expected_keys.issubset(set(ABLATION_VARIANTS.keys())))

    def test_b0_control_configuration(self):
        b0 = ABLATION_VARIANTS["B0"]
        self.assertEqual(b0.horizon, 1)
        self.assertEqual(b0.bench_weight, 0.0)
        self.assertFalse(b0.gk_hurdle)
        self.assertEqual(b0.candidate_pool_size, 5)
        self.assertEqual(b0.dead_capital_weight, 0.0)
        self.assertFalse(b0.chip_aware)
        self.assertEqual(b0.initial_strategy_mode, "v10_heuristic")

    def test_b1_multi_gw_horizon(self):
        b1 = ABLATION_VARIANTS["B1"]
        self.assertEqual(b1.horizon, 3)
        self.assertEqual(b1.bench_weight, 0.0)
        self.assertFalse(b1.gk_hurdle)
        self.assertEqual(b1.candidate_pool_size, 5)
        self.assertEqual(b1.dead_capital_weight, 0.0)

    def test_b2_extended_horizon(self):
        b2 = ABLATION_VARIANTS["B2"]
        self.assertEqual(b2.horizon, 5)
        self.assertEqual(b2.bench_weight, 0.0)

    def test_b3_bench_aware(self):
        b3 = ABLATION_VARIANTS["B3"]
        self.assertEqual(b3.horizon, 3)
        self.assertEqual(b3.bench_weight, 0.15)
        self.assertFalse(b3.gk_hurdle)

    def test_b4_gk_hurdle(self):
        b4 = ABLATION_VARIANTS["B4"]
        self.assertEqual(b4.horizon, 3)
        self.assertEqual(b4.bench_weight, 0.15)
        self.assertTrue(b4.gk_hurdle)
        self.assertEqual(b4.candidate_pool_size, 5)

    def test_b5_pool_expansion(self):
        b5 = ABLATION_VARIANTS["B5"]
        self.assertEqual(b5.horizon, 3)
        self.assertEqual(b5.candidate_pool_size, 25)
        self.assertEqual(b5.dead_capital_weight, 0.0)

    def test_b6_flexibility_dead_capital(self):
        b6 = ABLATION_VARIANTS["B6"]
        self.assertEqual(b6.dead_capital_weight, 3.0)
        self.assertFalse(b6.chip_aware)

    def test_b7_full_chip_aware(self):
        b7 = ABLATION_VARIANTS["B7"]
        self.assertEqual(b7.horizon, 3)
        self.assertEqual(b7.bench_weight, 0.15)
        self.assertTrue(b7.gk_hurdle)
        self.assertEqual(b7.candidate_pool_size, 25)
        self.assertEqual(b7.dead_capital_weight, 3.0)
        self.assertTrue(b7.chip_aware)
        self.assertEqual(b7.initial_strategy_mode, "strategic_balanced")

    def test_full_variant_parity_with_b7(self):
        b7 = ABLATION_VARIANTS["B7"]
        full = ABLATION_VARIANTS["Full"]
        self.assertEqual(b7.to_dict(), {**full.to_dict(), "name": "B7", "description": b7.description})

    def test_v135_prod_configuration(self):
        v135 = ABLATION_VARIANTS["V135_PROD"]
        self.assertEqual(v135.horizon, 3)
        self.assertEqual(v135.gamma, 0.75)
        self.assertEqual(v135.bench_weight, 0.15)
        self.assertTrue(v135.gk_hurdle)
        self.assertEqual(v135.candidate_pool_size, 5)
        self.assertEqual(v135.dead_capital_weight, 3.0)
        self.assertTrue(v135.chip_aware)
        self.assertEqual(v135.initial_strategy_mode, "strategic_maximum_ev")


class TestDecisionEngineAblationWiring(unittest.TestCase):
    """Test engine instantiation, resolution, and mechanics."""

    def test_resolve_ablation_engines(self):
        for i in range(8):
            eng = resolve_decision_engine(f"b{i}")
            self.assertIsInstance(eng, DecisionEngineAblation)
            self.assertEqual(eng.config.name, f"B{i}")

        eng_abl = resolve_decision_engine("ablation")
        self.assertIsInstance(eng_abl, DecisionEngineAblation)
        self.assertEqual(eng_abl.config.name, "B7")

    def test_resolve_v135_hardened_production(self):
        from fpl_manager.backtest.decision_engine import DecisionEngineV135
        eng_v135 = resolve_decision_engine("v1.3.5")
        self.assertIsInstance(eng_v135, DecisionEngineV135)
        self.assertEqual(eng_v135.version, "v1.3.5")
        self.assertEqual(eng_v135.horizon, 3)
        self.assertEqual(eng_v135.gamma, 0.75)
        self.assertEqual(eng_v135.bench_weight, 0.15)
        self.assertEqual(eng_v135.max_results, 5)
        self.assertEqual(eng_v135.gk_min_net_gain, 3.00)
        self.assertEqual(eng_v135.initial_strategy, "maximum_ev")

    def test_gk_hurdle_enforcement_ablation(self):
        eng_no_hurdle = DecisionEngineAblation("B3")
        eng_with_hurdle = DecisionEngineAblation("B4")

        mock_gk = MagicMock()
        mock_gk.position = Position.GOALKEEPER
        mock_proj = MagicMock()
        mock_proj.play_probability = 1.0

        opt_map = {1: mock_gk}
        proj_map = {1: mock_proj}

        # B3 has gk_hurdle=False: must return outfield minimum (0.50)
        hurdle_b3 = eng_no_hurdle._get_transfer_hurdle([1], opt_map, proj_map, min_net_gain=0.50)
        self.assertEqual(hurdle_b3, 0.50)

        # B4 has gk_hurdle=True: must enforce 3.00 hurdle for healthy GK
        hurdle_b4 = eng_with_hurdle._get_transfer_hurdle([1], opt_map, proj_map, min_net_gain=0.50)
        self.assertEqual(hurdle_b4, 3.00)

    def test_candidate_pool_size_and_initial_strategy_propagation(self):
        b4 = DecisionEngineAblation("B4")
        b5 = DecisionEngineAblation("B5")
        b6 = DecisionEngineAblation("B6")

        self.assertEqual(b4.cand_limit, 5)
        self.assertEqual(b4.initial_strategy, "v10_heuristic")

        self.assertEqual(b5.cand_limit, 25)
        self.assertEqual(b5.initial_strategy, "v10_heuristic")

        self.assertEqual(b6.cand_limit, 25)
        self.assertEqual(b6.initial_strategy, "strategic_balanced")

    def test_simulation_execution_duration_recorded(self):
        from pathlib import Path
        from fpl_manager.backtest.engine import run_sequential_simulation
        from fpl_manager.backtest.strategies import OptimizerStrategy

        season_dir = Path("data/historical/2024-25")
        eng = DecisionEngineAblation("B0")
        strat = OptimizerStrategy(1, decision_engine=eng)
        res = run_sequential_simulation(season_dir, strat, decision_engine=eng, start_gw=1, end_gw=2, use_chips=False)

        self.assertEqual(len(res.history), 2)
        for h in res.history:
            self.assertGreater(h.execution_duration_ms, 0.0)



class TestDecisionRegretDecomposition(unittest.TestCase):
    """Test mathematical correctness and invariant identities of the Decision-Regret Framework."""

    def test_regret_record_identity(self):
        rec = DecisionRegretRecord(
            season="2024-25",
            gameweek=5,
            variant="B7",
            selected_action=[(10, 20)],
            selected_model_value=3.5,
            realized_selected_points=52.0,
            best_action_model=[(10, 30)],
            best_model_value=4.2,
            realized_best_model_points=56.0,
            best_action_hindsight=[(10, 40)],
            realized_hindsight_points=64.0,
            prediction_regret=8.0,  # 64 - 56
            optimizer_regret=4.0,   # 56 - 52
            total_decision_regret=12.0,  # 64 - 52
            runtime_ms=12.5,
        )

        self.assertAlmostEqual(
            rec.prediction_regret + rec.optimizer_regret,
            rec.total_decision_regret,
            places=4,
            msg="Mathematical identity failed: Prediction Regret + Optimizer Regret != Total Decision Regret",
        )
        self.assertGreaterEqual(rec.prediction_regret, 0.0)
        self.assertGreaterEqual(rec.optimizer_regret, 0.0)
        self.assertGreaterEqual(rec.total_decision_regret, 0.0)


class TestAblationVariantsDivergence(unittest.TestCase):
    """Test that ablation variants actually change optimization behavior and decisions in practice."""

    def test_b4_vs_b5_candidate_pool_expansion_divergence(self):
        """Candidate pool size (5 vs 25) must measurably change transfer discovery and selection."""
        from pathlib import Path
        from fpl_manager.backtest.engine import run_sequential_simulation
        from fpl_manager.backtest.strategies import OptimizerStrategy

        season_dir = Path("data/historical/2024-25")
        b4 = DecisionEngineAblation(ABLATION_VARIANTS["B4"])
        b5 = DecisionEngineAblation(ABLATION_VARIANTS["B5"])

        r4 = run_sequential_simulation(season_dir, OptimizerStrategy(1, decision_engine=b4), decision_engine=b4, start_gw=1, end_gw=3, use_chips=False)
        r5 = run_sequential_simulation(season_dir, OptimizerStrategy(1, decision_engine=b5), decision_engine=b5, start_gw=1, end_gw=3, use_chips=False)

        # In GW 3, B4 (pool 5) selects player 91 while B5 (pool 25) discovers higher-utility player 469
        self.assertNotEqual(r4.history[2].transfers, r5.history[2].transfers)
        self.assertEqual(r4.history[2].transfers, ((396, 91),))
        self.assertEqual(r5.history[2].transfers, ((396, 469),))

    def test_b3_vs_b4_transfer_decision_divergence(self):
        """Role-specific GK hurdles must measurably alter transfer choices over the season."""
        from pathlib import Path
        from fpl_manager.backtest.engine import run_sequential_simulation
        from fpl_manager.backtest.strategies import OptimizerStrategy

        season_dir = Path("data/historical/2024-25")
        b3 = DecisionEngineAblation(ABLATION_VARIANTS["B3"])
        b4 = DecisionEngineAblation(ABLATION_VARIANTS["B4"])

        r3 = run_sequential_simulation(season_dir, OptimizerStrategy(1, decision_engine=b3), decision_engine=b3, start_gw=1, end_gw=10, use_chips=False)
        r4 = run_sequential_simulation(season_dir, OptimizerStrategy(1, decision_engine=b4), decision_engine=b4, start_gw=1, end_gw=10, use_chips=False)

        # By GW 10, transfer trajectories have diverged due to role hurdle enforcement
        self.assertNotEqual(r3.history[9].transfers, r4.history[9].transfers)
        self.assertEqual(r3.history[9].transfers, ((413, 383),))
        self.assertEqual(r4.history[9].transfers, ((17, 99),))

    def test_starting_state_divergence(self):
        """Starting State A (v10_heuristic), B (strategic_balanced), and C (strategic_maximum_ev) produce distinct initial squads."""
        from pathlib import Path
        from fpl_manager.backtest.engine import run_sequential_simulation
        from fpl_manager.backtest.strategies import OptimizerStrategy

        season_dir = Path("data/historical/2024-25")
        eng_a = DecisionEngineAblation(OptimizerAblationConfig(name="A", description="State A", initial_strategy_mode="v10_heuristic"))
        eng_b = DecisionEngineAblation(OptimizerAblationConfig(name="B", description="State B", initial_strategy_mode="strategic_balanced"))
        eng_c = DecisionEngineAblation(OptimizerAblationConfig(name="C", description="State C", initial_strategy_mode="strategic_maximum_ev"))

        ra = run_sequential_simulation(season_dir, OptimizerStrategy(1, decision_engine=eng_a), decision_engine=eng_a, start_gw=1, end_gw=1, use_chips=False)
        rb = run_sequential_simulation(season_dir, OptimizerStrategy(1, decision_engine=eng_b), decision_engine=eng_b, start_gw=1, end_gw=1, use_chips=False)
        rc = run_sequential_simulation(season_dir, OptimizerStrategy(1, decision_engine=eng_c), decision_engine=eng_c, start_gw=1, end_gw=1, use_chips=False)

        self.assertNotEqual(set(ra.history[0].starting_ids), set(rb.history[0].starting_ids))
        self.assertNotEqual(set(rb.history[0].starting_ids), set(rc.history[0].starting_ids))
        self.assertEqual(ra.history[0].gross_points, 83)
        self.assertEqual(rb.history[0].gross_points, 47)
        self.assertEqual(rc.history[0].gross_points, 52)

    def test_b6_vs_b7_chip_aware_weight_enforcement(self):
        """B6 clamps bench weight to static default, while B7 respects dynamic chip-aware weights."""
        from unittest.mock import MagicMock

        b6 = DecisionEngineAblation(ABLATION_VARIANTS["B6"])
        b7 = DecisionEngineAblation(ABLATION_VARIANTS["B7"])

        mock_snap = MagicMock()
        mock_snap.gameweek = 19
        mock_snap.fixtures = []
        mock_projs = []

        # Simulate caller passing dynamic bench weight 0.99 (Bench Boost)
        b6.bench_weight = 0.99
        b7.bench_weight = 0.99

        # When deciding transfers:
        # B6 has chip_aware=False -> clamps bench_weight back to 0.15
        # B7 has chip_aware=True -> retains dynamic bench_weight 0.99
        b6.decide_transfers("notransfer", [], {}, 0, 1, mock_snap, mock_projs)
        b7.decide_transfers("notransfer", [], {}, 0, 1, mock_snap, mock_projs)

        self.assertEqual(b6.bench_weight, 0.15)
        self.assertEqual(b7.bench_weight, 0.99)


if __name__ == "__main__":
    unittest.main()

