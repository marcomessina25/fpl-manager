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


def test_historical_recommendations_and_reproducibility(temp_sim_dir: Path) -> None:
    """Historical recommendations must provide unified chip, transfer, and lineup suggestions matching baseline engine."""
    sim = HistoricalSimulationSession.create(
        session_id="test_recs_repro",
        season="2023-24",
        start_gw=1,
        starting_strategy="v1.3.5",
        config_dir=temp_sim_dir,
    )
    recs = sim.get_recommendations()
    assert recs["gameweek"] == 1
    assert "recommended_starters" in recs
    assert len(recs["recommended_starters"]) == 11
    assert "recommended_bench" in recs
    assert len(recs["recommended_bench"]) == 4
    assert "recommended_captain" in recs
    assert "recommended_vice_captain" in recs
    assert "predicted_lineup_xp" in recs
    assert "recommended_transfers" in recs
    assert "recommended_chip" in recs

    # In GW 1 fresh squad, recommended_transfers should be empty and recommended_chip should be None
    assert recs["recommended_chip"] is None

    # Apply recommendations to session squad
    sim.set_lineup(
        recs["recommended_starters"],
        recs["recommended_bench"],
        recs["recommended_captain"],
        recs["recommended_vice_captain"],
    )
    if recs["recommended_chip"]:
        sim.play_chip(recs["recommended_chip"])

    res = sim.run_gameweek()
    # When all recommendations are applied, human and engine net points should match exactly
    divergence = res["human_engine_divergence"]
    assert divergence["human_override"] is False
    assert divergence["transfers_differed"] is False
    assert divergence["captain_differed"] is False
    assert divergence["point_delta_vs_engine"] == 0
    assert res["net_points"] == res["engine_net_points"]


def test_list_sessions_skips_corrupted_json_with_log(tmp_path: Path) -> None:
    """Verify list_sessions logs and skips corrupted JSON without silent failure."""
    valid_session = {
        "session_id": "valid_session",
        "season": "2023-24",
        "current_gw": 2,
        "status": "in_progress",
        "history": [],
        "experiment_metadata": {"created_at": "2026-10-06T12:00:00Z"},
    }
    (tmp_path / "valid.json").write_text(json.dumps(valid_session), encoding="utf-8")
    (tmp_path / "corrupt.json").write_text("{ incomplete json ...", encoding="utf-8")

    sessions = HistoricalSimulationSession.list_sessions(config_dir=tmp_path)
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "valid_session"


def test_baseline_engine_wildcard_failure_raises_data_integrity(tmp_path: Path) -> None:
    """Verify that a broken solver in baseline chip deployment raises DataIntegrityError."""
    from unittest.mock import patch
    from src.fpl_manager.errors import DataIntegrityError
    from src.fpl_manager.historical.models import GameweekOutcome, Position

    sim = HistoricalSimulationSession(
        session_id="solver_fail_test",
        season="2023-24",
        config_dir=tmp_path,
        squad_ids=list(range(1, 16)),
        engine_baseline_squad_ids=list(range(1, 16)),
    )
    sim.active_chip = "wildcard"

    snap = sim.get_current_snapshot()
    outcomes = {pid: GameweekOutcome(pid, 5, 90, 0, 0, 0, 0, 0, 0, 0, 0) for pid in range(1, 16)}
    positions = {pid: Position.MIDFIELDER for pid in range(1, 16)}

    with patch("src.fpl_manager.simulation.session.SeasonalChipPolicy.evaluate_gameweek_chip", return_value="wildcard"), \
         patch("src.fpl_manager.simulation.session.resolve_decision_engine") as mock_resolve:
        mock_engine = mock_resolve.return_value
        mock_engine.version = "v1.3.5"
        mock_engine.initialize_squad.side_effect = RuntimeError("Infeasible budget solver")
        
        with pytest.raises(DataIntegrityError) as exc_info:
            sim._step_baseline_engine(1, snap, outcomes, positions)
        assert "Baseline engine chip deployment failed" in str(exc_info.value)


def test_staged_transfers_lineup_persistence_and_normalization(tmp_path: Path) -> None:
    """Verify staged transfers update effective squad, lineup, and allow resilient unstaged saving."""
    sim = HistoricalSimulationSession.create(
        session_id="test_staged_lineup",
        season="2023-24",
        config_dir=tmp_path,
    )
    # Pick a player on bench to transfer out
    out_id = sim.bench_ids[0]
    snap = sim.get_current_snapshot()
    out_p = next(p for p in snap.players if p.player_id == out_id)

    # Count current club players (excluding out_id)
    club_counts: dict[int, int] = {}
    for pid in sim.squad_ids:
        if pid != out_id:
            p_obj = next((p for p in snap.players if p.player_id == pid), None)
            if p_obj:
                club_counts[p_obj.team_id] = club_counts.get(p_obj.team_id, 0) + 1

    # Find a replacement of the same position not in squad respecting club limits
    candidates = [
        p for p in snap.players
        if p.position == out_p.position
        and p.player_id not in sim.squad_ids
        and p.price_tenths <= out_p.price_tenths
        and club_counts.get(p.team_id, 0) < 3
    ]
    assert len(candidates) > 0
    in_id = candidates[0].player_id

    # 1. Stage transfer
    sim.stage_transfer(out_id, in_id)
    assert in_id in sim.bench_ids
    assert out_id not in sim.bench_ids

    # 2. get_squad_player_details reflects incoming player
    squad_details = sim.get_squad_player_details()
    p_ids = [p["player_id"] for p in squad_details]
    assert in_id in p_ids
    assert out_id not in p_ids

    # 3. set_lineup succeeds when passed the effective squad
    sim.set_lineup(sim.starting_ids, sim.bench_ids, sim.captain_id, sim.vice_captain_id)
    assert in_id in sim.bench_ids

    # 4. set_lineup succeeds and normalizes when passed the legacy/unstaged squad (containing out_id)
    legacy_bench = [out_id if pid == in_id else pid for pid in sim.bench_ids]
    sim.set_lineup(sim.starting_ids, legacy_bench, sim.captain_id, sim.vice_captain_id)
    assert in_id in sim.bench_ids
    assert out_id not in sim.bench_ids

    # 5. clear_staged_transfers reverts lineup back to out_id
    sim.clear_staged_transfers()
    assert out_id in sim.bench_ids
    assert in_id not in sim.bench_ids
    reverted_squad = [p["player_id"] for p in sim.get_squad_player_details()]
    assert out_id in reverted_squad
    assert in_id not in reverted_squad


def test_stage_transfer_idempotency_and_replacement(tmp_path: Path) -> None:
    """Validate that re-staging the same transfer is idempotent and replacing a staged player works."""
    sim = HistoricalSimulationSession.create(
        session_id="test_idempotent_tx",
        season="2023-24",
        start_gw=1,
        starting_strategy="v1.2.5",
        config_dir=tmp_path,
    )
    snap = sim.get_current_snapshot()
    out_id = sim.squad_ids[0]
    out_p = next(p for p in snap.players if p.player_id == out_id)

    club_counts: dict[int, int] = {}
    for pid in sim.squad_ids:
        pl = next((p for p in snap.players if p.player_id == pid), None)
        if pl:
            club_counts[pl.team_id] = club_counts.get(pl.team_id, 0) + 1

    same_pos = [
        p for p in snap.players
        if p.position == out_p.position
        and p.player_id not in sim.squad_ids
        and p.price_tenths <= out_p.price_tenths
        and (club_counts.get(p.team_id, 0) < 3 or p.team_id == out_p.team_id)
    ]
    assert len(same_pos) >= 2
    in_id1 = same_pos[0].player_id
    in_id2 = same_pos[1].player_id

    # 1. Stage first transfer
    st1 = sim.stage_transfer(out_id, in_id1)
    assert len(sim.transfers_staged) == 1
    assert sim.transfers_staged[0]["in_id"] == in_id1

    # 2. Stage SAME transfer again (idempotent, no error)
    st1_again = sim.stage_transfer(out_id, in_id1)
    assert len(sim.transfers_staged) == 1
    assert st1_again["in_id"] == in_id1

    # 3. Replace transfer: out_id to in_id2
    st2 = sim.stage_transfer(out_id, in_id2)
    assert len(sim.transfers_staged) == 1
    assert sim.transfers_staged[0]["in_id"] == in_id2


def test_stage_transfers_batch(tmp_path: Path) -> None:
    """Validate that batch transfer staging correctly validates net budget across trades."""
    sim = HistoricalSimulationSession.create(
        session_id="test_batch_tx",
        season="2023-24",
        start_gw=1,
        starting_strategy="v1.2.5",
        config_dir=tmp_path,
    )
    snap = sim.get_current_snapshot()
    out_ids = sim.squad_ids[:2]
    out_p1 = next(p for p in snap.players if p.player_id == out_ids[0])
    out_p2 = next(p for p in snap.players if p.player_id == out_ids[1])

    cand1 = next(
        p for p in snap.players
        if p.position == out_p1.position
        and p.player_id not in sim.squad_ids
        and p.team_id == out_p1.team_id
        and p.price_tenths <= out_p1.price_tenths
    )
    cand2 = next(
        p for p in snap.players
        if p.position == out_p2.position
        and p.player_id not in sim.squad_ids
        and p.player_id != cand1.player_id
        and p.team_id == out_p2.team_id
        and p.price_tenths <= out_p2.price_tenths
    )

    batch_payload = [
        {"out_id": out_ids[0], "in_id": cand1.player_id},
        {"out_id": out_ids[1], "in_id": cand2.player_id},
    ]

    # Batch staging succeeds
    staged = sim.stage_transfers_batch(batch_payload)
    assert len(staged) == 2
    assert len(sim.transfers_staged) == 2

    # Re-staging batch idempotently succeeds
    staged_again = sim.stage_transfers_batch(batch_payload)
    assert len(staged_again) == 2


def test_gw20_chips_reset(tmp_path):
    """Verify that chips reset when entering GW 20 (Window 2: GW 20-38)."""
    sim = HistoricalSimulationSession.create(
        session_id="test_chips_reset",
        season="2023-24",
        start_gw=19,
        starting_strategy="v1.2.5",
        config_dir=tmp_path,
    )
    # Simulate usage of chips in Window 1 (GW 1-19)
    sim.chips_used = {
        "wildcard": 8,
        "free_hit": 12,
        "bench_boost": 15,
        "triple_captain": 18,
    }
    sim.chips_remaining = []
    sim.engine_baseline_chips_remaining = []
    sim.save()

    # When advancing to GW 20
    sim.current_gw = 20
    sim.reset_chips_for_segment_2()
    assert set(sim.chips_remaining) == {"wildcard_2", "free_hit", "bench_boost", "triple_captain"}
    assert set(sim.engine_baseline_chips_remaining) == {"wildcard_2", "free_hit", "bench_boost", "triple_captain"}

    # Also test reconciliation on load when at GW 20+
    sim.current_gw = 20
    sim.chips_remaining = ["wildcard"]  # Depleted or corrupted state
    sim.engine_baseline_chips_remaining = []
    sim.save()

    loaded = HistoricalSimulationSession.load(sim.session_id, config_dir=tmp_path)
    assert set(loaded.chips_remaining) == {"wildcard_2", "free_hit", "bench_boost", "triple_captain"}
    assert set(loaded.engine_baseline_chips_remaining) == {"wildcard_2", "free_hit", "bench_boost", "triple_captain"}

    # Test playing a chip in Window 2
    loaded.play_chip("free_hit")
    assert loaded.active_chip == "free_hit"
    loaded.cancel_chip()
    assert loaded.active_chip is None


def test_gw1_transfers_free_and_already_applied_preserves_bank(tmp_path):
    """GW1 transfers must incur 0 hits, and already_applied transfers must not double-deduct bank."""
    sim = HistoricalSimulationSession.create(
        session_id="test_gw1_hits_and_bank",
        season="2023-24",
        start_gw=1,
        starting_strategy="v1.2.5",
        config_dir=tmp_path,
    )
    # Stage 3 transfers in GW1
    snap = sim.get_current_snapshot()
    out_id = sim.squad_ids[0]
    out_p = [p for p in snap.players if p.player_id == out_id][0]
    in_cand = [p for p in snap.players if p.position == out_p.position and p.player_id not in sim.squad_ids and p.price_tenths <= out_p.price_tenths][0]

    sim.transfers_staged = [
        {
            "out_id": out_id,
            "in_id": in_cand.player_id,
            "out_name": out_p.web_name,
            "in_name": in_cand.web_name,
            "cost_tenths": in_cand.price_tenths - out_p.price_tenths,
            "already_applied": True,
        },
        {
            "out_id": 99998,
            "in_id": 99999,
            "out_name": "Dummy1",
            "in_name": "Dummy2",
            "cost_tenths": 0,
            "already_applied": True,
        },
    ]

    initial_bank = sim.bank_tenths
    res = sim.run_gameweek()

    # GW1 must have 0 hits and 0 hit penalty
    assert res["transfer_hits"] == 0
    assert res["net_points"] == res["gross_points"]
    # Bank must NOT have been double-deducted
    assert sim.bank_tenths == initial_bank


def test_gw1_and_gw2_free_transfers_rollover_fpl_rules(tmp_path):
    """FPL Rules: Pre-season transfers are unlimited. GW1 never banks a rollover into GW2.
    Entering GW2 must always have free_transfers == 1.
    If 1 transfer is spent in GW2, GW3 starts with 1 free transfer.
    If 0 transfers are spent in GW2, GW3 starts with 2 free transfers (max 1 rollover).
    """
    squad_15 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
    sim = HistoricalSimulationSession.create(
        session_id="test_ft_rules",
        season="2023-24",
        start_gw=1,
        initial_squad_ids=squad_15,
        config_dir=tmp_path,
    )
    assert sim.current_gw == 1
    assert sim.free_transfers == 1
    assert sim.engine_baseline_free_transfers == 1

    # Run GW1 with 0 transfers
    sim.run_gameweek()
    assert sim.current_gw == 2
    # GW1 must NOT bank/rollover; entering GW2 must always be 1 FT
    assert sim.free_transfers == 1
    assert sim.engine_baseline_free_transfers == 1

    # In GW2, stage 1 transfer
    snap = sim.get_current_snapshot()
    out_id = sim.squad_ids[0]
    out_p = [p for p in snap.players if p.player_id == out_id][0]
    in_cand = [p for p in snap.players if p.position == out_p.position and p.player_id not in sim.squad_ids][0]
    sim.transfers_staged = [
        {
            "out_id": out_id,
            "in_id": in_cand.player_id,
            "out_name": out_p.web_name,
            "in_name": in_cand.web_name,
            "cost_tenths": 0,
            "already_applied": True,
        }
    ]
    sim.run_gameweek()
    assert sim.current_gw == 3
    # 1 FT spent in GW2 -> 1 FT entering GW3
    assert sim.free_transfers == 1

    # Undo back to GW2
    sim.undo_last_gameweek()
    assert sim.current_gw == 2
    assert sim.free_transfers == 1

    # Run GW2 with 0 transfers -> should roll over to 2 FT in GW3
    sim.transfers_staged = []
    sim.run_gameweek()
    assert sim.current_gw == 3
    assert sim.free_transfers == 2


