"""Residual-error research dataset and error classification taxonomy for V0.9 Phase 1.

Implements Section 5 of V0.9 Plan (docs/v09/v09.md):
- Decomposes every player-gameweek into pre-deadline projection features vs. actual outcome.
- Captures: season, gameweek, player_id, team_id, position, price, FPL status, chance of playing,
  p_start, p_sub, p_play, expected_minutes, actual_minutes, actual_started, actual_points,
  and pre-deadline schedule/historical features.
- Classifies residual errors into the 9-class V0.9 taxonomy:
    1. NO_APPEARANCE
    2. BENCHED
    3. SUB_APPEARANCE
    4. EARLY_SUBSTITUTION
    5. ROLE_LOSS
    6. RETURN_FROM_INJURY
    7. TACTICAL_CHANGE
    8. CONGESTION
    9. UNKNOWN
- Guarantees strict temporal point-in-time discipline: no post-deadline leakage is used
  for predictions. Ground truth outcomes are used strictly for diagnostic evaluation labelling.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from ..calibration import compute_reliability_curve
from ..evaluation import mean_absolute_error, root_mean_squared_error
from ..expected_points import ExpectedPointsProjection
from ..historical.models import Position
from ..historical.reconstruction import reconstruct_features_and_project
from ..historical.snapshots import build_historical_snapshot, load_gameweek_outcomes


V09_ERROR_TAXONOMY = (
    "NO_APPEARANCE",
    "BENCHED",
    "SUB_APPEARANCE",
    "EARLY_SUBSTITUTION",
    "ROLE_LOSS",
    "RETURN_FROM_INJURY",
    "TACTICAL_CHANGE",
    "CONGESTION",
    "UNKNOWN",
)


@dataclass(frozen=True, slots=True)
class ResidualRecord:
    """Individual player-gameweek observation pairing pre-deadline signals with matchday outcome."""

    # 1. Identity & Metadata
    season: str
    gameweek: int
    player_id: int
    web_name: str
    team_id: int
    position: Position
    price_tenths: int
    status: str
    chance_of_playing: int | None

    # 2. Pre-deadline Model Projections
    p_start: float
    p_sub: float
    p_play: float
    expected_minutes: float
    predicted_xp: float

    # 3. Ground Truth Matchday Outcomes
    actual_minutes: int
    actual_started: bool
    actual_points: int

    # 4. Pre-deadline Historical & Schedule Features
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

    # 5. Diagnostic Evaluation Labels & Metrics
    error_category: str
    residual_classification: str
    minute_error: float
    absolute_minute_error: float
    decision_penalty: float


def _safe_mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def _brier_score(probabilities: list[float], outcomes: list[int]) -> float:
    """Compute Brier score (mean squared error of probability predictions)."""
    if not probabilities or len(probabilities) != len(outcomes):
        return 0.0
    return round(sum((p - y) ** 2 for p, y in zip(probabilities, outcomes)) / len(probabilities), 4)


def classify_v09_residual_error(
    p_start: float,
    p_sub: float,
    p_play: float,
    expected_minutes: float,
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
    """Decompose prediction error into high-level category, V0.9 taxonomy class, and decision penalty.

    Guarantees:
    - Never uses post-deadline information for prediction.
    - Ground truth is strictly used for diagnostic evaluation labelling.
    """
    # 1. Error category classification (consistent with V0.8 diagnostic thresholds)
    if (p_start >= 0.70 or expected_minutes >= 60.0) and actual_minutes == 0:
        error_category = "HIGH_CONFIDENCE_FALSE_POSITIVE"
    elif expected_minutes >= 60.0 and actual_minutes <= 30:
        error_category = "FALSE_STARTER"
    elif expected_minutes <= 30.0 and actual_minutes >= 60:
        error_category = "SURPRISE_STARTER"
    elif abs(expected_minutes - float(actual_minutes)) <= 15.0:
        error_category = "ACCURATE"
    else:
        error_category = "MODERATE_MISS"

    # 2. Decision penalty quantification
    if error_category == "HIGH_CONFIDENCE_FALSE_POSITIVE":
        decision_penalty = max(0.0, round(predicted_xp - float(actual_points), 2))
    elif error_category == "SURPRISE_STARTER":
        decision_penalty = max(0.0, round(float(actual_points) - predicted_xp, 2))
    elif error_category == "FALSE_STARTER":
        decision_penalty = max(0.0, round(predicted_xp * 0.5 - float(actual_points), 2))
    else:
        decision_penalty = 0.0

    # 3. V0.9 9-Class Residual Error Taxonomy
    if error_category == "ACCURATE":
        residual_class = "ACCURATE"
    else:
        status_lower = status.lower()

        # Class 4: EARLY_SUBSTITUTION — player started, but was taken off early (< 60 mins)
        if actual_started and actual_minutes < 60:
            residual_class = "EARLY_SUBSTITUTION"

        # Class 3: SUB_APPEARANCE — player did not start, but came on as a substitute
        elif not actual_started and 0 < actual_minutes <= 45:
            residual_class = "SUB_APPEARANCE"

        # Class 6: RETURN_FROM_INJURY — player returning from known fitness doubt / absence
        elif actual_minutes > 0 and (
            status_lower in ("i", "d")
            or (chance_of_playing is not None and chance_of_playing < 100)
            or consecutive_zero_mins >= 2
        ):
            residual_class = "RETURN_FROM_INJURY"

        # Cases where player played 0 minutes
        elif actual_minutes == 0:
            # Class 1: NO_APPEARANCE — absence due to confirmed injury, suspension, or active doubt
            if status_lower in ("i", "d", "s", "u") or (chance_of_playing is not None and chance_of_playing < 100):
                residual_class = "NO_APPEARANCE"

            # Class 5: ROLE_LOSS — displacement from the team due to persistent benching / 0s
            elif consecutive_zero_mins >= 2 or (starts_last_3 == 0 and consecutive_zero_mins >= 1):
                residual_class = "ROLE_LOSS"

            # Class 8: CONGESTION — fixture turnaround or density induced rest
            elif (days_since_prev_fixture is not None and days_since_prev_fixture <= 3.2) or matches_last_7_days >= 2:
                residual_class = "CONGESTION"

            # Class 7: TACTICAL_CHANGE — fit regular starter unexpectedly dropped
            elif starts_last_3 >= 2 and status_lower == "a":
                residual_class = "TACTICAL_CHANGE"

            # Class 2: BENCHED — fit outfield / fringe player remained unplayed
            else:
                residual_class = "BENCHED"

        # Class 7 (continued): surprise full match starter for fit player
        elif actual_started and actual_minutes >= 60 and expected_minutes <= 30.0:
            residual_class = "TACTICAL_CHANGE"

        # Class 9: UNKNOWN — residual errors not cleanly matching patterns
        else:
            residual_class = "UNKNOWN"

    return error_category, residual_class, decision_penalty


def build_residual_dataset(
    season_dir: Path,
    start_gw: int = 1,
    end_gw: int = 38,
    predictor_version: str = "v0.8",
) -> list[ResidualRecord]:
    """Build the point-in-time residual observation dataset across a range of gameweeks."""
    records: list[ResidualRecord] = []

    for gw in range(start_gw, end_gw + 1):
        snapshot = build_historical_snapshot(season_dir, gw)
        if snapshot is None or not snapshot.players:
            continue

        outcomes = load_gameweek_outcomes(season_dir, gw)
        if not outcomes:
            continue

        projections = reconstruct_features_and_project(
            snapshot,
            predictor_version=predictor_version,
        )

        proj_map = {p.player_id: p for p in projections}
        state_map = {p.player_id: p for p in snapshot.players}

        fixture_map_h = {f.team_h: f for f in snapshot.fixtures}
        fixture_map_a = {f.team_a: f for f in snapshot.fixtures}

        for pid, outcome in outcomes.items():
            proj = proj_map.get(pid)
            state = state_map.get(pid)
            if proj is None or state is None:
                continue

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

            # Probability extraction
            p_start = getattr(proj, "start_probability", 0.0)
            p_sub = getattr(proj, "sub_probability", 0.0)
            p_play = getattr(proj, "play_probability", round(proj.availability_pct / 100.0, 2))
            exp_mins = getattr(proj, "expected_minutes", 0.0)
            pred_xp = getattr(proj, "expected_points", 0.0)

            err_cat, res_class, penalty = classify_v09_residual_error(
                p_start=p_start,
                p_sub=p_sub,
                p_play=p_play,
                expected_minutes=exp_mins,
                predicted_xp=pred_xp,
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

            rec = ResidualRecord(
                season=snapshot.season,
                gameweek=gw,
                player_id=pid,
                web_name=proj.web_name,
                team_id=proj.team_id,
                position=proj.position,
                price_tenths=proj.price_tenths,
                status=state.status,
                chance_of_playing=state.chance_of_playing_next_round,
                p_start=round(p_start, 3),
                p_sub=round(p_sub, 3),
                p_play=round(p_play, 3),
                expected_minutes=round(exp_mins, 1),
                predicted_xp=round(pred_xp, 2),
                actual_minutes=outcome.minutes,
                actual_started=outcome.starts > 0,
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
                residual_classification=res_class,
                minute_error=round(exp_mins - outcome.minutes, 2),
                absolute_minute_error=round(abs(exp_mins - outcome.minutes), 2),
                decision_penalty=penalty,
            )
            records.append(rec)

    return records


def diagnose_residual_dataset(records: list[ResidualRecord]) -> dict[str, Any]:
    """Aggregate comprehensive residual-error diagnostics across observation records."""
    if not records:
        return {"total_records": 0}

    total_records = len(records)
    act_mins = [float(r.actual_minutes) for r in records]
    pred_mins = [r.expected_minutes for r in records]

    # Global minute metrics
    xm_mae = mean_absolute_error(pred_mins, act_mins)
    xm_rmse = root_mean_squared_error(pred_mins, act_mins)
    xm_bias = round(_safe_mean([p - a for p, a in zip(pred_mins, act_mins)]), 3)

    # Global xP metrics
    act_pts = [float(r.actual_points) for r in records]
    pred_xps = [r.predicted_xp for r in records]
    xp_mae = mean_absolute_error(pred_xps, act_pts)
    xp_rmse = root_mean_squared_error(pred_xps, act_pts)

    # Probability calibration metrics (Brier Scores, Log Loss & ECE)
    start_curve = compute_reliability_curve(
        [r.p_start for r in records],
        [1 if r.actual_started else 0 for r in records],
        n_bins=10,
    )
    play_curve = compute_reliability_curve(
        [r.p_play for r in records],
        [1 if r.actual_minutes > 0 else 0 for r in records],
        n_bins=10,
    )

    # Inactive rate
    zero_mins = sum(1 for r in records if r.actual_minutes == 0)
    zero_min_rate = round(zero_mins / total_records, 4)

    # Minute calibration by predicted-minute bucket
    mins_buckets = {
        "0-15": [r for r in records if r.expected_minutes <= 15.0],
        "16-30": [r for r in records if 15.0 < r.expected_minutes <= 30.0],
        "31-60": [r for r in records if 30.0 < r.expected_minutes <= 60.0],
        "61-75": [r for r in records if 60.0 < r.expected_minutes <= 75.0],
        "76-90": [r for r in records if r.expected_minutes > 75.0],
    }
    bucket_metrics: dict[str, Any] = {}
    for b_name, b_recs in mins_buckets.items():
        if b_recs:
            b_pred = [r.expected_minutes for r in b_recs]
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

    # Error category counts
    non_accurate_recs = [r for r in records if r.error_category != "ACCURATE"]
    total_non_accurate = len(non_accurate_recs)
    fp_records = [r for r in records if r.error_category == "HIGH_CONFIDENCE_FALSE_POSITIVE"]
    total_decision_penalty = round(sum(r.decision_penalty for r in records), 2)

    # 9-Class V0.9 Taxonomy Breakdown
    taxonomy_counts: dict[str, dict[str, Any]] = {}
    for taxon in V09_ERROR_TAXONOMY:
        t_recs = [r for r in non_accurate_recs if r.residual_classification == taxon]
        t_penalty = sum(r.decision_penalty for r in t_recs)
        t_min_err = [r.minute_error for r in t_recs]
        t_abs_err = [r.absolute_minute_error for r in t_recs]
        taxonomy_counts[taxon] = {
            "count": len(t_recs),
            "pct_of_errors": round((len(t_recs) / total_non_accurate) * 100.0, 1) if total_non_accurate > 0 else 0.0,
            "pct_of_total": round((len(t_recs) / total_records) * 100.0, 1),
            "mean_minute_error": _safe_mean(t_min_err),
            "mae_minutes": _safe_mean(t_abs_err),
            "total_penalty": round(t_penalty, 1),
            "mean_penalty": round(t_penalty / len(t_recs), 2) if t_recs else 0.0,
        }

    # High Confidence False Positive Top Culprits
    fp_sorted = sorted(fp_records, key=lambda r: r.predicted_xp, reverse=True)[:20]
    top_culprits = [
        {
            "gameweek": r.gameweek,
            "player_id": r.player_id,
            "web_name": r.web_name,
            "position": r.position.name,
            "price_tenths": r.price_tenths,
            "predicted_xp": r.predicted_xp,
            "predicted_xm": r.expected_minutes,
            "p_start": r.p_start,
            "status": r.status,
            "residual_classification": r.residual_classification,
            "penalty": r.decision_penalty,
        }
        for r in fp_sorted
    ]

    return {
        "total_records": total_records,
        "accurate_records": total_records - total_non_accurate,
        "non_accurate_records": total_non_accurate,
        "xm_mae": xm_mae,
        "xm_rmse": xm_rmse,
        "xm_bias": xm_bias,
        "xp_mae": xp_mae,
        "xp_rmse": xp_rmse,
        "brier_start": start_curve.brier_score,
        "brier_play": play_curve.brier_score,
        "ece_start": start_curve.expected_calibration_error,
        "mce_start": start_curve.maximum_calibration_error,
        "log_loss_start": start_curve.log_loss,
        "ece_play": play_curve.expected_calibration_error,
        "mce_play": play_curve.maximum_calibration_error,
        "log_loss_play": play_curve.log_loss,
        "start_curve_buckets": [
            {
                "bin_min": b.bin_min,
                "bin_max": b.bin_max,
                "count": b.count,
                "mean_predicted": b.mean_predicted,
                "empirical_rate": b.empirical_rate,
                "calibration_error": b.calibration_error,
            }
            for b in start_curve.buckets
        ],
        "zero_min_count": zero_mins,
        "zero_min_rate": zero_min_rate,
        "high_confidence_false_positives": len(fp_records),
        "total_decision_penalty": total_decision_penalty,
        "bucket_metrics": bucket_metrics,
        "residual_taxonomy": taxonomy_counts,
        "top_culprits": top_culprits,
    }


def format_residual_dataset_report(
    summary: dict[str, Any],
    season: str,
    gameweek_range: str,
) -> str:
    """Format diagnostic summary into a structured GitHub-style Markdown report."""
    total_recs = summary.get("total_records", 0)
    if total_recs == 0:
        return "# V0.9 Residual-Error Dataset Report\n\nNo records evaluated."

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    xm_mae = summary.get("xm_mae", 0.0)
    xm_rmse = summary.get("xm_rmse", 0.0)
    xm_bias = summary.get("xm_bias", 0.0)
    brier_start = summary.get("brier_start", 0.0)
    ece_start = summary.get("ece_start", 0.0)
    log_loss_start = summary.get("log_loss_start", 0.0)
    brier_play = summary.get("brier_play", 0.0)
    zero_pct = round(summary.get("zero_min_rate", 0.0) * 100.0, 1)
    zero_cnt = summary.get("zero_min_count", 0)
    fp_cnt = summary.get("high_confidence_false_positives", 0)
    tot_penalty = summary.get("total_decision_penalty", 0.0)

    lines: list[str] = [
        "# V0.9 Residual-Error Dataset & Error Decomposition Report",
        "",
        f"- **Season:** `{season}`",
        f"- **Gameweek Range:** `{gameweek_range}`",
        f"- **Generated At:** `{now_utc}`",
        f"- **Total Evaluated Observations:** `{total_recs:,}`",
        f"- **Global xM MAE:** `{xm_mae:.2f} mins` (RMSE: `{xm_rmse:.2f}`, Bias: `{xm_bias:+.2f}` mins)",
        f"- **Probability Calibration (P(start)):** Brier=`{brier_start:.4f}`, ECE=`{ece_start:.4f}`, LogLoss=`{log_loss_start:.4f}`",
        f"- **Probability Calibration (P(play)):** Brier=`{brier_play:.4f}`",
        f"- **Zero-Minute Inactive Rate:** `{zero_pct}%` ({zero_cnt:,} occurrences)",
        "",
        "---",
        "",
        "## 1. Executive Summary & V0.9 Phase 1 Baseline Findings",
        "",
        f"1. **High-Confidence False Positives:** `{fp_cnt}` instances where players were projected as nailed starters ($P(\\text{{start}}) \\ge 0.70$ or $xM \\ge 60.0$) but logged 0 minutes.",
        f"2. **Total Manager Decision Penalty:** **`{tot_penalty:.1f} points`** lost due to participation errors.",
        "3. **Research Dataset Status:** Observations extracted with pre-deadline feature isolation and ground truth diagnostic labels ready for learned participation modelling.",
        "",
        "---",
        "",
        "## 2. Expected Minutes (xM) Calibration by Projection Bucket",
        "",
        "| Predicted Range | Count | Mean Predicted | Mean Actual | MAE (mins) | Zero-Min Count | Zero-Min % |",
        "|---|---|---|---|---|---|---|",
    ]

    for b_name, b_data in summary.get("bucket_metrics", {}).items():
        z_pct = round(b_data.get("zero_min_rate", 0.0) * 100.0, 1)
        lines.append(
            f"| `{b_name}` | {b_data.get('count', 0):,} | {b_data.get('mean_predicted', 0.0):.1f} | "
            f"{b_data.get('mean_actual', 0.0):.1f} | **{b_data.get('mae', 0.0):.1f}** | "
            f"{b_data.get('zero_min_count', 0):,} | {z_pct}% |"
        )

    start_buckets = summary.get("start_curve_buckets", [])
    if start_buckets:
        lines.extend([
            "",
            "---",
            "",
            "## 3. Probability Calibration Reliability Diagram (P(start))",
            "",
            "| Probability Bin | Count | Mean Predicted P(start) | Empirical Start Rate | Calibration Error |",
            "|---|---|---|---|---|",
        ])
        for b in start_buckets:
            b_range = f"[{b['bin_min']:.1f}, {b['bin_max']:.1f})"
            lines.append(
                f"| `{b_range}` | {b['count']:,} | {b['mean_predicted']:.3f} | {b['empirical_rate']:.3f} | **{b['calibration_error']:.3f}** |"
            )

    lines.extend([
        "",
        "---",
        "",
        "## 4. V0.9 9-Class Residual Error Taxonomy Decomposition",
        "",
        "| Residual Classification | Count | % of Errors | % of All Obs | Mean Min Error | MAE (mins) | Total Penalty (pts) | Mean Penalty / Case |",
        "|---|---|---|---|---|---|---|---|",
    ])

    for taxon in V09_ERROR_TAXONOMY:
        t_data = summary.get("residual_taxonomy", {}).get(taxon, {})
        cnt = t_data.get("count", 0)
        pct_err = t_data.get("pct_of_errors", 0.0)
        pct_tot = t_data.get("pct_of_total", 0.0)
        m_err = t_data.get("mean_minute_error", 0.0)
        mae_m = t_data.get("mae_minutes", 0.0)
        pen = t_data.get("total_penalty", 0.0)
        m_pen = t_data.get("mean_penalty", 0.0)
        lines.append(
            f"| `{taxon}` | {cnt:,} | **{pct_err:.1f}%** | {pct_tot:.1f}% | {m_err:+.1f} | {mae_m:.1f} | {pen:.1f} | {m_pen:.2f} |"
        )

    top_culprits = summary.get("top_culprits", [])
    if top_culprits:
        lines.extend([
            "",
            "---",
            "",
            "## 5. Top False Positive Culprits (High Projected xP with 0 Minutes)",
            "",
            "| GW | Player | Pos | Price | Pred xP | Pred xM | Pred P(start) | Status | V0.9 Taxonomy | Penalty |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ])
        for c in top_culprits:
            gw_str = f"GW{c['gameweek']:02d}"
            p_price = f"£{c['price_tenths'] / 10.0:.1f}m"
            lines.append(
                f"| {gw_str} | **{c['web_name']}** | {c['position']} | {p_price} | "
                f"{c['predicted_xp']:.2f} | {c['predicted_xm']:.1f} | {c['p_start']:.2f} | "
                f"`{c['status']}` | `{c['residual_classification']}` | {c['penalty']:.1f} |"
            )

    lines.append("")
    return "\n".join(lines)


def export_residual_dataset_json(records: list[ResidualRecord], output_path: Path) -> Path:
    """Serialize residual observation records to JSON format for research downstream."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serializable = []
    for r in records:
        d = asdict(r)
        d["position"] = r.position.value
        serializable.append(d)

    output_path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output_path


def export_residual_dataset_csv(records: list[ResidualRecord], output_path: Path) -> Path:
    """Serialize residual observation records to CSV format for ML model training."""
    import csv

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        output_path.write_text("", encoding="utf-8")
        return output_path

    fieldnames = list(asdict(records[0]).keys())
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            d = asdict(r)
            d["position"] = r.position.value
            writer.writerow(d)
    return output_path


def run_residual_dataset_pipeline(
    season_dir: Path,
    start_gw: int = 1,
    end_gw: int = 38,
    predictor_version: str = "v0.8",
    export_path: Path | None = None,
    export_format: str = "json",
    save_report: bool = False,
    report_output_path: Path | None = None,
) -> tuple[dict[str, Any], list[ResidualRecord]]:
    """Execute the end-to-end V0.9 residual dataset extraction, classification, and diagnostics."""
    records = build_residual_dataset(
        season_dir=season_dir,
        start_gw=start_gw,
        end_gw=end_gw,
        predictor_version=predictor_version,
    )
    summary = diagnose_residual_dataset(records)

    season_name = season_dir.name
    gw_range = f"GW{start_gw}-{end_gw}"
    markdown_report = format_residual_dataset_report(summary, season=season_name, gameweek_range=gw_range)
    summary["markdown"] = markdown_report

    if export_path is not None:
        if export_format.lower() == "csv":
            saved_export = export_residual_dataset_csv(records, export_path)
        else:
            saved_export = export_residual_dataset_json(records, export_path)
        summary["saved_dataset_path"] = str(saved_export)

    if save_report:
        if report_output_path is None:
            from .reporting import build_backtest_report_path
            report_output_path = build_backtest_report_path(
                "residuals",
                season_name,
                f"gw{start_gw}_{end_gw}",
                predictor_version,
            )
        report_output_path.parent.mkdir(parents=True, exist_ok=True)
        report_output_path.write_text(markdown_report, encoding="utf-8")
        summary["saved_report_path"] = str(report_output_path)

    return summary, records
