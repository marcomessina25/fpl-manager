"""Tests for V1.4.6 Human Benchmark provenance export, verification, and corruption rejection."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.verify_v146_human_benchmark import (
    PROVENANCE_PATH,
    export_sanitized_provenance,
    format_chip_schedule_table,
    format_markdown_summary,
    format_provenance_audit_table,
    verify_provenance,
)


def test_verified_provenance_passes_full_suite() -> None:
    """The canonical committed provenance artifact passes all arithmetic and semantic verifications."""
    artifact = verify_provenance(PROVENANCE_PATH)
    assert artifact["schema_version"] == "1.4.6"
    assert artifact["study_id"] == "V146-HITL-BENCHMARK-5S"
    assert len(artifact["seasons"]) == 5
    assert artifact["aggregate_metrics"]["human_season_wins"] == 4
    assert artifact["aggregate_metrics"]["mean_decision_alpha_points"] == 63.6


def test_markdown_formatters_execute_without_error() -> None:
    """Markdown summary formatters produce well-formed markdown tables matching the artifact."""
    artifact = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    summary_md = format_markdown_summary(artifact)
    chip_md = format_chip_schedule_table(artifact)
    audit_md = format_provenance_audit_table(artifact)

    assert "exp_hm_01_2021_22" in summary_md
    assert "+63.6 pts" in summary_md
    assert "Track B (Human)" in chip_md
    assert "Track A (Engine)" in chip_md
    assert "Verified (bank=0, FT=1)" in audit_md


def test_corruption_rejects_arithmetic_mismatch(tmp_path: Path) -> None:
    """Verification must fail if gross points - hit points does not equal net points."""
    artifact = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    artifact["seasons"][0]["gameweeks"][0]["track_b_human_assisted"]["net_points"] += 10
    corrupt_path = tmp_path / "corrupt_arithmetic.json"
    corrupt_path.write_text(json.dumps(artifact), encoding="utf-8")

    with pytest.raises(AssertionError, match="gross .* - hit_pts .* != net"):
        verify_provenance(corrupt_path)


def test_corruption_rejects_cumulative_net_mismatch(tmp_path: Path) -> None:
    """Verification must fail if cumulative net points deviates from running sum."""
    artifact = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    artifact["seasons"][0]["gameweeks"][5]["track_b_human_assisted"]["cumulative_net_points"] = 9999
    corrupt_path = tmp_path / "corrupt_cumulative.json"
    corrupt_path.write_text(json.dumps(artifact), encoding="utf-8")

    with pytest.raises(AssertionError, match="cumulative_net_points"):
        verify_provenance(corrupt_path)


def test_corruption_rejects_chip_event_mismatch(tmp_path: Path) -> None:
    """Verification must fail if summary chips do not match canonical gameweek trace events."""
    artifact = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    # Fabricate an extra chip in summary not present in traces
    artifact["seasons"][0]["season_summary"]["track_b_chips_used"]["bench_boost_2"] = 38
    corrupt_path = tmp_path / "corrupt_chip.json"
    corrupt_path.write_text(json.dumps(artifact), encoding="utf-8")

    with pytest.raises(AssertionError, match="Track B summary chips .* do not match"):
        verify_provenance(corrupt_path)


def test_corruption_rejects_override_count_mismatch(tmp_path: Path) -> None:
    """Verification must fail if summary override count disagrees with per-gameweek trace classifications."""
    artifact = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    artifact["seasons"][1]["season_summary"]["override_count"] = 99
    corrupt_path = tmp_path / "corrupt_override.json"
    corrupt_path.write_text(json.dumps(artifact), encoding="utf-8")

    with pytest.raises(AssertionError, match="override_count 99 != trace override sum"):
        verify_provenance(corrupt_path)


def test_corruption_rejects_win_rate_mismatch(tmp_path: Path) -> None:
    """Verification must fail if aggregate win count or rate is fabricated."""
    artifact = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    artifact["aggregate_metrics"]["human_season_wins"] = 5
    corrupt_path = tmp_path / "corrupt_win_rate.json"
    corrupt_path.write_text(json.dumps(artifact), encoding="utf-8")

    with pytest.raises(AssertionError, match="Aggregate win count mismatch"):
        verify_provenance(corrupt_path)


def test_corruption_rejects_tampered_source_hash(tmp_path: Path) -> None:
    """Verification must fail if the declared raw source SHA-256 does not match the actual file."""
    artifact = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    artifact["seasons"][0]["source_trace_sha256"] = "deadbeef" * 8
    corrupt_path = tmp_path / "corrupt_hash.json"
    corrupt_path.write_text(json.dumps(artifact), encoding="utf-8")

    # Supply an isolated mock simulations directory containing the raw session trace file so the test
    # is deterministic and self-contained even in CI environments without uncommitted session traces.
    mock_sim_dir = tmp_path / "simulations"
    mock_sim_dir.mkdir(parents=True, exist_ok=True)
    mock_trace = mock_sim_dir / "sim_2021_22_4016_marco.json"
    mock_trace.write_bytes(b"mock session trace data")

    with pytest.raises(AssertionError, match="source SHA-256 mismatch"):
        verify_provenance(corrupt_path, simulations_dir=mock_sim_dir)


@pytest.mark.parametrize("field,value", [("bank_tenths", 9999), ("free_transfers", 5)])
def test_initial_state_verification_reads_actual_values(tmp_path: Path, field: str, value: int) -> None:
    artifact = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    artifact["seasons"][0]["initial_state_parity"]["track_a_initial_state"][field] = value
    corrupt_path = tmp_path / "initial_state.json"
    corrupt_path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(AssertionError, match="initial"):
        verify_provenance(corrupt_path, simulations_dir=tmp_path)


def test_initial_state_rejects_stale_comparison_flags(tmp_path: Path) -> None:
    artifact = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    artifact["seasons"][0]["initial_state_parity"]["comparison"]["squad_ids_identical"] = True
    corrupt_path = tmp_path / "comparison.json"
    corrupt_path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(AssertionError, match="comparison"):
        verify_provenance(corrupt_path, simulations_dir=tmp_path)


def test_initial_state_requires_distinct_players(tmp_path: Path) -> None:
    artifact = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    ids = artifact["seasons"][0]["initial_state_parity"]["track_a_initial_state"]["squad_ids"]
    ids[1] = ids[0]
    corrupt_path = tmp_path / "duplicate_initial.json"
    corrupt_path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(AssertionError, match="distinct"):
        verify_provenance(corrupt_path, simulations_dir=tmp_path)


def test_override_distribution_is_derived_from_outcomes(tmp_path: Path) -> None:
    artifact = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    summary = artifact["seasons"][0]["season_summary"]
    summary["override_positive_count"] -= 1
    summary["override_negative_count"] += 1
    corrupt_path = tmp_path / "distribution.json"
    corrupt_path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(AssertionError, match="override_positive_count"):
        verify_provenance(corrupt_path, simulations_dir=tmp_path)


def test_missing_raw_sources_are_explicitly_unverified(tmp_path: Path) -> None:
    artifact = verify_provenance(PROVENANCE_PATH, simulations_dir=tmp_path)
    status = artifact["verification_status"]
    assert status["arithmetic"] == "verified"
    assert status["semantic_consistency"] == "verified"
    assert status["initial_state_consistency"] == "verified"
    assert status["source_hashes"]["verified_seasons"] == []
    assert len(status["source_hashes"]["unavailable_seasons"]) == 5
    assert "Not checked" in format_provenance_audit_table(artifact)


def test_raw_source_status_reports_partial_verification(tmp_path: Path) -> None:
    artifact = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    raw_bytes = b"isolated test source"
    artifact["seasons"][0]["source_trace_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
    (tmp_path / "sim_2021_22_4016_marco.json").write_bytes(raw_bytes)
    provenance = tmp_path / "partial.json"
    provenance.write_text(json.dumps(artifact), encoding="utf-8")
    verified = verify_provenance(provenance, simulations_dir=tmp_path)
    status = verified["verification_status"]["source_hashes"]
    assert status["verified_seasons"] == ["2021-22"]
    assert len(status["unavailable_seasons"]) == 4
    table = format_provenance_audit_table(verified)
    assert table.count("Not checked") == 4
    assert "| Source Digest Check |" in table
