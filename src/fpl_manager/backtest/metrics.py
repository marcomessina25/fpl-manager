"""Quantitative prediction evaluation metrics for xP, xM, and availability (V0.7.1)."""

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

from ..evaluation import mean_absolute_error, root_mean_squared_error, spearman_rank_correlation
from ..models import Position


@dataclass(frozen=True, slots=True)
class PredictionEvaluationRecord:
    """Individual player gameweek prediction paired with ground truth outcome."""
    season: str
    gameweek: int
    player_id: int
    web_name: str
    position: Position
    price_tenths: int
    predicted_xp: float
    actual_points: int
    predicted_minutes: float
    actual_minutes: int
    predicted_availability: float
    actual_availability: bool   # True if actual_minutes > 0


def _safe_mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def evaluate_predictions(records: list[PredictionEvaluationRecord]) -> dict[str, Any]:
    """Calculate comprehensive evaluation metrics across xP, xM, and availability."""
    if not records:
        return {"total_records": 0}

    pred_xp = [r.predicted_xp for r in records]
    act_pts = [float(r.actual_points) for r in records]
    pred_mins = [r.predicted_minutes for r in records]
    act_mins = [float(r.actual_minutes) for r in records]

    # Overall xP metrics
    xp_mae = mean_absolute_error(pred_xp, act_pts)
    xp_rmse = root_mean_squared_error(pred_xp, act_pts)
    xp_corr = spearman_rank_correlation(pred_xp, act_pts)
    xp_bias = round(_safe_mean([p - a for p, a in zip(pred_xp, act_pts)]), 3)

    # Active player xP metrics (players who actually played >0 minutes)
    active_records = [r for r in records if r.actual_minutes > 0]
    active_xp_mae = mean_absolute_error(
        [r.predicted_xp for r in active_records],
        [float(r.actual_points) for r in active_records],
    ) if active_records else 0.0
    active_xp_corr = spearman_rank_correlation(
        [r.predicted_xp for r in active_records],
        [float(r.actual_points) for r in active_records],
    ) if active_records else 0.0

    # Minutes metrics (xM)
    xm_mae = mean_absolute_error(pred_mins, act_mins)
    xm_rmse = root_mean_squared_error(pred_mins, act_mins)
    xm_bias = round(_safe_mean([p - a for p, a in zip(pred_mins, act_mins)]), 3)

    # Minutes calibration by bucket: 0-15, 16-30, 31-60, 61-75, 76-90
    mins_buckets = {
        "0-15": [r for r in records if r.predicted_minutes <= 15.0],
        "16-30": [r for r in records if 15.0 < r.predicted_minutes <= 30.0],
        "31-60": [r for r in records if 30.0 < r.predicted_minutes <= 60.0],
        "61-75": [r for r in records if 60.0 < r.predicted_minutes <= 75.0],
        "76-90": [r for r in records if r.predicted_minutes > 75.0],
    }
    mins_calibration = {}
    for bucket_name, bucket_records in mins_buckets.items():
        if bucket_records:
            b_pred = [r.predicted_minutes for r in bucket_records]
            b_act = [float(r.actual_minutes) for r in bucket_records]
            mins_calibration[bucket_name] = {
                "count": len(bucket_records),
                "mean_predicted": _safe_mean(b_pred),
                "mean_actual": _safe_mean(b_act),
                "mae": mean_absolute_error(b_pred, b_act),
            }
        else:
            mins_calibration[bucket_name] = {"count": 0, "mean_predicted": 0.0, "mean_actual": 0.0, "mae": 0.0}

    # Availability metrics
    # Classification: positive if predicted_availability >= 0.50, negative if < 0.50
    tp = sum(1 for r in records if r.predicted_availability >= 0.50 and r.actual_availability)
    fp = sum(1 for r in records if r.predicted_availability >= 0.50 and not r.actual_availability)
    tn = sum(1 for r in records if r.predicted_availability < 0.50 and not r.actual_availability)
    fn = sum(1 for r in records if r.predicted_availability < 0.50 and r.actual_availability)

    total_avail = len(records)
    avail_accuracy = round((tp + tn) / total_avail, 4) if total_avail > 0 else 0.0
    avail_precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
    avail_recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0

    # Metrics by position
    by_position = {}
    for pos in Position:
        pos_records = [r for r in records if r.position == pos]
        if pos_records:
            p_pred = [r.predicted_xp for r in pos_records]
            p_act = [float(r.actual_points) for r in pos_records]
            by_position[pos.name] = {
                "count": len(pos_records),
                "xp_mae": mean_absolute_error(p_pred, p_act),
                "xp_rmse": root_mean_squared_error(p_pred, p_act),
                "xp_spearman": spearman_rank_correlation(p_pred, p_act),
                "mean_predicted": _safe_mean(p_pred),
                "mean_actual": _safe_mean(p_act),
            }

    # Metrics by price tier
    price_tiers = {
        "budget (<=5.0m)": [r for r in records if r.price_tenths <= 50],
        "mid-price (5.1-8.0m)": [r for r in records if 50 < r.price_tenths <= 80],
        "premium (>8.0m)": [r for r in records if r.price_tenths > 80],
    }
    by_price_tier = {}
    for tier_name, tier_records in price_tiers.items():
        if tier_records:
            t_pred = [r.predicted_xp for r in tier_records]
            t_act = [float(r.actual_points) for r in tier_records]
            by_price_tier[tier_name] = {
                "count": len(tier_records),
                "xp_mae": mean_absolute_error(t_pred, t_act),
                "xp_rmse": root_mean_squared_error(t_pred, t_act),
                "xp_spearman": spearman_rank_correlation(t_pred, t_act),
            }

    return {
        "total_records": len(records),
        "xp": {
            "overall_mae": xp_mae,
            "overall_rmse": xp_rmse,
            "spearman_correlation": xp_corr,
            "bias": xp_bias,
            "active_players_mae": active_xp_mae,
            "active_players_spearman": active_xp_corr,
        },
        "xm": {
            "overall_mae": xm_mae,
            "overall_rmse": xm_rmse,
            "bias": xm_bias,
            "calibration_buckets": mins_calibration,
        },
        "availability": {
            "accuracy": avail_accuracy,
            "precision": avail_precision,
            "recall": avail_recall,
            "true_positives": tp,
            "false_positives": fp,
            "true_negatives": tn,
            "false_negatives": fn,
        },
        "by_position": by_position,
        "by_price_tier": by_price_tier,
    }


def run_prediction_backtest(
    season_dir: Path,
    start_gw: int = 1,
    end_gw: int = 38,
    save_report: bool = False,
    output_path: Path | None = None,
    predictor_version: str = "v0.8",
) -> tuple[dict[str, Any], list[PredictionEvaluationRecord]]:
    """Run point-in-time prediction backtesting across a range of gameweeks.
    
    Guarantees:
    - Zero future leakage: only data available prior to GW deadline is used for predictions.
    - Ground truth outcomes are only used for comparison metrics.
    """
    from ..historical.snapshots import build_historical_snapshot, load_gameweek_outcomes
    from ..historical.reconstruction import reconstruct_features_and_project

    all_records: list[PredictionEvaluationRecord] = []

    for gw in range(start_gw, end_gw + 1):
        snapshot = build_historical_snapshot(season_dir, gw)
        projections = reconstruct_features_and_project(snapshot, predictor_version=predictor_version)
        outcomes = load_gameweek_outcomes(season_dir, gw)

        proj_map = {p.player_id: p for p in projections}
        for pid, outcome in outcomes.items():
            proj = proj_map.get(pid)
            if proj is None:
                continue

            all_records.append(
                PredictionEvaluationRecord(
                    season=snapshot.season,
                    gameweek=gw,
                    player_id=pid,
                    web_name=proj.web_name,
                    position=proj.position,
                    price_tenths=proj.price_tenths,
                    predicted_xp=proj.expected_points,
                    actual_points=outcome.total_points,
                    predicted_minutes=proj.expected_minutes,
                    actual_minutes=outcome.minutes,
                    predicted_availability=round(proj.play_probability, 2) if hasattr(proj, "play_probability") else round(proj.availability_pct / 100.0, 2),
                    actual_availability=(outcome.minutes > 0),
                )
            )

    results = evaluate_predictions(all_records)
    results["predictor_version"] = predictor_version
    if save_report:
        from .reporting import build_backtest_report_path, format_prediction_report, save_backtest_report

        season_name = season_dir.name
        report_text = format_prediction_report(results, season=season_name, gameweek_range=f"{start_gw}-{end_gw}")
        prefix = f"predictions_{predictor_version}" if predictor_version != "v0.7" else "predictions"
        target_path = output_path or build_backtest_report_path(prefix, season_name, start_gw, end_gw)
        save_backtest_report(report_text, target_path)
        results["saved_report_path"] = str(target_path)

    return results, all_records

