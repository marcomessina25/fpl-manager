"""Participation error diagnostics and error decomposition engine for V0.8.1.

Implements Phases 1 & 2 of the V0.8 Roadmap (docs/v08/v08.md):
- 5.1 Player-GW diagnostic table with pre-deadline features and ground truth outcomes.
- 5.2 High-confidence false-positive isolation (P(start) >= 0.70 or xM >= 60 but actual minutes = 0).
- 5.3 Large-minute error isolation (predicted 60-90 actual 0-30; predicted 0-30 actual 60-90).
- 6.0 Root-cause decomposition: injury/fitness, congestion rotation, role change, tactical omission, early sub.
- 10.0 Decision-level impact and points lost due to participation errors.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from ..evaluation import mean_absolute_error, root_mean_squared_error
from ..expected_points import ExpectedPointsProjection
from ..historical.models import Position
from ..historical.reconstruction import reconstruct_features_and_project
from ..historical.snapshots import build_historical_snapshot, load_gameweek_outcomes


@dataclass(frozen=True, slots=True)
class ParticipationDiagnosticRecord:
    """Diagnostic observation record pairing pre-deadline projection signals with matchday outcome."""
    season: str
    gameweek: int
    player_id: int
    web_name: str
    team_id: int
    position: Position
    price_tenths: int
    status: str
    chance_of_playing: int | None
    predicted_availability: float
    predicted_start_prob: float
    predicted_expected_minutes: float
    predicted_xp: float
    actual_started: bool
    actual_minutes: int
    actual_points: int
    historical_starts: int
    historical_minutes: int
    starts_last_3: int
    starts_last_5: int
    minutes_last_3: int
    minutes_last_5: int
    consecutive_zero_mins: int
    days_since_prev_fixture: float | None
    matches_last_7_days: int
    matches_last_14_days: int
    fdr: int
    is_home: bool
    error_category: str
    root_cause: str
    decision_penalty: float


def _safe_mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def classify_participation_error(
    predicted_start_prob: float,
    predicted_xm: float,
    predicted_xp: float,
    status: str,
    chance_of_playing: int | None,
    actual_started: bool,
    actual_minutes: int,
    actual_points: int,
    consecutive_zero_mins: int,
    starts_last_3: int,
    days_since_prev_fixture: float | None,
    matches_last_7_days: int,
) -> tuple[str, str, float]:
    """Decompose error into diagnostic category, root cause, and estimated decision penalty."""
    # 1. Error Category Classification
    if (predicted_start_prob >= 0.70 or predicted_xm >= 60.0) and actual_minutes == 0:
        error_category = "HIGH_CONFIDENCE_FALSE_POSITIVE"
    elif predicted_xm >= 60.0 and actual_minutes <= 30:
        error_category = "FALSE_STARTER"
    elif predicted_xm <= 30.0 and actual_minutes >= 60:
        error_category = "SURPRISE_STARTER"
    elif abs(predicted_xm - actual_minutes) <= 15.0:
        error_category = "ACCURATE"
    else:
        error_category = "MODERATE_MISS"

    # 2. Root Cause Decomposition (Phase 2)
    status_lower = status.lower()
    if status_lower in ("d", "i", "s", "u") or (chance_of_playing is not None and chance_of_playing < 100):
        if status_lower == "s":
            root_cause = "SUSPENSION"
        else:
            root_cause = "INJURY_FITNESS_DOUBT"
    elif consecutive_zero_mins >= 2 or (starts_last_3 == 0 and consecutive_zero_mins >= 1):
        root_cause = "ROLE_LOSS"
    elif (days_since_prev_fixture is not None and days_since_prev_fixture <= 3.2) or matches_last_7_days >= 2:
        root_cause = "CONGESTION_ROTATION"
    elif actual_minutes == 0 and status_lower == "a":
        root_cause = "TACTICAL_BENCH"
    elif actual_started and actual_minutes < 60:
        root_cause = "EARLY_SUBSTITUTION"
    elif not actual_started and 0 < actual_minutes <= 30:
        root_cause = "SUBSTITUTE_APPEARANCE"
    else:
        root_cause = "GENUINE_MODEL_MISS"

    # 3. Decision Penalty Calculation
    # Quantifies points foregone by the manager by relying on false signals
    if error_category == "HIGH_CONFIDENCE_FALSE_POSITIVE":
        decision_penalty = max(0.0, round(predicted_xp - float(actual_points), 2))
    elif error_category == "SURPRISE_STARTER":
        decision_penalty = max(0.0, round(float(actual_points) - predicted_xp, 2))
    elif error_category == "FALSE_STARTER":
        decision_penalty = max(0.0, round(predicted_xp * 0.5 - float(actual_points), 2))
    else:
        decision_penalty = 0.0

    return error_category, root_cause, decision_penalty


def diagnose_participation_records(
    records: list[ParticipationDiagnosticRecord],
) -> dict[str, Any]:
    """Aggregate diagnostic metrics across all historical player-gameweek records."""
    if not records:
        return {"total_records": 0}

    total_records = len(records)
    act_mins = [float(r.actual_minutes) for r in records]
    pred_mins = [r.predicted_expected_minutes for r in records]

    # Minutes error
    xm_mae = mean_absolute_error(pred_mins, act_mins)
    xm_rmse = root_mean_squared_error(pred_mins, act_mins)
    xm_bias = round(_safe_mean([p - a for p, a in zip(pred_mins, act_mins)]), 3)

    # Minutes calibration by bucket
    mins_buckets = {
        "0-15": [r for r in records if r.predicted_expected_minutes <= 15.0],
        "16-30": [r for r in records if 15.0 < r.predicted_expected_minutes <= 30.0],
        "31-60": [r for r in records if 30.0 < r.predicted_expected_minutes <= 60.0],
        "61-75": [r for r in records if 60.0 < r.predicted_expected_minutes <= 75.0],
        "76-90": [r for r in records if r.predicted_expected_minutes > 75.0],
    }
    bucket_metrics: dict[str, Any] = {}
    for b_name, b_recs in mins_buckets.items():
        if b_recs:
            b_pred = [r.predicted_expected_minutes for r in b_recs]
            b_act = [float(r.actual_minutes) for r in b_recs]
            b_zeros = sum(1 for r in b_recs if r.actual_minutes == 0)
            bucket_metrics[b_name] = {
                "count": len(b_recs),
                "mean_predicted": _safe_mean(b_pred),
                "mean_actual": _safe_mean(b_act),
                "mae": mean_absolute_error(b_pred, b_act),
                "zero_min_count": b_zeros,
                "zero_min_rate": round(b_zeros / len(b_recs), 4),
            }
        else:
            bucket_metrics[b_name] = {
                "count": 0,
                "mean_predicted": 0.0,
                "mean_actual": 0.0,
                "mae": 0.0,
                "zero_min_count": 0,
                "zero_min_rate": 0.0,
            }

    # Error classification counts
    fp_records = [r for r in records if r.error_category == "HIGH_CONFIDENCE_FALSE_POSITIVE"]
    false_starters = [r for r in records if r.error_category == "FALSE_STARTER"]
    surprise_starters = [r for r in records if r.error_category == "SURPRISE_STARTER"]
    accurate_records = [r for r in records if r.error_category == "ACCURATE"]

    # Root Cause Breakdown
    root_causes = [
        "INJURY_FITNESS_DOUBT",
        "SUSPENSION",
        "CONGESTION_ROTATION",
        "ROLE_LOSS",
        "TACTICAL_BENCH",
        "EARLY_SUBSTITUTION",
        "SUBSTITUTE_APPEARANCE",
        "GENUINE_MODEL_MISS",
    ]
    non_accurate_recs = [r for r in records if r.error_category != "ACCURATE"]
    total_non_accurate = len(non_accurate_recs)
    root_cause_counts: dict[str, dict[str, Any]] = {}
    for rc in root_causes:
        rc_recs = [r for r in non_accurate_recs if r.root_cause == rc]
        rc_penalty = sum(r.decision_penalty for r in rc_recs)
        root_cause_counts[rc] = {
            "count": len(rc_recs),
            "pct_of_errors": round((len(rc_recs) / total_non_accurate) * 100.0, 1) if total_non_accurate > 0 else 0.0,
            "total_penalty": round(rc_penalty, 1),
            "mean_penalty": round(rc_penalty / len(rc_recs), 2) if rc_recs else 0.0,
        }

    # Positional Breakdown of High-Confidence False Positives
    by_position: dict[str, Any] = {}
    for pos in Position:
        pos_recs = [r for r in records if r.position == pos]
        pos_fps = [r for r in fp_records if r.position == pos]
        if pos_recs:
            by_position[pos.name] = {
                "total_players": len(pos_recs),
                "false_positives": len(pos_fps),
                "fp_rate": round(len(pos_fps) / len(pos_recs), 4),
            }

    # Price Tier Breakdown of False Positives
    price_tiers = {
        "budget (<=5.0m)": [r for r in records if r.price_tenths <= 50],
        "mid-price (5.1-8.0m)": [r for r in records if 50 < r.price_tenths <= 80],
        "premium (>8.0m)": [r for r in records if r.price_tenths > 80],
    }
    by_price: dict[str, Any] = {}
    for tier_name, tier_recs in price_tiers.items():
        tier_fps = [r for r in fp_records if r in tier_recs]
        if tier_recs:
            by_price[tier_name] = {
                "total_players": len(tier_recs),
                "false_positives": len(tier_fps),
                "fp_rate": round(len(tier_fps) / len(tier_recs), 4),
            }

    # Top False Positive Culprits (Highest xP projected players who played 0 minutes)
    sorted_fps = sorted(fp_records, key=lambda r: (r.predicted_xp, r.predicted_expected_minutes), reverse=True)
    top_culprits = [
        {
            "player_id": r.player_id,
            "web_name": r.web_name,
            "gameweek": r.gameweek,
            "position": r.position.name,
            "price": round(r.price_tenths / 10.0, 1),
            "predicted_xp": r.predicted_xp,
            "predicted_xm": r.predicted_expected_minutes,
            "predicted_start": r.predicted_start_prob,
            "status": r.status,
            "root_cause": r.root_cause,
            "penalty": r.decision_penalty,
        }
        for r in sorted_fps[:20]
    ]

    total_decision_penalty = sum(r.decision_penalty for r in records)
    unique_gws = len(set(r.gameweek for r in records))
    mean_gw_penalty = round(total_decision_penalty / unique_gws, 2) if unique_gws > 0 else 0.0

    return {
        "total_records": total_records,
        "active_players_count": sum(1 for r in records if r.actual_minutes > 0),
        "zero_minute_count": sum(1 for r in records if r.actual_minutes == 0),
        "zero_minute_rate": round(sum(1 for r in records if r.actual_minutes == 0) / total_records, 4),
        "overall_xm_mae": xm_mae,
        "overall_xm_rmse": xm_rmse,
        "overall_xm_bias": xm_bias,
        "accuracy_rate": round(len(accurate_records) / total_records, 4),
        "bucket_metrics": bucket_metrics,
        "false_positives": {
            "count": len(fp_records),
            "rate": round(len(fp_records) / total_records, 4),
            "by_position": by_position,
            "by_price_tier": by_price,
            "top_culprits": top_culprits,
        },
        "large_minute_errors": {
            "false_starters_count": len(false_starters),
            "surprise_starters_count": len(surprise_starters),
            "total_large_errors": len(false_starters) + len(surprise_starters),
        },
        "root_cause_decomposition": root_cause_counts,
        "decision_impact": {
            "total_penalty_points": round(total_decision_penalty, 1),
            "mean_gw_penalty": mean_gw_penalty,
            "false_positive_penalty": round(sum(r.decision_penalty for r in fp_records), 1),
            "surprise_starter_penalty": round(sum(r.decision_penalty for r in surprise_starters), 1),
        },
    }


def run_participation_diagnostics(
    season_dir: Path,
    start_gw: int = 1,
    end_gw: int = 38,
    save_report: bool = False,
    output_path: Path | None = None,
) -> tuple[dict[str, Any], list[ParticipationDiagnosticRecord]]:
    """Execute complete historical participation error diagnostics across gameweeks."""
    all_records: list[ParticipationDiagnosticRecord] = []

    for gw in range(start_gw, end_gw + 1):
        snapshot = build_historical_snapshot(season_dir, gw)
        projections = reconstruct_features_and_project(snapshot)
        outcomes = load_gameweek_outcomes(season_dir, gw)

        proj_map = {p.player_id: p for p in projections}
        state_map = {p.player_id: p for p in snapshot.players}

        # Match fixtures for turnaround info
        fixture_map_h = {f.team_h: f for f in snapshot.fixtures}
        fixture_map_a = {f.team_a: f for f in snapshot.fixtures}

        for pid, outcome in outcomes.items():
            proj = proj_map.get(pid)
            state = state_map.get(pid)
            if proj is None or state is None:
                continue

            # Schedule metrics
            days_prev = None
            m7 = 0
            m14 = 0
            fdr = 3
            is_home = True
            if state.team_id in fixture_map_h:
                f_obj = fixture_map_h[state.team_id]
                days_prev = f_obj.days_since_prev_h
                m7 = f_obj.matches_7d_h
                m14 = f_obj.matches_14d_h
                fdr = f_obj.team_h_difficulty
                is_home = True
            elif state.team_id in fixture_map_a:
                f_obj = fixture_map_a[state.team_id]
                days_prev = f_obj.days_since_prev_a
                m7 = f_obj.matches_7d_a
                m14 = f_obj.matches_14d_a
                fdr = f_obj.team_a_difficulty
                is_home = False

            err_cat, root_cause, penalty = classify_participation_error(
                predicted_start_prob=proj.start_probability,
                predicted_xm=proj.expected_minutes,
                predicted_xp=proj.expected_points,
                status=state.status,
                chance_of_playing=state.chance_of_playing_next_round,
                actual_started=outcome.starts > 0,
                actual_minutes=outcome.minutes,
                actual_points=outcome.total_points,
                consecutive_zero_mins=state.consecutive_zero_mins,
                starts_last_3=state.starts_last_3,
                days_since_prev_fixture=days_prev,
                matches_last_7_days=m7,
            )

            rec = ParticipationDiagnosticRecord(
                season=snapshot.season,
                gameweek=gw,
                player_id=pid,
                web_name=proj.web_name,
                team_id=proj.team_id,
                position=proj.position,
                price_tenths=proj.price_tenths,
                status=state.status,
                chance_of_playing=state.chance_of_playing_next_round,
                predicted_availability=round(proj.play_probability, 2) if hasattr(proj, "play_probability") else round(proj.availability_pct / 100.0, 2),
                predicted_start_prob=proj.start_probability,
                predicted_expected_minutes=proj.expected_minutes,
                predicted_xp=proj.expected_points,
                actual_started=outcome.starts > 0,
                actual_minutes=outcome.minutes,
                actual_points=outcome.total_points,
                historical_starts=state.starts,
                historical_minutes=state.minutes,
                starts_last_3=state.starts_last_3,
                starts_last_5=state.starts_last_5,
                minutes_last_3=state.minutes_last_3,
                minutes_last_5=state.minutes_last_5,
                consecutive_zero_mins=state.consecutive_zero_mins,
                days_since_prev_fixture=days_prev,
                matches_last_7_days=m7,
                matches_last_14_days=m14,
                fdr=fdr,
                is_home=is_home,
                error_category=err_cat,
                root_cause=root_cause,
                decision_penalty=penalty,
            )
            all_records.append(rec)

    diagnostics = diagnose_participation_records(all_records)

    if save_report:
        from .reporting import build_backtest_report_path, save_backtest_report
        season_name = season_dir.name
        report_text = format_participation_report(diagnostics, season=season_name, gameweek_range=f"{start_gw}-{end_gw}")
        target_path = output_path or build_backtest_report_path("participation", season_name, start_gw, end_gw)
        save_backtest_report(report_text, target_path)
        diagnostics["saved_report_path"] = str(target_path)

    return diagnostics, all_records


def format_participation_report(diagnostics: dict[str, Any], season: str, gameweek_range: str) -> str:
    """Format Markdown research report detailing participation failure modes and decomposition."""
    tot = diagnostics.get("total_records", 0)
    fp = diagnostics.get("false_positives", {})
    lge = diagnostics.get("large_minute_errors", {})
    rc = diagnostics.get("root_cause_decomposition", {})
    buckets = diagnostics.get("bucket_metrics", {})
    dec = diagnostics.get("decision_impact", {})

    lines = [
        f"# Participation Error Diagnostics & Root-Cause Decomposition Report",
        f"",
        f"- **Season:** `{season}`",
        f"- **Gameweek Range:** `GW{gameweek_range}`",
        f"- **Generated At:** `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}`",
        f"- **Total Evaluated Player-Gameweeks:** `{tot:,}`",
        f"- **Overall xM MAE:** `{diagnostics.get('overall_xm_mae', 0.0):.2f} mins` (RMSE: `{diagnostics.get('overall_xm_rmse', 0.0):.2f}`)",
        f"- **Zero-Minute Inactive Rate:** `{diagnostics.get('zero_minute_rate', 0.0) * 100:.1f}%` ({diagnostics.get('zero_minute_count', 0):,} occurrences)",
        f"",
        f"---",
        f"",
        f"## 1. Executive Summary & V0.8.1 Key Findings",
        f"",
        f"1. **High-Confidence False Positives:** `{fp.get('count', 0):,}` instances where players were projected as nailed starters ($P(\\text{{start}}) \\ge 0.70$ or $xM \\ge 60.0$) but logged 0 minutes.",
        f"2. **Total Manager Decision Penalty:** **`{dec.get('total_penalty_points', 0.0):,.1f} points`** lost due to participation errors (mean `{dec.get('mean_gw_penalty', 0.0):.1f} pts/GW`).",
        f"3. **The Rotation Cohort Bottleneck:** The `31-60 min` and `61-75 min` buckets continue to represent the largest absolute MAE regions.",
        f"",
        f"---",
        f"",
        f"## 2. Expected Minutes (xM) Calibration by Projection Bucket",
        f"",
        f"| Predicted Range | Count | Mean Predicted | Mean Actual | MAE (mins) | Zero-Min Count | Zero-Min % |",
        f"|---|---|---|---|---|---|---|",
    ]

    for b_name in ("0-15", "16-30", "31-60", "61-75", "76-90"):
        b_data = buckets.get(b_name, {})
        c = b_data.get("count", 0)
        mp = b_data.get("mean_predicted", 0.0)
        ma = b_data.get("mean_actual", 0.0)
        mae = b_data.get("mae", 0.0)
        zc = b_data.get("zero_min_count", 0)
        zr = b_data.get("zero_min_rate", 0.0) * 100.0
        lines.append(f"| `{b_name}` | {c:,} | {mp:.1f} | {ma:.1f} | **{mae:.1f}** | {zc:,} | {zr:.1f}% |")

    lines.extend([
        f"",
        f"---",
        f"",
        f"## 3. Root-Cause Error Decomposition (Phase 2)",
        f"",
        f"| Root Cause Category | Count | % of Errors | Total Penalty (pts) | Mean Penalty / Case |",
        f"|---|---|---|---|---|",
    ])

    for rc_name, rc_data in rc.items():
        c = rc_data.get("count", 0)
        pct = rc_data.get("pct_of_errors", 0.0)
        tot_pen = rc_data.get("total_penalty", 0.0)
        mean_pen = rc_data.get("mean_penalty", 0.0)
        lines.append(f"| `{rc_name}` | {c:,} | **{pct:.1f}%** | {tot_pen:,.1f} | {mean_pen:.2f} |")

    lines.extend([
        f"",
        f"---",
        f"",
        f"## 4. High-Confidence False Positives Breakdown",
        f"",
        f"### By Position",
        f"",
        f"| Position | Total Players | False Positives | FP Rate |",
        f"|---|---|---|---|",
    ])

    for pos_name, p_data in fp.get("by_position", {}).items():
        tot_p = p_data.get("total_players", 0)
        fps = p_data.get("false_positives", 0)
        fpr = p_data.get("fp_rate", 0.0) * 100.0
        lines.append(f"| `{pos_name}` | {tot_p:,} | {fps:,} | **{fpr:.2f}%** |")

    lines.extend([
        f"",
        f"### By Price Tier",
        f"",
        f"| Price Tier | Total Players | False Positives | FP Rate |",
        f"|---|---|---|---|",
    ])

    for tier_name, t_data in fp.get("by_price_tier", {}).items():
        tot_p = t_data.get("total_players", 0)
        fps = t_data.get("false_positives", 0)
        fpr = t_data.get("fp_rate", 0.0) * 100.0
        lines.append(f"| `{tier_name}` | {tot_p:,} | {fps:,} | **{fpr:.2f}%** |")

    lines.extend([
        f"",
        f"---",
        f"",
        f"## 5. Top False Positive Culprits (High Projected xP with 0 Minutes)",
        f"",
        f"| GW | Player | Pos | Price | Pred xP | Pred xM | Pred P(start) | Status | Root Cause | Penalty |",
        f"|---|---|---|---|---|---|---|---|---|---|",
    ])

    for culprit in fp.get("top_culprits", []):
        gw = culprit.get("gameweek")
        name = culprit.get("web_name")
        pos = culprit.get("position")
        price = culprit.get("price")
        xp = culprit.get("predicted_xp")
        xm = culprit.get("predicted_xm")
        p_start = culprit.get("predicted_start")
        stat = culprit.get("status")
        rc_val = culprit.get("root_cause")
        pen = culprit.get("penalty")
        lines.append(f"| GW{gw:02d} | **{name}** | {pos} | £{price:.1f}m | {xp:.2f} | {xm:.1f} | {p_start:.2f} | `{stat}` | `{rc_val}` | {pen:.1f} |")

    lines.append("")
    return "\n".join(lines)
