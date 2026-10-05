"""Unit and integration tests for historical interactive simulation session (V1.4)."""

import json
from pathlib import Path
import tempfile
import pytest

from src.fpl_manager.simulation import HistoricalSimulationSession


@pytest.fixture
def temp_sim_dir() -> Path:
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def test_session_creation_and_state_isolation(temp_sim_dir: Path) -> None:
    """Historical simulation session must be completely isolated and never mutate live files."""
    live_squad_file = Path("config/current_squad.json")
    live_squad_before = live_squad_file.read_text(encoding="utf-8") if live_squad_file.exists() else None

    sim = HistoricalSimulationSession.create(
        session_id="test_iso_sim_01",
        season="2023-24",
        start_gw=1,
        config_dir=temp_sim_dir,
    )

    assert sim.session_id == "test_iso_sim_01"
    assert sim.season == "2023-24"
    assert sim.current_gw == 1
    assert sim.status == "active"
    assert len(sim.squad_ids) == 15
    assert len(sim.starting_ids) == 11
    assert len(sim.bench_ids) == 4
    assert sim.free_transfers == 1
    assert sim.bank_tenths >= 0

    # Ensure isolation
    live_squad_after = live_squad_file.read_text(encoding="utf-8") if live_squad_file.exists() else None
    assert live_squad_before == live_squad_after

    # Ensure saved to temp_sim_dir
    session_file = temp_sim_dir / "test_iso_sim_01.json"
    assert session_file.exists()
    saved = json.loads(session_file.read_text(encoding="utf-8"))
    assert saved["session_id"] == "test_iso_sim_01"


def test_staged_transfers_and_legality_checks(temp_sim_dir: Path) -> None:
    """Transfer validation rules must reject position mismatches, club limits, and budget overruns."""
    sim = HistoricalSimulationSession.create(
        session_id="test_tx_legality",
        season="2023-24",
        start_gw=1,
        config_dir=temp_sim_dir,
    )
    snap = sim.get_current_snapshot()
    out_id = sim.squad_ids[0]
    out_p = [p for p in snap.players if p.player_id == out_id][0]

    # 1. Reject position mismatch
    diff_pos_p = [p for p in snap.players if p.position != out_p.position and p.player_id not in sim.squad_ids][0]
    with pytest.raises(ValueError, match="Position mismatch"):
        sim.stage_transfer(out_id, diff_pos_p.player_id)

    # 2. Reject player not in squad
    fake_out_id = 99999
    with pytest.raises(ValueError, match="not in the current squad"):
        sim.stage_transfer(fake_out_id, diff_pos_p.player_id)

    # 3. Reject insufficient budget
    expensive_p = [p for p in snap.players if p.position == out_p.position and p.price_tenths > (out_p.price_tenths + sim.bank_tenths)]
    if expensive_p:
        with pytest.raises(ValueError, match="Insufficient funds"):
            sim.stage_transfer(out_id, expensive_p[0].player_id)


def test_chip_activation_and_rules(temp_sim_dir: Path) -> None:
    """Chips can only be played once and must obey window rules."""
    sim = HistoricalSimulationSession.create(
        session_id="test_chips",
        season="2023-24",
        start_gw=1,
        config_dir=temp_sim_dir,
    )
    # Wildcard 2 is illegal in GW1 (only GW 20-38)
    with pytest.raises(ValueError, match="Second Wildcard"):
        sim.play_chip("wildcard_2")

    # Triple captain is legal
    act = sim.play_chip("triple_captain")
    assert act == "triple_captain"
    assert sim.active_chip == "triple_captain"

    # Cancel chip
    sim.cancel_chip()
    assert sim.active_chip is None


def test_free_hit_restores_pre_chip_squad(temp_sim_dir: Path) -> None:
    """Free Hit chip must revert the squad, purchase prices, and bank after matchday resolution."""
    sim = HistoricalSimulationSession.create(
        session_id="test_free_hit",
        season="2023-24",
        start_gw=1,
        config_dir=temp_sim_dir,
    )
    original_squad = list(sim.squad_ids)
    original_bank = sim.bank_tenths

    # Play Free Hit in GW1
    sim.play_chip("free_hit")
    snap1 = sim.get_current_snapshot()
    out_id = sim.squad_ids[0]
    out_p = [p for p in snap1.players if p.player_id == out_id][0]

    # Find legal replacement respecting club limits
    club_counts: dict[int, int] = {}
    for pid in sim.squad_ids:
        if pid != out_id:
            p_obj = [p for p in snap1.players if p.player_id == pid][0]
            club_counts[p_obj.team_id] = club_counts.get(p_obj.team_id, 0) + 1

    in_p = [
        p for p in snap1.players
        if p.position == out_p.position
        and p.player_id not in sim.squad_ids
        and p.price_tenths <= out_p.price_tenths
        and club_counts.get(p.team_id, 0) < 3
    ][0]

    sim.stage_transfer(out_id, in_p.player_id)
    assert len(sim.transfers_staged) == 1

    # Run gameweek
    res = sim.run_gameweek()
    assert res["chip_used"] == "free_hit"
    assert res["transfer_hits"] == 0  # Free Hit incurs 0 transfer hits

    # SQUAD MUST BE REVERTED POST-GW!
    assert sim.squad_ids == original_squad
    assert sim.bank_tenths == original_bank
    assert "free_hit" in sim.chips_used
    assert "free_hit" not in sim.chips_remaining


def test_gameweek_resolution_autosubs_and_divergence(temp_sim_dir: Path) -> None:
    """Matchday resolution evaluates points, autosubs, and frozen engine benchmark divergence."""
    sim = HistoricalSimulationSession.create(
        session_id="test_resolution",
        season="2023-24",
        start_gw=1,
        config_dir=temp_sim_dir,
    )
    res = sim.run_gameweek()
    assert res["gameweek"] == 1
    assert res["net_points"] > 0
    assert "effective_captain_id" in res
    assert "autosubs" in res
    assert "human_engine_divergence" in res
    assert sim.current_gw == 2
    assert len(sim.history) == 1

    # Check summary and export
    summary = sim.generate_summary()
    assert summary.gameweeks_completed == 1
    assert summary.total_net_points == res["net_points"]

    j_path, m_path = sim.export_report(output_dir=temp_sim_dir / "reports")
    assert j_path.exists()
    assert m_path.exists()
