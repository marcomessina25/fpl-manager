"""Execution identities and immutable legacy trial boundaries."""

import json
from types import SimpleNamespace

import pytest

from fpl_manager.execution import (
    ExecutionVersion,
    LegacyTrialReadOnlyError,
    execution_scope,
    resolve_execution_version,
)
from fpl_manager.application import StaleRevisionError
from fpl_manager.models import Position
from fpl_manager.simulation import HistoricalSimulationSession


@pytest.fixture
def trial(tmp_path, monkeypatch):
    positions = [Position.GOALKEEPER] * 2 + [Position.DEFENDER] * 5 + [
        Position.MIDFIELDER
    ] * 5 + [Position.FORWARD] * 3
    snapshot = SimpleNamespace(players=tuple(
        SimpleNamespace(
            player_id=pid, web_name=f"Player {pid}", position=position,
            team_id=pid, price_tenths=50,
        )
        for pid, position in enumerate(positions, 1)
    ))
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    bench = [2, 6, 7, 12]
    monkeypatch.setattr(HistoricalSimulationSession, "get_current_snapshot", lambda self: snapshot)
    monkeypatch.setattr("fpl_manager.simulation.session.reconstruct_features_and_project", lambda snap: [])
    monkeypatch.setattr(
        "fpl_manager.simulation.session.select_best_lineup",
        lambda ids, projections: (starters, bench, 13, 14, 0),
    )
    return HistoricalSimulationSession(
        "source", "2023-24", current_gw=5, squad_ids=list(range(1, 16)),
        purchase_prices_tenths={str(pid): 49 for pid in range(1, 16)},
        bank_tenths=17, free_transfers=2, starting_ids=starters, bench_ids=bench,
        captain_id=13, vice_captain_id=14, config_dir=tmp_path,
    )


def archive(trial):
    path = trial.save()
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("execution_version")
    path.write_text(json.dumps(data), encoding="utf-8")
    return HistoricalSimulationSession.load("source", config_dir=trial.config_dir), path


def test_execution_scope_restores_policy_after_failure():
    assert resolve_execution_version() is ExecutionVersion.CORRECTED_V147
    with pytest.raises(RuntimeError):
        with execution_scope("v146"):
            assert resolve_execution_version() is ExecutionVersion.LEGACY_V146
            raise RuntimeError("interrupted")
    assert resolve_execution_version() is ExecutionVersion.CORRECTED_V147


def test_corrected_session_persists_identity(trial):
    path = trial.save()
    assert json.loads(path.read_text(encoding="utf-8"))["execution_version"] == "v147"
    assert not HistoricalSimulationSession.load("source", config_dir=trial.config_dir).read_only


def test_direct_mutation_rejects_a_stale_loaded_session(trial):
    path = trial.save()
    stale = HistoricalSimulationSession.load("source", config_dir=trial.config_dir)
    trial.play_chip("triple_captain")
    before = path.read_bytes()
    with pytest.raises(StaleRevisionError):
        stale.cancel_chip()
    assert path.read_bytes() == before


@pytest.mark.parametrize("marker", [None, "", "future-version", 147, {"version": "v147"}])
def test_unverified_persisted_markers_remain_readable_archives(trial, marker):
    path = trial.save()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["execution_version"] = marker
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    loaded = HistoricalSimulationSession.load("source", config_dir=trial.config_dir)
    assert loaded.read_only
    with pytest.raises(LegacyTrialReadOnlyError):
        loaded.save()
    fork = loaded.fork_corrected("corrected")
    assert not fork.read_only
    assert fork.experiment_metadata["parent_recorded_execution_version"] == marker
    assert path.read_bytes() == before


@pytest.mark.parametrize("chip", [None, "wildcard"])
def test_comparison_settlement_uses_canonical_falling_prices(trial, monkeypatch, chip):
    snapshot = trial.get_current_snapshot()
    snapshot.players = (*snapshot.players, SimpleNamespace(
        player_id=16, web_name="Incoming", position=Position.FORWARD,
        team_id=16, price_tenths=60,
    ))
    trial.engine_baseline_bank_tenths = 10
    trial.engine_baseline_purchase_prices["15"] = 65
    selected = [16 if pid == 15 else pid for pid in trial.squad_ids]
    captured = []

    def initialize(*args, **kwargs):
        captured.append(kwargs["budget_tenths"])
        return selected, {}, 999

    engine = SimpleNamespace(
        version="v1.3.5", bench_weight=0.15,
        decide_transfers=lambda **kwargs: [(15, 16)],
        initialize_squad=initialize,
        select_lineup=lambda ids, projections: (
            [16 if pid == 15 else pid for pid in trial.starting_ids], trial.bench_ids, 13, 14, 0,
        ),
    )
    monkeypatch.setattr("fpl_manager.simulation.session.resolve_decision_engine", lambda version: engine)
    monkeypatch.setattr("fpl_manager.simulation.session.SeasonalChipPolicy.evaluate_gameweek_chip", lambda *args: chip)
    monkeypatch.setattr("fpl_manager.simulation.session.simulate_autosubs_and_score", lambda *args, **kwargs: (0, (), False))
    trial._step_baseline_engine(5, snapshot, {}, {p.player_id: p.position for p in snapshot.players})
    assert trial.engine_baseline_bank_tenths == 0
    assert trial.engine_baseline_purchase_prices["16"] == 60
    assert trial.engine_baseline_purchase_prices["1"] == 49
    assert 15 not in trial.engine_baseline_squad_ids
    if chip:
        assert captured == [746]


@pytest.mark.parametrize("operation", [
    lambda sim: sim.save(),
    lambda sim: sim.stage_transfer(3, 16),
    lambda sim: sim.stage_transfers_batch([]),
    lambda sim: sim.clear_staged_transfers(),
    lambda sim: sim.set_lineup([], [], 1, 2),
    lambda sim: sim.play_chip("wildcard"),
    lambda sim: sim.cancel_chip(),
    lambda sim: sim.reset_chips_for_segment_2(),
    lambda sim: sim.run_gameweek(),
    lambda sim: sim.undo_last_gameweek(),
])
def test_legacy_load_and_mutations_never_rewrite_archive(trial, operation):
    sim, path = archive(trial)
    before = path.read_bytes()
    assert sim.read_only
    with pytest.raises(LegacyTrialReadOnlyError):
        operation(sim)
    assert path.read_bytes() == before
    assert HistoricalSimulationSession.list_sessions(trial.config_dir)[0]["read_only"]


def test_explicit_fork_preserves_archive_and_financial_basis(trial):
    sim, path = archive(trial)
    before = path.read_bytes()
    fork = sim.fork_corrected("corrected")
    assert path.read_bytes() == before
    assert fork.session_id == "corrected"
    assert not fork.read_only
    assert fork.squad_ids == sim.gw_start_state["squad_ids"]
    assert fork.purchase_prices_tenths == sim.gw_start_state["purchase_prices_tenths"]
    assert fork.bank_tenths == 17
    assert fork.engine_baseline_bank_tenths == 17
    assert fork.engine_baseline_purchase_prices == fork.purchase_prices_tenths
    assert not fork.history and not fork.engine_baseline_history and not fork.transfers_staged
    assert fork.experiment_metadata["parent_execution_version"] == "v146"
    assert fork.experiment_metadata["parent_session_id"] == "source"
    assert HistoricalSimulationSession.load("corrected", config_dir=trial.config_dir).execution_version.value == "v147"


@pytest.mark.parametrize("invalid", ["unknown-prices", "completed", "exists", "invalid-squad"])
def test_fork_rejects_unsafe_boundary_without_creating_trial(trial, invalid):
    sim, path = archive(trial)
    before = path.read_bytes()
    if invalid == "unknown-prices":
        sim.gw_start_state["purchase_basis_unverified"] = True
    elif invalid == "completed":
        sim.status = "completed"
    elif invalid == "exists":
        (trial.config_dir / "corrected.json").write_text("reserved", encoding="utf-8")
    else:
        sim.gw_start_state["squad_ids"][-1] = 1
    with pytest.raises(ValueError):
        sim.fork_corrected("corrected")
    assert path.read_bytes() == before
    if invalid != "exists":
        assert not (trial.config_dir / "corrected.json").exists()
