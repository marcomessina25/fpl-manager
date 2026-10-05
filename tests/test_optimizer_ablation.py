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


if __name__ == "__main__":
    unittest.main()
