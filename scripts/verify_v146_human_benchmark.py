"""Reproducible provenance exporter and verifier for the V1.4.6 Human-in-the-Loop Benchmark.

Usage:
    # Verify committed sanitized traces and regenerate leaderboard tables:
    python scripts/verify_v146_human_benchmark.py

    # Export/refresh sanitized provenance JSON from local config/simulations/:
    python scripts/verify_v146_human_benchmark.py --export
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SIMULATIONS_DIR = REPO_ROOT / "config" / "simulations"
PROVENANCE_PATH = REPO_ROOT / "reports" / "v146" / "human_benchmark_provenance.json"

BENCHMARK_SESSIONS: list[tuple[str, str, str]] = [
    ("2021-22", "sim_2021_22_4016_marco", "exp_hm_01_2021_22"),
    ("2022-23", "sim_2022_23_1631_marco", "exp_hm_01_2022_23"),
    ("2023-24", "sim_2023_24_7254_marco", "exp_hm_01_2023_24"),
    ("2024-25", "sim_2024_25_0093_marco", "exp_hm_01_2024_25"),
    ("2025-26", "sim_2025_26_4700_marco", "exp_hm_01_2025_26"),
]


def _normalize_hits_count(raw_hits: Any, gross_pts: int, net_pts: int) -> int:
    val = int(raw_hits or 0)
    diff = int(gross_pts) - int(net_pts)
    if diff == 0:
        return 0
    if diff > 0 and diff % 4 == 0:
        expected_count = diff // 4
        if val == diff and val != expected_count:
            return expected_count
        if val == expected_count:
            return val
    return val


def _canonical_chip_name(chip: str | None, gw: int) -> str | None:
    if not chip:
        return None
    base = chip.replace("_1", "").replace("_2", "")
    if gw <= 19:
        return "wildcard_1" if base == "wildcard" else base
    else:
        return f"{base}_2"


def _extract_transfer_pair(t: Any) -> dict[str, int]:
    if isinstance(t, (list, tuple)) and len(t) >= 2:
        return {"out_id": int(t[0]), "in_id": int(t[1])}
    if isinstance(t, dict):
        out_val = t.get("out_id", t.get("out"))
        in_val = t.get("in_id", t.get("in"))
        return {"out_id": int(out_val), "in_id": int(in_val)}
    raise ValueError(f"Unrecognized transfer record: {t!r}")


def export_sanitized_provenance(
    simulations_dir: Path = SIMULATIONS_DIR,
    output_path: Path = PROVENANCE_PATH,
) -> dict[str, Any]:
    """Export sanitized, checksummed 5-season replay traces from local simulation sessions."""
    seasons_payload: list[dict[str, Any]] = []

    for season, raw_sid, anon_id in BENCHMARK_SESSIONS:
        src_file = simulations_dir / f"{raw_sid}.json"
        if not src_file.exists():
            raise FileNotFoundError(f"Benchmark session file not found: {src_file}")

        raw_bytes = src_file.read_bytes()
        raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        data = json.loads(raw_bytes.decode("utf-8"))

        history = [h for h in data.get("history", []) if "gross_points" in h]
        baseline_history = data.get("engine_baseline_history", [])
        if len(history) != 38 or len(baseline_history) != 38:
            raise ValueError(
                f"Season {season} must have 38 completed GWs in both tracks; "
                f"got {len(history)} and {len(baseline_history)}"
            )

        gw1_human = history[0]
        initial_squad_ids = list(gw1_human.get("squad_ids_before", []))
        initial_prices = {
            str(k): int(v) for k, v in (gw1_human.get("purchase_prices_before") or {}).items()
        }
        initial_bank_tenths = int(gw1_human.get("bank_tenths_before", 0))
        initial_ft = int(gw1_human.get("free_transfers_before", 1))
        initial_chips = list(
            gw1_human.get(
                "chips_remaining_before",
                ["wildcard_1", "free_hit", "bench_boost", "triple_captain"],
            )
        )

        max_ft_cap = 5 if int(season.split("-")[0]) >= 2024 else 2

        gw_traces: list[dict[str, Any]] = []
        override_count = 0
        override_pos = 0
        override_neg = 0
        override_neutral = 0
        captain_override_count = 0
        transfer_override_count = 0
        chip_override_count = 0

        for h_entry, b_entry in zip(history, baseline_history):
            gw = int(h_entry["gameweek"])
            if int(b_entry["gameweek"]) != gw:
                raise ValueError(f"GW mismatch in {season}: {gw} vs {b_entry['gameweek']}")

            h_gross = int(h_entry["gross_points"])
            h_net = int(h_entry["net_points"])
            h_hits = _normalize_hits_count(h_entry.get("transfer_hits", 0), h_gross, h_net)
            h_hit_pts = h_hits * 4

            b_gross = int(b_entry["gross_points"])
            b_net = int(b_entry["net_points"])
            b_hits = _normalize_hits_count(b_entry.get("transfer_hits", 0), b_gross, b_net)
            b_hit_pts = b_hits * 4

            rec = h_entry.get("engine_recommendation") or {}
            rec_transfers = [_extract_transfer_pair(t) for t in rec.get("recommended_transfers", [])]
            hum_transfers = [_extract_transfer_pair(t) for t in h_entry.get("transfers_executed", [])]
            base_transfers = [_extract_transfer_pair(t) for t in b_entry.get("transfers", [])]

            rec_cap = rec.get("recommended_captain", rec.get("recommended_captain_id"))
            hum_cap = h_entry.get("captain_id")
            rec_chip = rec.get("recommended_chip")
            hum_chip = h_entry.get("chip_used")
            base_chip = b_entry.get("chip_used")

            logged_div = h_entry.get("human_engine_divergence") or {}
            tx_diff = bool(
                logged_div.get(
                    "transfers_differed",
                    {(t["out_id"], t["in_id"]) for t in hum_transfers}
                    != {(t["out_id"], t["in_id"]) for t in rec_transfers},
                )
            )
            cap_diff = bool(
                logged_div.get(
                    "captain_differed",
                    rec_cap is not None and int(rec_cap) != int(hum_cap or 0),
                )
            )
            chip_diff = (hum_chip or None) != (rec_chip or None)
            is_override = bool(tx_diff or cap_diff or chip_diff)

            div = h_net - b_net
            if is_override:
                override_count += 1
                if tx_diff:
                    transfer_override_count += 1
                if cap_diff:
                    captain_override_count += 1
                if chip_diff:
                    chip_override_count += 1
                if div > 0:
                    override_pos += 1
                elif div < 0:
                    override_neg += 1
                else:
                    override_neutral += 1

            gw_traces.append(
                {
                    "gameweek": gw,
                    "track_b_human_assisted": {
                        "gross_points": h_gross,
                        "transfer_hits": h_hits,
                        "transfer_hit_points": h_hit_pts,
                        "net_points": h_net,
                        "cumulative_net_points": int(h_entry["cumulative_net_points"]),
                        "captain_id": int(hum_cap) if hum_cap is not None else None,
                        "effective_captain_id": int(h_entry["effective_captain_id"])
                        if h_entry.get("effective_captain_id") is not None
                        else None,
                        "captain_points": int(h_entry.get("captain_points", 0)),
                        "chip_used": hum_chip,
                        "transfers_executed": hum_transfers,
                        "autosubs_count": len(h_entry.get("autosubs", [])),
                        "bank_tenths_after": int(h_entry.get("bank_tenths_after", 0)),
                    },
                    "track_a_engine_baseline": {
                        "gross_points": b_gross,
                        "transfer_hits": b_hits,
                        "transfer_hit_points": b_hit_pts,
                        "net_points": b_net,
                        "chip_used": base_chip,
                        "transfers_executed": base_transfers,
                        "bank_tenths_after": int(b_entry.get("bank_tenths", 0)),
                    },
                    "point_in_time_advisory": {
                        "recommended_transfers": rec_transfers,
                        "recommended_captain_id": int(rec_cap) if rec_cap is not None else None,
                        "recommended_chip": rec_chip,
                        "predicted_lineup_xp": float(rec.get("predicted_lineup_xp", 0.0)),
                    },
                    "divergence": {
                        "net_points_delta": div,
                        "is_human_override": is_override,
                        "transfer_override": tx_diff,
                        "captain_override": cap_diff,
                        "chip_override": chip_diff,
                    },
                }
            )

        h_total_gross = sum(g["track_b_human_assisted"]["gross_points"] for g in gw_traces)
        h_total_hits = sum(g["track_b_human_assisted"]["transfer_hits"] for g in gw_traces)
        h_total_hit_pts = sum(g["track_b_human_assisted"]["transfer_hit_points"] for g in gw_traces)
        h_total_net = sum(g["track_b_human_assisted"]["net_points"] for g in gw_traces)

        b_total_gross = sum(g["track_a_engine_baseline"]["gross_points"] for g in gw_traces)
        b_total_hits = sum(g["track_a_engine_baseline"]["transfer_hits"] for g in gw_traces)
        b_total_hit_pts = sum(g["track_a_engine_baseline"]["transfer_hit_points"] for g in gw_traces)
        b_total_net = sum(g["track_a_engine_baseline"]["net_points"] for g in gw_traces)

        track_b_chips_used: dict[str, int] = {}
        track_a_chips_used: dict[str, int] = {}
        for g in gw_traces:
            b_chip = g["track_b_human_assisted"].get("chip_used")
            if b_chip:
                key = _canonical_chip_name(b_chip, g["gameweek"])
                if key:
                    track_b_chips_used[key] = g["gameweek"]
            a_chip = g["track_a_engine_baseline"].get("chip_used")
            if a_chip:
                key = _canonical_chip_name(a_chip, g["gameweek"])
                if key:
                    track_a_chips_used[key] = g["gameweek"]

        b0 = baseline_history[0]
        track_a_squad_ids = list(b0.get("squad_ids", []))
        track_a_bank = int(b0.get("bank_tenths", 0))
        track_a_ft = 1
        track_a_chips = ["wildcard_1", "free_hit", "bench_boost", "triple_captain"]

        squads_identical = sorted(initial_squad_ids) == sorted(track_a_squad_ids)
        overlap_count = len(set(initial_squad_ids).intersection(track_a_squad_ids))

        initial_state_record = {
            "shared_between_track_a_and_track_b": (
                squads_identical and initial_bank_tenths == track_a_bank and initial_ft == track_a_ft
            ),
            "shared_starting_bank_and_ft": (initial_bank_tenths == track_a_bank and initial_ft == track_a_ft),
            "shared_starting_squad": squads_identical,
            "squad_overlap_count": overlap_count,
            "track_b_initial_state": {
                "selection_method": "human_strategic_studio",
                "squad_ids": initial_squad_ids,
                "purchase_prices_tenths": initial_prices,
                "bank_tenths": initial_bank_tenths,
                "free_transfers": initial_ft,
                "chips_remaining": initial_chips,
            },
            "track_a_initial_state": {
                "selection_method": "autonomous_engine_maximum_ev",
                "squad_ids": track_a_squad_ids,
                "bank_tenths": track_a_bank,
                "free_transfers": track_a_ft,
                "chips_remaining": track_a_chips,
            },
            "comparison": {
                "bank_tenths_identical": (initial_bank_tenths == track_a_bank),
                "free_transfers_identical": (initial_ft == track_a_ft),
                "chips_remaining_identical": (sorted(initial_chips) == sorted(track_a_chips)),
                "squad_ids_identical": squads_identical,
                "squad_ids_overlap": f"{overlap_count}/15",
            },
            "persisted_configuration": data.get("experiment_metadata") or {
                "frozen_engine_version": data.get("engine_baseline_version", "v1.3.5"),
                "starting_policy": data.get("starting_policy", "engine_baseline"),
            },
        }

        seasons_payload.append(
            {
                "season": season,
                "experiment_session_id": anon_id,
                "participant_id": "EXP-HM-01",
                "source_trace_sha256": raw_sha256,
                "ruleset": {
                    "data_source": f"data/historical/{season}",
                    "information_boundary": "strict_point_in_time_pre_deadline",
                    "gw1_to_gw2_ft_rollover": 1,
                    "max_free_transfers_cap": max_ft_cap,
                    "chip_windows": {
                        "segment_1": {
                            "gameweeks": [1, 19],
                            "chips": ["wildcard_1", "free_hit", "bench_boost", "triple_captain"],
                        },
                        "segment_2": {
                            "gameweeks": [20, 38],
                            "chips": ["wildcard_2", "free_hit_2", "bench_boost_2", "triple_captain_2"],
                        },
                    },
                },
                "initial_state_parity": initial_state_record,
                "season_summary": {
                    "gameweeks_completed": 38,
                    "track_b_gross_points": h_total_gross,
                    "track_b_transfer_hits": h_total_hits,
                    "track_b_transfer_hit_points": h_total_hit_pts,
                    "track_b_net_points": h_total_net,
                    "track_b_chips_used": track_b_chips_used,
                    "track_a_gross_points": b_total_gross,
                    "track_a_transfer_hits": b_total_hits,
                    "track_a_transfer_hit_points": b_total_hit_pts,
                    "track_a_net_points": b_total_net,
                    "track_a_chips_used": track_a_chips_used,
                    "decision_alpha_net_points": h_total_net - b_total_net,
                    "override_count": override_count,
                    "override_positive_count": override_pos,
                    "override_negative_count": override_neg,
                    "override_neutral_count": override_neutral,
                    "transfer_override_count": transfer_override_count,
                    "captain_override_count": captain_override_count,
                    "chip_override_count": chip_override_count,
                },
                "gameweeks": gw_traces,
            }
        )

    track_b_means = sum(s["season_summary"]["track_b_net_points"] for s in seasons_payload) / len(seasons_payload)
    track_a_means = sum(s["season_summary"]["track_a_net_points"] for s in seasons_payload) / len(seasons_payload)
    alpha_mean = round(track_b_means - track_a_means, 2)
    wins = sum(
        1
        for s in seasons_payload
        if s["season_summary"]["track_b_net_points"] > s["season_summary"]["track_a_net_points"]
    )

    artifact = {
        "schema_version": "1.4.6",
        "study_id": "V146-HITL-BENCHMARK-5S",
        "study_status": "completed_end_to_end_two_track_comparison",
        "study_design": "end_to_end_strategy_comparison",
        "tracks_evaluated": [
            "Track A: Autonomous Frozen Reference Baseline (DecisionEngineV135 + ChipOpportunityOptimizer C1)",
            "Track B: Human-Assisted Replay (Operator EXP-HM-01 + Point-in-Time Engine Advisory)",
        ],
        "tracks_excluded": [
            "Track C: Human Blind Control (deferred; not executed in v1.4.6 single-operator study)"
        ],
        "engine_configuration": {
            "decision_engine": "v1.3.5",
            "quantitative_predictor": "v0.9.1-frozen",
            "chip_policy": "ChipOpportunityOptimizer (c1_linear_decay)",
            "initial_squad_strategy": "maximum_ev",
            "horizon_gws": 3,
            "horizon_decay_gamma": 0.75,
            "bench_weight": 0.15,
            "gk_transfer_hurdle": 3.0,
        },
        "statistical_scope_and_limitations": {
            "seasons_count": 5,
            "total_gameweeks": 190,
            "human_operators_count": 1,
            "participant_id": "EXP-HM-01",
            "note": (
                "Five-season (190-GW), single-operator end-to-end strategy comparison. "
                "Different initial squads mean the observed net surplus includes initial "
                "selection and later decisions, not an isolated identical-start treatment effect. "
                "Five seasons with one operator do not establish population-wide significance."
            ),
        },
        "aggregate_metrics": {
            "seasons_evaluated": 5,
            "gameweeks_evaluated": 190,
            "track_b_mean_net_points": round(track_b_means, 2),
            "track_a_mean_net_points": round(track_a_means, 2),
            "mean_decision_alpha_points": alpha_mean,
            "human_season_wins": wins,
            "engine_season_wins": len(seasons_payload) - wins,
            "human_season_win_rate": round(wins / len(seasons_payload), 4),
        },
        "seasons": seasons_payload,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    return artifact


def verify_provenance(
    provenance_path: Path = PROVENANCE_PATH,
    simulations_dir: Path | None = None,
) -> dict[str, Any]:
    """Verify recorded consistency and report which raw-source digests were checked."""
    if not provenance_path.exists():
        raise FileNotFoundError(f"Provenance file missing: {provenance_path}")

    artifact = json.loads(provenance_path.read_text(encoding="utf-8"))
    seasons = artifact.get("seasons", [])
    if len(seasons) != 5:
        raise AssertionError(f"Expected 5 seasons, got {len(seasons)}")

    total_b_net_all = 0
    total_a_net_all = 0
    human_wins = 0
    verified_source_seasons: list[str] = []
    unavailable_source_seasons: list[str] = []
    source_sessions = {season: (sid, anon_id) for season, sid, anon_id in BENCHMARK_SESSIONS}
    if {s["season"] for s in seasons} != set(source_sessions):
        raise AssertionError("Expected five distinct benchmark seasons")

    for s in seasons:
        season_name = s["season"]
        gws = s["gameweeks"]
        if len(gws) != 38:
            raise AssertionError(f"Season {season_name}: expected 38 GWs, got {len(gws)}")

        init = s["initial_state_parity"]
        comp = init.get("comparison", {})
        track_b_initial = init.get("track_b_initial_state", {})
        track_a_initial = init.get("track_a_initial_state", {})
        for label, state in (("Track B", track_b_initial), ("Track A", track_a_initial)):
            ids = state.get("squad_ids", [])
            if len(ids) != 15 or len(set(ids)) != 15:
                raise AssertionError(f"Season {season_name}: {label} initial squad must have 15 distinct players")
            for field in ("bank_tenths", "free_transfers"):
                if type(state.get(field)) is not int:
                    raise AssertionError(f"Season {season_name}: {label} initial {field} must be an integer")
        same_bank = track_b_initial["bank_tenths"] == track_a_initial["bank_tenths"]
        same_ft = track_b_initial["free_transfers"] == track_a_initial["free_transfers"]
        if not same_bank:
            raise AssertionError(f"Season {season_name}: initial bank tenths not identical between tracks")
        if not same_ft:
            raise AssertionError(f"Season {season_name}: initial FT not identical between tracks")
        b_ids = set(track_b_initial["squad_ids"])
        a_ids = set(track_a_initial["squad_ids"])
        overlap = len(b_ids & a_ids)
        expected_comparison = {
            "bank_tenths_identical": same_bank,
            "free_transfers_identical": same_ft,
            "chips_remaining_identical": (
                sorted(track_b_initial["chips_remaining"]) == sorted(track_a_initial["chips_remaining"])
            ),
            "squad_ids_identical": b_ids == a_ids,
            "squad_ids_overlap": f"{overlap}/15",
        }
        for field, expected in expected_comparison.items():
            if comp.get(field) != expected:
                raise AssertionError(f"Season {season_name}: initial comparison {field} disagrees with recorded states")
        expected_flags = {
            "shared_between_track_a_and_track_b": same_bank and same_ft and b_ids == a_ids,
            "shared_starting_bank_and_ft": same_bank and same_ft,
            "shared_starting_squad": b_ids == a_ids,
            "squad_overlap_count": overlap,
        }
        for field, expected in expected_flags.items():
            if init.get(field) != expected:
                raise AssertionError(f"Season {season_name}: initial comparison {field} is inconsistent")

        raw_sid, anon_id = source_sessions[season_name]
        if s.get("experiment_session_id") != anon_id:
            raise AssertionError(f"Season {season_name}: unexpected experiment session identifier")
        declared_sha = s.get("source_trace_sha256")
        if (
            not isinstance(declared_sha, str)
            or len(declared_sha) != 64
            or any(c not in "0123456789abcdef" for c in declared_sha)
        ):
            raise AssertionError(f"Season {season_name}: invalid source SHA-256 digest")
        sim_dir = simulations_dir if simulations_dir is not None else SIMULATIONS_DIR
        src_file = sim_dir / f"{raw_sid}.json"
        if src_file.exists():
            computed_sha = hashlib.sha256(src_file.read_bytes()).hexdigest()
            if declared_sha != computed_sha:
                raise AssertionError(
                    f"Season {season_name}: source SHA-256 mismatch "
                    f"(artifact={declared_sha}, file={computed_sha})"
                )
            verified_source_seasons.append(season_name)
        else:
            unavailable_source_seasons.append(season_name)

        running_b_net = 0
        running_b_gross = 0
        running_b_hits = 0
        running_a_net = 0
        running_a_gross = 0
        running_a_hits = 0

        for idx, gw_rec in enumerate(gws, start=1):
            if gw_rec["gameweek"] != idx:
                raise AssertionError(f"Season {season_name}: expected GW {idx}, got {gw_rec['gameweek']}")

            tb = gw_rec["track_b_human_assisted"]
            ta = gw_rec["track_a_engine_baseline"]
            div = gw_rec["divergence"]

            if tb["transfer_hit_points"] != tb["transfer_hits"] * 4:
                raise AssertionError(f"Season {season_name} GW{idx}: Track B hit points mismatch")
            if tb["gross_points"] - tb["transfer_hit_points"] != tb["net_points"]:
                raise AssertionError(
                    f"Season {season_name} GW{idx}: Track B gross ({tb['gross_points']}) - "
                    f"hit_pts ({tb['transfer_hit_points']}) != net ({tb['net_points']})"
                )

            if ta["transfer_hit_points"] != ta["transfer_hits"] * 4:
                raise AssertionError(f"Season {season_name} GW{idx}: Track A hit points mismatch")
            if ta["gross_points"] - ta["transfer_hit_points"] != ta["net_points"]:
                raise AssertionError(
                    f"Season {season_name} GW{idx}: Track A gross ({ta['gross_points']}) - "
                    f"hit_pts ({ta['transfer_hit_points']}) != net ({ta['net_points']})"
                )

            running_b_net += tb["net_points"]
            running_b_gross += tb["gross_points"]
            running_b_hits += tb["transfer_hits"]

            running_a_net += ta["net_points"]
            running_a_gross += ta["gross_points"]
            running_a_hits += ta["transfer_hits"]

            if tb["cumulative_net_points"] != running_b_net:
                raise AssertionError(
                    f"Season {season_name} GW{idx}: cumulative_net_points "
                    f"{tb['cumulative_net_points']} != running sum {running_b_net}"
                )
            if div["net_points_delta"] != tb["net_points"] - ta["net_points"]:
                raise AssertionError(f"Season {season_name} GW{idx}: divergence delta mismatch")

        summary = s["season_summary"]
        if summary["track_b_net_points"] != running_b_net:
            raise AssertionError(f"Season {season_name}: Track B net total mismatch")
        if summary["track_b_gross_points"] != running_b_gross:
            raise AssertionError(f"Season {season_name}: Track B gross total mismatch")
        if summary["track_b_transfer_hits"] != running_b_hits:
            raise AssertionError(f"Season {season_name}: Track B hits total mismatch")
        if summary["track_a_net_points"] != running_a_net:
            raise AssertionError(f"Season {season_name}: Track A net total mismatch")
        if summary["track_a_gross_points"] != running_a_gross:
            raise AssertionError(f"Season {season_name}: Track A gross total mismatch")
        if summary["track_a_transfer_hits"] != running_a_hits:
            raise AssertionError(f"Season {season_name}: Track A hits total mismatch")
        if summary["decision_alpha_net_points"] != running_b_net - running_a_net:
            raise AssertionError(f"Season {season_name}: decision alpha mismatch")

        # Semantic verification: validate summary chip deployments against GW traces
        derived_b_chips: dict[str, int] = {}
        derived_a_chips: dict[str, int] = {}
        for gw_rec in gws:
            b_chip = gw_rec["track_b_human_assisted"].get("chip_used")
            if b_chip:
                key = _canonical_chip_name(b_chip, gw_rec["gameweek"])
                if key:
                    derived_b_chips[key] = gw_rec["gameweek"]
            a_chip = gw_rec["track_a_engine_baseline"].get("chip_used")
            if a_chip:
                key = _canonical_chip_name(a_chip, gw_rec["gameweek"])
                if key:
                    derived_a_chips[key] = gw_rec["gameweek"]

        if summary.get("track_b_chips_used") != derived_b_chips:
            raise AssertionError(
                f"Season {season_name}: Track B summary chips {summary.get('track_b_chips_used')} "
                f"do not match canonical events in GW traces {derived_b_chips}"
            )
        if summary.get("track_a_chips_used") != derived_a_chips:
            raise AssertionError(
                f"Season {season_name}: Track A summary chips {summary.get('track_a_chips_used')} "
                f"do not match canonical events in GW traces {derived_a_chips}"
            )

        # Semantic verification: override classifications and counts
        actual_overrides = sum(1 for g in gws if g["divergence"]["is_human_override"])
        if summary["override_count"] != actual_overrides:
            raise AssertionError(
                f"Season {season_name}: override_count {summary['override_count']} "
                f"!= trace override sum {actual_overrides}"
            )
        categorized_overrides = (
            summary["override_positive_count"]
            + summary["override_negative_count"]
            + summary["override_neutral_count"]
        )
        if summary["override_count"] != categorized_overrides:
            raise AssertionError(
                f"Season {season_name}: override_count {summary['override_count']} "
                f"!= positive+negative+neutral sum {categorized_overrides}"
            )
        for field, sign in (
            ("override_positive_count", 1),
            ("override_negative_count", -1),
            ("override_neutral_count", 0),
        ):
            expected_count = sum(
                1 for g in gws
                if g["divergence"]["is_human_override"]
                and (
                    (g["divergence"]["net_points_delta"] > 0) - (g["divergence"]["net_points_delta"] < 0)
                ) == sign
            )
            if summary[field] != expected_count:
                raise AssertionError(f"Season {season_name}: {field} disagrees with trace outcomes")
        actual_tx_overrides = sum(1 for g in gws if g["divergence"]["transfer_override"])
        if summary["transfer_override_count"] != actual_tx_overrides:
            raise AssertionError(
                f"Season {season_name}: transfer_override_count {summary['transfer_override_count']} "
                f"!= trace count {actual_tx_overrides}"
            )
        actual_cap_overrides = sum(1 for g in gws if g["divergence"]["captain_override"])
        if summary["captain_override_count"] != actual_cap_overrides:
            raise AssertionError(
                f"Season {season_name}: captain_override_count {summary['captain_override_count']} "
                f"!= trace count {actual_cap_overrides}"
            )
        actual_chip_overrides = sum(1 for g in gws if g["divergence"]["chip_override"])
        if summary["chip_override_count"] != actual_chip_overrides:
            raise AssertionError(
                f"Season {season_name}: chip_override_count {summary['chip_override_count']} "
                f"!= trace count {actual_chip_overrides}"
            )

        total_b_net_all += running_b_net
        total_a_net_all += running_a_net
        if running_b_net > running_a_net:
            human_wins += 1

    agg = artifact["aggregate_metrics"]
    if round(total_b_net_all / 5, 2) != agg["track_b_mean_net_points"]:
        raise AssertionError("Aggregate Track B mean mismatch")
    if round(total_a_net_all / 5, 2) != agg["track_a_mean_net_points"]:
        raise AssertionError("Aggregate Track A mean mismatch")
    if round((total_b_net_all - total_a_net_all) / 5, 2) != agg["mean_decision_alpha_points"]:
        raise AssertionError("Aggregate decision alpha mean mismatch")
    if human_wins != agg["human_season_wins"]:
        raise AssertionError(f"Aggregate win count mismatch: {human_wins} vs {agg['human_season_wins']}")
    if len(seasons) - human_wins != agg["engine_season_wins"]:
        raise AssertionError("Aggregate engine win count mismatch")
    if round(human_wins / len(seasons), 4) != agg["human_season_win_rate"]:
        raise AssertionError("Aggregate human season win rate mismatch")

    artifact["verification_status"] = {
        "arithmetic": "verified",
        "semantic_consistency": "verified",
        "initial_state_consistency": "verified",
        "source_hashes": {
            "verified_seasons": verified_source_seasons,
            "unavailable_seasons": unavailable_source_seasons,
        },
    }
    return artifact


def format_markdown_summary(artifact: dict[str, Any]) -> str:
    """Format the verified leaderboard and override analysis table from trace data."""
    lines = [
        "| Season | Session ID | Track B Gross | Track B Hits (Pts) | Track B Net | Track A Gross | Track A Hits (Pts) | Track A Net | Observed Net Surplus (B - A) | Overrides (+ / - / 0) |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for s in artifact["seasons"]:
        sm = s["season_summary"]
        alpha = sm["decision_alpha_net_points"]
        alpha_str = f"+{alpha} pts" if alpha > 0 else f"{alpha} pts"
        ov_str = (
            f"{sm['override_count']} "
            f"({sm['override_positive_count']}+ / {sm['override_negative_count']}- / {sm['override_neutral_count']}=)"
        )
        lines.append(
            f"| **{s['season']}** | `{s['experiment_session_id']}` | "
            f"{sm['track_b_gross_points']:,} | {sm['track_b_transfer_hits']} (-{sm['track_b_transfer_hit_points']}) | "
            f"**{sm['track_b_net_points']:,} pts** | "
            f"{sm['track_a_gross_points']:,} | {sm['track_a_transfer_hits']} (-{sm['track_a_transfer_hit_points']}) | "
            f"{sm['track_a_net_points']:,} pts | **{alpha_str}** | {ov_str} |"
        )
    agg = artifact["aggregate_metrics"]
    lines.append(
        f"| **5-Season Mean** | - | - | - | **{agg['track_b_mean_net_points']:,.1f} pts** | "
        f"- | - | {agg['track_a_mean_net_points']:,.1f} pts | "
        f"**+{agg['mean_decision_alpha_points']:.1f} pts** | "
        f"**{agg['human_season_wins']} / {agg['seasons_evaluated']} Seasons ({agg['human_season_win_rate']*100:.1f}%)** |"
    )
    return "\n".join(lines)


def format_chip_schedule_table(artifact: dict[str, Any]) -> str:
    """Format the verified chip deployment schedule table from trace data."""
    lines = [
        "| Season | Track | Segment 1 (`GW1–19`) Chips (`WC1`, `FH1`, `BB1`, `TC1`) | Segment 2 (`GW20–38`) Chips (`WC2`, `FH2`, `BB2`, `TC2`) |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for s in artifact["seasons"]:
        season = s["season"]
        sm = s["season_summary"]
        for track_label, track_chips in [
            ("Track B (Human)", sm["track_b_chips_used"]),
            ("Track A (Engine)", sm["track_a_chips_used"]),
        ]:
            seg1_items: list[tuple[int, str]] = []
            seg2_items: list[tuple[int, str]] = []
            for chip_base, abbr in [
                ("wildcard", "WC"),
                ("free_hit", "FH"),
                ("bench_boost", "BB"),
                ("triple_captain", "TC"),
            ]:
                c1_key = f"{chip_base}_1" if chip_base == "wildcard" else chip_base
                if c1_key in track_chips:
                    seg1_items.append((track_chips[c1_key], f"`{abbr}1`: GW{track_chips[c1_key]}"))
                c2_key = f"{chip_base}_2"
                if c2_key in track_chips:
                    seg2_items.append((track_chips[c2_key], f"`{abbr}2`: GW{track_chips[c2_key]}"))
            seg1_items.sort(key=lambda x: x[0])
            seg2_items.sort(key=lambda x: x[0])
            seg1_str = ", ".join(x[1] for x in seg1_items) if seg1_items else "*(None deployed)*"
            seg2_str = ", ".join(x[1] for x in seg2_items) if seg2_items else "*(None deployed)*"
            lines.append(f"| **{season}** | {track_label} | {seg1_str} | {seg2_str} |")
    return "\n".join(lines)


def format_provenance_audit_table(artifact: dict[str, Any]) -> str:
    """Distinguish metadata consistency from optional raw-source verification."""
    lines = [
        "| Season | Anonymized Session ID | Raw Session Trace SHA-256 Digest | Bank / FT Consistency | Squad Overlap | Source Digest Check |",
        "| :--- | :--- | :--- | :--- | :---: | :--- |",
    ]
    checked_sources = artifact.get("verification_status", {}).get("source_hashes", {}).get("verified_seasons", [])
    for s in artifact["seasons"]:
        init = s["initial_state_parity"]
        b_state = init["track_b_initial_state"]
        a_state = init["track_a_initial_state"]
        parity_str = (
            f"Verified (bank={b_state['bank_tenths']}, FT={b_state['free_transfers']})"
            if b_state["bank_tenths"] == a_state["bank_tenths"]
            and b_state["free_transfers"] == a_state["free_transfers"]
            else "Discrepancy"
        )
        overlap_str = f"{len(set(b_state['squad_ids']) & set(a_state['squad_ids']))}/15"
        source_status = "Verified" if s["season"] in checked_sources else "Not checked (raw source unavailable or not supplied)"
        lines.append(
            f"| **{s['season']}** | `{s['experiment_session_id']}` | "
            f"`{s['source_trace_sha256']}` | {parity_str} | {overlap_str} | {source_status} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify or export V1.4.6 Human Benchmark provenance.")
    parser.add_argument(
        "--export",
        action="store_true",
        help="Export sanitized provenance JSON from local config/simulations/ before verifying.",
    )
    parser.add_argument(
        "--simulations-dir",
        type=Path,
        default=None,
        help="Custom path to raw simulation JSON files for hash checking.",
    )
    args = parser.parse_args()

    if args.export:
        export_sanitized_provenance()
        print(f"Exported sanitized provenance to {PROVENANCE_PATH}")

    artifact = verify_provenance(simulations_dir=args.simulations_dir)
    print("V1.4.6 Benchmark Consistency Verification: PASSED (5 seasons, 190 gameweeks reconciled)")
    hashes = artifact["verification_status"]["source_hashes"]
    print(f"Raw source digests checked: {len(hashes['verified_seasons'])}/5.")
    if hashes["unavailable_seasons"]:
        print("Raw source verification NOT PERFORMED for: " + ", ".join(hashes["unavailable_seasons"]))
    print("Different initial squads: results compare end-to-end strategies, not an identical-start experiment.")
    print()
    print("### Primary Leaderboard & Override Analysis")
    print(format_markdown_summary(artifact))
    print()
    print("### Chip Deployment Schedule (Track B vs. Track A)")
    print(format_chip_schedule_table(artifact))
    print()
    print("### Provenance & Initial State Audit")
    print(format_provenance_audit_table(artifact))


if __name__ == "__main__":
    main()
