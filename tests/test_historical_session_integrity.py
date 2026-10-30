"""Focused, deterministic regressions for persisted historical session integrity."""

import copy
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pytest

from fpl_manager.historical.models import Position
from fpl_manager.simulation import HistoricalSimulationSession


class HistoricalSessionIntegrityTests(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def isolated_session_directory(self, tmp_path: Path) -> None:
        self.config_dir = tmp_path

    def setUp(self) -> None:
        squad = list(range(1, 16))
        positions = (
            [Position.GOALKEEPER] * 2
            + [Position.DEFENDER] * 5
            + [Position.MIDFIELDER] * 5
            + [Position.FORWARD] * 3
            + [Position.DEFENDER] * 3
        )
        players = tuple(
            SimpleNamespace(
                player_id=pid,
                position=position,
                team_id=pid,
                price_tenths=70 if pid == 3 else 50,
                web_name=f"Player {pid}",
            )
            for pid, position in enumerate(positions, 1)
        )
        self.snapshot = SimpleNamespace(players=players)
        self.sim = HistoricalSimulationSession(
            session_id="integrity",
            season="2023-24",
            current_gw=5,
            squad_ids=squad,
            purchase_prices_tenths={str(pid): 65 if pid == 3 else 50 for pid in squad},
            bank_tenths=100,
            starting_ids=[1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15],
            bench_ids=[2, 6, 7, 12],
            captain_id=13,
            vice_captain_id=14,
            initial_decision={"gameweek": 1, "squad_player_ids": squad},
            engine_baseline_purchase_prices={str(pid): 70 if pid == 3 else 50 for pid in squad},
            config_dir=self.config_dir,
        )
        patches = (
            patch.object(HistoricalSimulationSession, "get_current_snapshot", return_value=self.snapshot),
            patch.object(HistoricalSimulationSession, "get_recommendations", return_value={}),
            patch.object(HistoricalSimulationSession, "_step_baseline_engine", return_value=0),
            patch.object(HistoricalSimulationSession, "get_squad_player_details", return_value=[]),
            patch("fpl_manager.simulation.session.load_gameweek_outcomes", return_value={}),
            patch("fpl_manager.simulation.session.reconstruct_features_and_project", return_value=[]),
            patch(
                "fpl_manager.simulation.session.select_best_lineup",
                side_effect=lambda ids, projections: (list(ids[:11]), list(ids[11:]), ids[0], ids[1], 0),
            ),
            patch("fpl_manager.simulation.session.simulate_autosubs_and_score", return_value=(50, (), False)),
        )
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)

    def assert_rejected_atomically(self, action: Callable[[], object], message: str) -> None:
        path = self.sim.save()
        persisted = path.read_bytes()
        before = copy.deepcopy(self.sim.__dict__)
        with self.assertRaisesRegex(ValueError, message):
            action()
        self.assertEqual(self.sim.__dict__, before)
        self.assertEqual(path.read_bytes(), persisted)

    def roundtrip(self) -> None:
        self.sim.save()
        self.sim = HistoricalSimulationSession.load("integrity", config_dir=self.config_dir)

    def commit_legacy_transfer(self, *, known: bool = False) -> None:
        transfer = self.sim.stage_transfer(3, 16)
        self.sim.squad_ids[self.sim.squad_ids.index(3)] = 16
        self.sim.purchase_prices_tenths.pop("3")
        self.sim.purchase_prices_tenths["16"] = 50
        self.sim.bank_tenths -= transfer["cost_tenths"]
        transfer["already_applied"] = True
        if not known:
            transfer.pop("out_purchase_price_tenths")
            self.sim.gw_start_state = {}
        self.roundtrip()

    def test_batch_duplicate_incoming_is_rejected_after_normalization(self) -> None:
        self.assert_rejected_atomically(
            lambda: self.sim.stage_transfers_batch([{"out_id": 3, "in_id": 16}, {"out_id": 4, "in_id": 16}]),
            "more than once",
        )

    def test_batch_duplicate_outgoing_is_rejected_after_normalization(self) -> None:
        self.assert_rejected_atomically(
            lambda: self.sim.stage_transfers_batch([{"out_id": 3, "in_id": 16}, {"out_id": 3, "in_id": 17}]),
            "more than once",
        )

    def test_chains_do_not_hide_duplicate_normalized_endpoints(self) -> None:
        self.assert_rejected_atomically(
            lambda: self.sim.stage_transfers_batch([
                {"out_id": 3, "in_id": 16},
                {"out_id": 16, "in_id": 17},
                {"out_id": 4, "in_id": 17},
            ]),
            "more than once",
        )

    def test_identical_items_inside_one_batch_are_not_idempotent(self) -> None:
        transfer = self.sim.stage_transfer(3, 16)
        self.assert_rejected_atomically(
            lambda: self.sim.stage_transfers_batch([transfer, transfer]),
            "more than once",
        )

    def test_chain_normalization_preserves_valid_batch(self) -> None:
        moves = self.sim.stage_transfers_batch([{"out_id": 3, "in_id": 16}, {"out_id": 16, "in_id": 17}])
        self.assertEqual([(t["out_id"], t["in_id"]) for t in moves], [(3, 17)])
        self.assertEqual(moves[0]["out_selling_price_tenths"], 67)
        self.sim.run_gameweek()
        self.assertEqual(len(set(self.sim.squad_ids)), 15)

    def test_partial_repeat_of_committed_batch_remains_idempotent(self) -> None:
        self.commit_legacy_transfer(known=True)
        self.sim.stage_transfers_batch([{"out_id": 3, "in_id": 16}, {"out_id": 4, "in_id": 17}])
        self.sim.run_gameweek()
        self.assertEqual(self.sim.bank_tenths, 117)
        self.assertEqual(len(self.sim.transfers_staged), 0)
        self.assertEqual(set(self.sim.squad_ids), (set(range(1, 16)) - {3, 4}) | {16, 17})

    def test_committed_prefix_is_not_rebought_when_extending_chain(self) -> None:
        self.commit_legacy_transfer(known=True)
        request = [{"out_id": 3, "in_id": 16}, {"out_id": 16, "in_id": 17}]
        self.sim.stage_transfers_batch(request)
        self.sim.run_gameweek()
        self.assertEqual(self.sim.bank_tenths, 117)
        self.assertEqual(set(self.sim.squad_ids), (set(range(1, 16)) - {3}) | {17})

    def test_collision_with_existing_pending_move_is_atomic(self) -> None:
        self.sim.stage_transfer(3, 16)
        self.assert_rejected_atomically(lambda: self.sim.stage_transfer(4, 16), "15 unique")

    def test_invalid_persisted_batch_cannot_resolve(self) -> None:
        self.sim.transfers_staged = [{"out_id": 3, "in_id": 16}, {"out_id": 4, "in_id": 16}]
        self.assert_rejected_atomically(self.sim.run_gameweek, "more than once")
        self.assertEqual(len(self.sim.history), 0)

    def test_invalid_owned_squad_cannot_stage(self) -> None:
        self.sim.squad_ids[-1] = self.sim.squad_ids[-2]
        self.assert_rejected_atomically(lambda: self.sim.stage_transfer(3, 16), "15 unique")

    def test_legacy_recovery_never_uses_mutable_baseline_prices(self) -> None:
        self.commit_legacy_transfer()
        self.assertTrue(self.sim.gw_start_state["purchase_basis_unverified"])
        self.assertNotIn("3", self.sim.gw_start_state["purchase_prices_tenths"])
        self.sim.run_gameweek()
        self.roundtrip()
        self.assert_rejected_atomically(self.sim.undo_last_gameweek, "purchase")

    def test_unverified_undo_preserves_pending_history(self) -> None:
        self.commit_legacy_transfer()
        self.sim.run_gameweek()
        self.sim.history.append({"gameweek": 6, "type": "strategic_decision"})
        self.assert_rejected_atomically(self.sim.undo_last_gameweek, "purchase")

    def test_flagged_undo_snapshot_does_not_make_prices_authoritative(self) -> None:
        self.commit_legacy_transfer()
        self.sim.run_gameweek()
        self.sim.history[-1]["purchase_prices_before"] = {
            str(pid): 70 if pid == 3 else 50 for pid in range(1, 16)
        }
        self.sim.history[-1]["purchase_basis_unverified"] = True
        self.roundtrip()
        self.assert_rejected_atomically(self.sim.undo_last_gameweek, "purchase")

    def test_immutable_initial_basis_recovers_human_sale_not_baseline_sale(self) -> None:
        self.sim.initial_decision["purchase_prices_tenths"] = dict(self.sim.purchase_prices_tenths)
        self.commit_legacy_transfer()
        self.assertFalse(self.sim.gw_start_state["purchase_basis_unverified"])
        self.sim.run_gameweek()
        self.roundtrip()
        self.sim.undo_last_gameweek()
        self.assertEqual(self.sim.purchase_prices_tenths["3"], 65)
        self.assertEqual(self.sim.stage_transfer(3, 17)["out_selling_price_tenths"], 67)

    def test_latest_human_reacquisition_overrides_initial_cost(self) -> None:
        self.sim.initial_decision["purchase_prices_tenths"] = dict(self.sim.purchase_prices_tenths)
        self.sim.purchase_prices_tenths["3"] = 68
        self.sim.history = [
            {"gameweek": 2, "transfers_executed": [{"out_id": 3, "in_id": 17}]},
            {"gameweek": 4, "transfers_executed": [{"out_id": 17, "in_id": 3, "in_price_tenths": 68}]},
        ]
        self.sim._capture_gw_start_state()
        self.commit_legacy_transfer()
        self.assertEqual(self.sim.gw_start_state["purchase_prices_tenths"]["3"], 68)

    def test_unknown_human_reacquisition_does_not_reuse_initial_cost(self) -> None:
        self.sim.initial_decision["purchase_prices_tenths"] = dict(self.sim.purchase_prices_tenths)
        self.sim.history = [
            {"gameweek": 2, "transfers_executed": [{"out_id": 3, "in_id": 17}]},
            {"gameweek": 4, "transfers_executed": [{"out_id": 17, "in_id": 3}]},
        ]
        self.commit_legacy_transfer()
        self.assertTrue(self.sim.gw_start_state["purchase_basis_unverified"])

    def test_unknown_intermediate_cost_does_not_taint_verified_permanent_squad(self) -> None:
        self.sim.initial_decision["purchase_prices_tenths"] = dict(self.sim.purchase_prices_tenths)
        self.commit_legacy_transfer()
        transfer = self.sim.stage_transfer(16, 17)
        self.sim.squad_ids[self.sim.squad_ids.index(16)] = 17
        self.sim.purchase_prices_tenths.pop("16")
        self.sim.purchase_prices_tenths["17"] = 50
        transfer["already_applied"] = True
        transfer.pop("out_purchase_price_tenths")
        self.sim.gw_start_state = {}
        self.roundtrip()
        self.assertFalse(self.sim.gw_start_state["purchase_basis_unverified"])
        self.assertEqual(self.sim.gw_start_state["purchase_prices_tenths"]["3"], 65)
        self.sim.play_chip("free_hit")
        self.sim.run_gameweek()
        self.assertEqual(self.sim.purchase_prices_tenths["3"], 65)

    def test_undo_recovers_missing_snapshot_from_recorded_human_acquisition(self) -> None:
        self.commit_legacy_transfer(known=True)
        self.sim.run_gameweek()
        self.sim.history[-1]["purchase_prices_before"] = None
        self.sim.history[-1]["purchase_basis_unverified"] = True
        self.roundtrip()
        self.sim.undo_last_gameweek()
        self.assertEqual(self.sim.purchase_prices_tenths["3"], 65)
        self.assertEqual(self.sim.stage_transfer(3, 17)["out_selling_price_tenths"], 67)

    def test_unverified_permanent_basis_blocks_free_hit_activation(self) -> None:
        self.commit_legacy_transfer()
        self.assert_rejected_atomically(lambda: self.sim.play_chip("free_hit"), "purchase")
        self.roundtrip()
        self.sim.cancel_chip()
        self.assert_rejected_atomically(lambda: self.sim.play_chip("fh"), "purchase")

    def test_legacy_free_hit_snapshot_cannot_erase_missing_basis(self) -> None:
        self.commit_legacy_transfer()
        self.sim.active_chip = "free_hit"
        self.sim.pre_free_hit_state = {
            "gameweek": 5,
            "squad_ids": self.sim.gw_start_state["squad_ids"],
            "purchase_prices_tenths": self.sim.gw_start_state["purchase_prices_tenths"],
            "bank_tenths": 100,
        }
        self.sim.gw_start_state = {}
        self.roundtrip()
        self.assert_rejected_atomically(self.sim.run_gameweek, "purchase")

    def test_explicit_free_hit_uncertainty_survives_roundtrip(self) -> None:
        self.sim.active_chip = "free_hit"
        self.sim.pre_free_hit_state = {
            "gameweek": 5,
            "squad_ids": list(self.sim.squad_ids),
            "purchase_prices_tenths": dict(self.sim.purchase_prices_tenths),
            "bank_tenths": 100,
            "purchase_basis_unverified": True,
            "unverified_player_ids": [3],
        }
        self.sim.gw_start_state = {}
        self.roundtrip()
        self.assertTrue(self.sim.gw_start_state["purchase_basis_unverified"])
        self.assert_rejected_atomically(self.sim.run_gameweek, "purchase")

    def test_modern_free_hit_roundtrip_run_undo_cancel_preserves_original_basis(self) -> None:
        self.sim.stage_transfer(3, 16)
        self.sim.play_chip("free_hit")
        self.roundtrip()
        self.sim.run_gameweek()
        self.roundtrip()
        self.assertEqual(self.sim.purchase_prices_tenths["3"], 65)
        self.sim.undo_last_gameweek()
        self.assertEqual(self.sim.purchase_prices_tenths["3"], 65)
        self.sim.play_chip("free_hit")
        self.sim.cancel_chip()
        self.assertIsNone(self.sim.pre_free_hit_state)
        self.assertEqual(self.sim.stage_transfer(3, 17)["out_selling_price_tenths"], 67)

    def test_missing_owned_basis_never_falls_back_to_market_price(self) -> None:
        self.sim.purchase_prices_tenths.pop("3")
        self.sim.gw_start_state = {}
        self.roundtrip()
        self.assert_rejected_atomically(lambda: self.sim.stage_transfer(3, 16), "purchase")

    def test_resolution_never_values_missing_owned_basis_at_market_price(self) -> None:
        self.sim.purchase_prices_tenths.pop("3")
        self.sim.gw_start_state = {}
        self.roundtrip()
        self.assert_rejected_atomically(self.sim.run_gameweek, "purchase")

    def test_new_gameweek_capture_preserves_missing_owned_basis(self) -> None:
        self.sim.purchase_prices_tenths.pop("3")
        self.sim._capture_gw_start_state()
        self.roundtrip()
        self.assertTrue(self.sim.gw_start_state["purchase_basis_unverified"])
        self.assert_rejected_atomically(lambda: self.sim.play_chip("free_hit"), "purchase")
