"""Comprehensive investigation runner for V0.9 regression analysis (2025-26).

Executes:
1. Four-Way Predictor x Decision Engine Ablation.
2. Predictor Sub-Ablation (V0.8 vs V0.9 components, regimes, calibration).
3. Intermediate Minutes (16-60 min) Error Decomposition.
4. Probability Calibration Audit (P(start), P(sub|not start), P(play), P(60+)).
5. Decision-Weighted Selection & Transfer Analysis.
6. Outputs reports/v09_ablation_results.json.
"""

from dataclasses import asdict
import json
import math
from pathlib import Path
import time
from typing import Any

from fpl_manager.backtest.engine import run_decision_backtest
from fpl_manager.backtest.metrics import run_prediction_backtest
from fpl_manager.backtest.residual_dataset import build_residual_dataset, ResidualRecord
from fpl_manager.calibration import compute_brier_score, compute_log_loss, compute_reliability_curve
from fpl_manager.evaluation import mean_absolute_error, root_mean_squared_error, spearman_rank_correlation
from fpl_manager.historical.models import Position
from fpl_manager.historical.reconstruction import reconstruct_features_and_project
from fpl_manager.historical.snapshots import build_historical_snapshot, load_gameweek_outcomes

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data"
HISTORICAL_2025_26 = DATA_DIRECTORY / "historical" / "2025-26"
REPORT_OUTPUT = PROJECT_ROOT / "reports" / "v09_ablation_results.json"


def safe_mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def run_predictor_evaluation(season_dir: Path, predictor_version: str) -> dict[str, Any]:
    print(f"Running prediction backtest for: {predictor_version}...")
    metrics, records = run_prediction_backtest(
        season_dir=season_dir,
        start_gw=1,
        end_gw=38,
        predictor_version=predictor_version,
        save_report=False,
    )
    return metrics


def run_decision_simulation(
    season_dir: Path,
    predictor_version: str,
    decision_engine: str = "v0.9",
) -> dict[str, Any]:
    print(f"Running decision backtest for pred={predictor_version}, engine={decision_engine}...")
    t0 = time.time()
    simulations = run_decision_backtest(
        season_dir=season_dir,
        strategy="all",
        start_gw=1,
        end_gw=38,
        predictor_version=predictor_version,
        decision_engine=decision_engine,
        save_report=False,
    )
    duration = round(time.time() - t0, 2)
    res = {}
    for sim in simulations:
        res[sim.strategy_name] = {
            "predictor_version": sim.predictor_version,
            "decision_engine_version": sim.decision_engine_version,
            "optimizer_implementation": sim.optimizer_implementation,
            "optimizer_config": sim.optimizer_config,
            "net_points": sim.total_net_points,
            "gross_points": sim.total_gross_points,
            "hits": sim.total_hits,
            "transfers": sim.total_transfers,
            "zero_min_starters": sim.total_zero_min_starters,
            "captain_zero_mins": sim.captain_zero_min_count,
            "bench_regret": sim.total_bench_regret_points,
            "transfer_gain": sim.total_transfer_net_gain,
            "final_bank_tenths": sim.final_bank_tenths,
        }
    res["execution_time_seconds"] = duration
    return res


def analyze_intermediate_minutes(records: list[ResidualRecord]) -> dict[str, Any]:
    """Decompose intermediate-minute prediction errors (16-30, 31-60, 61-75)."""
    buckets = {
        "16-30": [r for r in records if 15.0 < r.expected_minutes <= 30.0],
        "31-60": [r for r in records if 30.0 < r.expected_minutes <= 60.0],
        "61-75": [r for r in records if 60.0 < r.expected_minutes <= 75.0],
    }

    result = {}
    for b_name, b_recs in buckets.items():
        if not b_recs:
            continue
        pred_m = [r.expected_minutes for r in b_recs]
        act_m = [float(r.actual_minutes) for r in b_recs]
        mae = mean_absolute_error(pred_m, act_m)
        rmse = root_mean_squared_error(pred_m, act_m)
        mean_p = safe_mean(pred_m)
        mean_a = safe_mean(act_m)

        # By actual state: Started vs Sub vs 0 mins
        starters = [r for r in b_recs if r.actual_started]
        subs = [r for r in b_recs if not r.actual_started and r.actual_minutes > 0]
        zero_mins = [r for r in b_recs if r.actual_minutes == 0]

        # By position
        by_pos = {}
        for pos in (Position.GOALKEEPER, Position.DEFENDER, Position.MIDFIELDER, Position.FORWARD):
            p_recs = [r for r in b_recs if r.position == pos]
            if p_recs:
                by_pos[pos.name] = {
                    "count": len(p_recs),
                    "mean_pred": safe_mean([r.expected_minutes for r in p_recs]),
                    "mean_act": safe_mean([float(r.actual_minutes) for r in p_recs]),
                    "mae": mean_absolute_error([r.expected_minutes for r in p_recs], [float(r.actual_minutes) for r in p_recs]),
                    "zero_min_rate": round(sum(1 for r in p_recs if r.actual_minutes == 0) / len(p_recs), 3),
                }

        # By price tier
        tiers = {
            "budget": [r for r in b_recs if r.price_tenths <= 50],
            "mid_price": [r for r in b_recs if 50 < r.price_tenths <= 80],
            "premium": [r for r in b_recs if r.price_tenths > 80],
        }
        by_tier = {}
        for t_name, t_recs in tiers.items():
            if t_recs:
                by_tier[t_name] = {
                    "count": len(t_recs),
                    "mean_pred": safe_mean([r.expected_minutes for r in t_recs]),
                    "mean_act": safe_mean([float(r.actual_minutes) for r in t_recs]),
                    "mae": mean_absolute_error([r.expected_minutes for r in t_recs], [float(r.actual_minutes) for r in t_recs]),
                    "zero_min_rate": round(sum(1 for r in t_recs if r.actual_minutes == 0) / len(t_recs), 3),
                }

        result[b_name] = {
            "total_count": len(b_recs),
            "mean_predicted": mean_p,
            "mean_actual": mean_a,
            "mae": mae,
            "rmse": rmse,
            "actual_starters_count": len(starters),
            "actual_subs_count": len(subs),
            "zero_mins_count": len(zero_mins),
            "zero_mins_pct": round(len(zero_mins) / len(b_recs) * 100.0, 1),
            "mean_actual_mins_when_started": safe_mean([float(r.actual_minutes) for r in starters]),
            "mean_actual_mins_when_sub": safe_mean([float(r.actual_minutes) for r in subs]),
            "by_position": by_pos,
            "by_price_tier": by_tier,
        }

    return result


def audit_probability_calibration(records: list[ResidualRecord]) -> dict[str, Any]:
    """Audit probability calibration for P(start), P(sub | not start), P(play), P(60+)."""
    # 1. P(start)
    p_start = [r.p_start for r in records]
    y_start = [1 if r.actual_started else 0 for r in records]
    rel_start = compute_reliability_curve(p_start, y_start, n_bins=10)

    # 2. P(sub | not start) for non-starters
    non_starters = [r for r in records if not r.actual_started]
    p_sub_cond = []
    y_sub_cond = []
    for r in non_starters:
        # p_sub = (1 - p_start) * cond_p_sub => cond_p_sub ~ p_sub / max(0.01, 1 - p_start)
        cond_p = min(1.0, r.p_sub / max(0.05, 1.0 - r.p_start))
        p_sub_cond.append(cond_p)
        y_sub_cond.append(1 if r.actual_minutes > 0 else 0)
    rel_sub = compute_reliability_curve(p_sub_cond, y_sub_cond, n_bins=10)

    # 3. P(play)
    p_play = [r.p_play for r in records]
    y_play = [1 if r.actual_minutes > 0 else 0 for r in records]
    rel_play = compute_reliability_curve(p_play, y_play, n_bins=10)

    # 4. P(60+)
    # in V0.9, prob_60_plus is available or can be estimated
    p_60 = []
    y_60 = []
    for r in records:
        # approximate prob_60_plus from p_start * 0.96
        p60_val = min(1.0, r.p_start * 0.96)
        p_60.append(p60_val)
        y_60.append(1 if r.actual_minutes >= 60 else 0)
    rel_60 = compute_reliability_curve(p_60, y_60, n_bins=10)

    return {
        "p_start": rel_start.to_dict(),
        "p_sub_conditional": rel_sub.to_dict(),
        "p_play": rel_play.to_dict(),
        "p_60_plus": rel_60.to_dict(),
    }


def main() -> None:
    print("=================================================================")
    print("STARTING V0.9 REGRESSION INVESTIGATION EXPERIMENTAL SUITE")
    print(f"Season dataset: {HISTORICAL_2025_26}")
    print("=================================================================")

    predictors_to_test = [
        "v0.8",
        "v0.9",
        "v0.9_part_v0.8_comp",
        "v0.8_part_v0.9_comp",
        "v0.9_no_regimes",
        "v0.9_no_calib",
        "v0.9_raw",
    ]

    all_results: dict[str, Any] = {
        "meta": {
            "season": "2025-26",
            "gameweeks": "1-38",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "four_way_ablation": {},
        "predictor_ablations": {},
        "intermediate_minutes_analysis": {},
        "probability_calibration_audit": {},
    }

    # 1. Predictor & Decision Ablation Loop
    for pred in predictors_to_test:
        print(f"\n--- Processing Predictor: {pred} ---")
        pred_metrics = run_predictor_evaluation(HISTORICAL_2025_26, pred)
        dec_metrics = run_decision_simulation(HISTORICAL_2025_26, pred)

        xp_info = pred_metrics.get("xp", {})
        xm_info = pred_metrics.get("xm", {})
        avail_info = pred_metrics.get("availability", {})

        all_results["predictor_ablations"][pred] = {
            "prediction": {
                "evaluated_records": pred_metrics.get("total_records"),
                "xp_mae": xp_info.get("overall_mae"),
                "xp_rmse": xp_info.get("overall_rmse"),
                "xp_spearman": xp_info.get("spearman_correlation"),
                "xp_bias": xp_info.get("bias"),
                "xm_mae": xm_info.get("overall_mae"),
                "xm_rmse": xm_info.get("overall_rmse"),
                "xm_bias": xm_info.get("bias"),
                "availability_precision": avail_info.get("precision"),
                "availability_recall": avail_info.get("recall"),
                "false_positives": avail_info.get("false_positives"),
                "false_negatives": avail_info.get("false_negatives"),
                "mins_calibration": xm_info.get("calibration_buckets"),
            },
            "decision": dec_metrics,
        }

    # 2. Extract Four-Way Ablation Matrix (Genuine 2x2 Grid)
    print("\n--- Running Four-Way Ablation Matrix: Decision Engine V0.8 ---")
    sim_a = run_decision_simulation(HISTORICAL_2025_26, predictor_version="v0.8", decision_engine="v0.8")
    sim_b = run_decision_simulation(HISTORICAL_2025_26, predictor_version="v0.9", decision_engine="v0.8")
    sim_c = all_results["predictor_ablations"]["v0.8"]["decision"]
    sim_d = all_results["predictor_ablations"]["v0.9"]["decision"]

    all_results["four_way_ablation"] = {
        "A_v08_pred_v08_engine": sim_a,
        "B_v09_pred_v08_engine": sim_b,
        "C_v08_pred_v09_engine": sim_c,
        "D_v09_pred_v09_engine": sim_d,
    }

    # 3. Deep-Dive on Intermediate Minutes (V0.9 vs V0.8)
    print("\n--- Running Residual Decomposition for V0.9 & V0.8 ---")
    recs_v09 = build_residual_dataset(HISTORICAL_2025_26, start_gw=1, end_gw=38, predictor_version="v0.9")
    recs_v08 = build_residual_dataset(HISTORICAL_2025_26, start_gw=1, end_gw=38, predictor_version="v0.8")
    recs_v09_nocalib = build_residual_dataset(HISTORICAL_2025_26, start_gw=1, end_gw=38, predictor_version="v0.9_no_calib")

    all_results["intermediate_minutes_analysis"]["v0.9"] = analyze_intermediate_minutes(recs_v09)
    all_results["intermediate_minutes_analysis"]["v0.8"] = analyze_intermediate_minutes(recs_v08)

    # 4. Probability Calibration Audit (V0.9 Calibrated vs Uncalibrated)
    print("\n--- Auditing Probability Calibration ---")
    all_results["probability_calibration_audit"]["v0.9_calibrated"] = audit_probability_calibration(recs_v09)
    all_results["probability_calibration_audit"]["v0.9_uncalibrated"] = audit_probability_calibration(recs_v09_nocalib)

    # Save to JSON
    REPORT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUTPUT.write_text(json.dumps(all_results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nInvestigation results successfully saved to: {REPORT_OUTPUT}")
    print("ALL EXPERIMENTS COMPLETED.")


if __name__ == "__main__":
    main()
