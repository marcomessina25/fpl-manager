"""P6 — Freeze the Model and Run the Final 2025/26 Evaluation.

Produces machine-readable artifact: reports/v09_final_2025_26_evaluation.json
Comparing frozen V0.8 baseline vs final frozen V0.9 across all required dimensions.
"""

import json
from pathlib import Path
import math
import time

from fpl_manager.historical.snapshots import build_historical_snapshot, load_gameweek_outcomes
from fpl_manager.historical.reconstruction import reconstruct_features_and_project
from fpl_manager.evaluation import (
    mean_absolute_error,
    root_mean_squared_error,
    spearman_rank_correlation,
)
from fpl_manager.calibration import compute_reliability_curve
from fpl_manager.backtest.engine import run_decision_backtest

HISTORICAL_2025_26 = Path("data/historical/2025-26")
OUTPUT_PATH = Path("reports/v09_final_2025_26_evaluation.json")


def run_final_evaluation():
    print("=======================================================")
    print("Running P6 Final Evaluation on 2025-26 Season (GW 1-38)")
    print("=======================================================")
    
    t0 = time.time()
    
    # 1. Predictive Accuracy (Participation & Expected Points)
    obs_v08 = []
    obs_v09 = []
    
    for gw in range(1, 39):
        snap = build_historical_snapshot(HISTORICAL_2025_26, gw)
        if not snap or not snap.players:
            continue
        outs = load_gameweek_outcomes(HISTORICAL_2025_26, gw)
        if not outs:
            continue
            
        projs_08 = reconstruct_features_and_project(snap, predictor_version="v0.8")
        projs_09 = reconstruct_features_and_project(snap, predictor_version="v0.9")
        
        m_08 = {p.player_id: p for p in projs_08}
        m_09 = {p.player_id: p for p in projs_09}
        
        for pid, out in outs.items():
            if pid not in m_08 or pid not in m_09:
                continue
            act_pts = float(out.total_points)
            act_mins = float(out.minutes)
            act_started = int(out.starts > 0)
            act_played = int(act_mins > 0)
            act_sub = int(act_played and not act_started)
            
            p08 = m_08[pid]
            p09 = m_09[pid]
            
            obs_v08.append({
                "act_pts": act_pts, "act_mins": act_mins, "act_started": act_started, "act_played": act_played,
                "pred_xp": p08.expected_points, "pred_xm": p08.expected_minutes,
                "p_start": p08.start_probability, "p_play": p08.play_probability,
            })
            obs_v09.append({
                "act_pts": act_pts, "act_mins": act_mins, "act_started": act_started, "act_played": act_played, "act_sub": act_sub,
                "pred_xp": p09.expected_points, "pred_xm": p09.expected_minutes,
                "p_start": p09.start_probability, "p_sub": p09.sub_probability, "p_play": p09.play_probability,
            })
            
    n_obs = len(obs_v08)
    print(f"Evaluated {n_obs} player-gameweeks across 38 gameweeks.")
    
    def calc_metrics(preds, acts):
        errs = [p - a for p, a in zip(preds, acts)]
        mae = sum(abs(e) for e in errs) / len(errs)
        rmse = math.sqrt(sum(e**2 for e in errs) / len(errs))
        bias = sum(errs) / len(errs)
        return round(mae, 3), round(rmse, 3), round(bias, 3)

    # Expected Points Metrics
    v08_xp_mae, v08_xp_rmse, v08_xp_bias = calc_metrics([o["pred_xp"] for o in obs_v08], [o["act_pts"] for o in obs_v08])
    v09_xp_mae, v09_xp_rmse, v09_xp_bias = calc_metrics([o["pred_xp"] for o in obs_v09], [o["act_pts"] for o in obs_v09])
    v08_spearman = round(spearman_rank_correlation([o["pred_xp"] for o in obs_v08], [o["act_pts"] for o in obs_v08]), 4)
    v09_spearman = round(spearman_rank_correlation([o["pred_xp"] for o in obs_v09], [o["act_pts"] for o in obs_v09]), 4)

    # Expected Minutes Metrics
    v08_xm_mae, v08_xm_rmse, v08_xm_bias = calc_metrics([o["pred_xm"] for o in obs_v08], [o["act_mins"] for o in obs_v08])
    v09_xm_mae, v09_xm_rmse, v09_xm_bias = calc_metrics([o["pred_xm"] for o in obs_v09], [o["act_mins"] for o in obs_v09])

    # Participation Classification & Availability
    def calc_avail(obs_list):
        fp = sum(1 for o in obs_list if o["pred_xm"] >= 15.0 and o["act_mins"] == 0)
        fn = sum(1 for o in obs_list if o["pred_xm"] < 15.0 and o["act_mins"] >= 60)
        tp = sum(1 for o in obs_list if o["pred_xm"] >= 15.0 and o["act_mins"] > 0)
        prec = round(tp / max(1, tp + fp), 4)
        rec = round(tp / max(1, sum(1 for o in obs_list if o["act_mins"] > 0)), 4)
        return fp, fn, prec, rec

    v08_fp, v08_fn, v08_prec, v08_rec = calc_avail(obs_v08)
    v09_fp, v09_fn, v09_prec, v09_rec = calc_avail(obs_v09)

    # Calibration Reliability Curves
    act_starts = [o["act_started"] for o in obs_v09]
    act_plays = [o["act_played"] for o in obs_v09]
    rel_start_08 = compute_reliability_curve([o["p_start"] for o in obs_v08], act_starts, n_bins=10)
    rel_start_09 = compute_reliability_curve([o["p_start"] for o in obs_v09], act_starts, n_bins=10)
    rel_play_09 = compute_reliability_curve([o["p_play"] for o in obs_v09], act_plays, n_bins=10)

    # Breakdown by minute bucket
    buckets = [
        ("0-15 mins", 0.0, 15.0),
        ("16-30 mins", 16.0, 30.0),
        ("31-60 mins", 31.0, 60.0),
        ("61-75 mins", 61.0, 75.0),
        ("76-90 mins", 76.0, 90.0),
    ]
    bucket_breakdown = {}
    for b_name, b_low, b_high in buckets:
        sub_08 = [o for o in obs_v08 if b_low <= o["pred_xm"] <= b_high]
        sub_09 = [o for o in obs_v09 if b_low <= o["pred_xm"] <= b_high]
        m08 = calc_metrics([o["pred_xm"] for o in sub_08], [o["act_mins"] for o in sub_08]) if sub_08 else (0,0,0)
        m09 = calc_metrics([o["pred_xm"] for o in sub_09], [o["act_mins"] for o in sub_09]) if sub_09 else (0,0,0)
        z09 = sum(1 for o in sub_09 if o["act_mins"] == 0)
        bucket_breakdown[b_name] = {
            "v08": {"count": len(sub_08), "mae": m08[0], "bias": m08[2]},
            "v09": {"count": len(sub_09), "mae": m09[0], "bias": m09[2], "zero_min_pct": round(z09/max(1, len(sub_09))*100, 1)},
        }

    # 2. Decision Simulation (V0.8 baseline vs V0.9 candidate)
    print("\nRunning V0.8 Decision Simulation...")
    v08_sims = run_decision_backtest(
        season_dir=HISTORICAL_2025_26,
        strategy="all",
        start_gw=1,
        end_gw=38,
        predictor_version="v0.8",
        decision_engine="v0.8",
        save_report=False,
    )
    v08_decisions = {s.strategy_name: s for s in v08_sims}

    print("\nRunning V0.9 Decision Simulation...")
    v09_sims = run_decision_backtest(
        season_dir=HISTORICAL_2025_26,
        strategy="all",
        start_gw=1,
        end_gw=38,
        predictor_version="v0.9",
        decision_engine="v0.9",
        save_report=False,
    )
    v09_decisions = {s.strategy_name: s for s in v09_sims}

    # Assemble complete report
    def sim_to_dict(s):
        return {
            "net_points": s.total_net_points,
            "gross_points": s.total_gross_points,
            "hits": s.total_hits,
            "transfers": s.total_transfers,
            "zero_min_starters": s.total_zero_min_starters,
            "captain_zero_mins": s.captain_zero_min_count,
            "bench_regret": s.total_bench_regret_points,
            "transfer_gain": s.total_transfer_net_gain,
        }

    duration = round(time.time() - t0, 1)

    report = {
        "season": "2025-26",
        "gameweeks": "1-38",
        "sample_count": n_obs,
        "duration_seconds": duration,
        "metrics": {
            "expected_points": {
                "v08": {"mae": v08_xp_mae, "rmse": v08_xp_rmse, "spearman": v08_spearman, "bias": v08_xp_bias},
                "v09": {"mae": v09_xp_mae, "rmse": v09_xp_rmse, "spearman": v09_spearman, "bias": v09_xp_bias},
                "delta": {
                    "mae": round(v09_xp_mae - v08_xp_mae, 3),
                    "spearman": round(v09_spearman - v08_spearman, 4),
                },
            },
            "expected_minutes": {
                "v08": {"mae": v08_xm_mae, "rmse": v08_xm_rmse, "bias": v08_xm_bias},
                "v09": {"mae": v09_xm_mae, "rmse": v09_xm_rmse, "bias": v09_xm_bias},
                "delta": {"mae": round(v09_xm_mae - v08_xm_mae, 3), "bias": round(v09_xm_bias - v08_xm_bias, 3)},
            },
            "availability": {
                "v08": {"precision": v08_prec, "recall": v08_rec, "false_positives": v08_fp, "false_negatives": v08_fn},
                "v09": {"precision": v09_prec, "recall": v09_rec, "false_positives": v09_fp, "false_negatives": v09_fn},
            },
            "calibration": {
                "p_start_v08": {"ece": rel_start_08.expected_calibration_error, "brier": rel_start_08.brier_score},
                "p_start_v09": {"ece": rel_start_09.expected_calibration_error, "brier": rel_start_09.brier_score},
                "p_play_v09": {"ece": rel_play_09.expected_calibration_error, "brier": rel_play_09.brier_score},
            },
            "by_minute_bucket": bucket_breakdown,
            "decision_simulation": {
                "v08_frozen_baseline": {name: sim_to_dict(s) for name, s in v08_decisions.items()},
                "v09_candidate": {name: sim_to_dict(s) for name, s in v09_decisions.items()},
            },
        },
        "verdict": "P6 Final Evaluation completed successfully.",
    }

    opt_08 = next((s for s in v08_sims if "optimizer" in s.strategy_name.lower()), v08_sims[-1])
    opt_09 = next((s for s in v09_sims if "optimizer" in s.strategy_name.lower()), v09_sims[-1])

    report["metrics"]["decision_simulation"]["optimizer_delta_net_points"] = opt_09.total_net_points - opt_08.total_net_points
    report["metrics"]["decision_simulation"]["optimizer_delta_zero_min_starters"] = opt_09.total_zero_min_starters - opt_08.total_zero_min_starters

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nSaved final evaluation report to {OUTPUT_PATH}")

    print(f"\n=======================================================")
    print(f"P6 Evaluation Summary:")
    print(f"  Optimizer Net Points: V0.8={opt_08.total_net_points} vs V0.9={opt_09.total_net_points} (Delta: {opt_09.total_net_points - opt_08.total_net_points:+d} pts)")
    print(f"  0-Min Starters:       V0.8={opt_08.total_zero_min_starters} vs V0.9={opt_09.total_zero_min_starters}")
    print(f"  xM MAE:               V0.8={v08_xm_mae} vs V0.9={v09_xm_mae}")
    print(f"  xP Spearman:          V0.8={v08_spearman} vs V0.9={v09_spearman}")
    print(f"=======================================================")


if __name__ == "__main__":
    run_final_evaluation()
