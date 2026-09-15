"""Experimental script to test and compare state-based participation models (P4)."""
import json
from pathlib import Path
from collections import defaultdict
import math

from fpl_manager.historical.snapshots import build_historical_snapshot, load_gameweek_outcomes
from fpl_manager.historical.reconstruction import reconstruct_features_and_project
from fpl_manager.evaluation import mean_absolute_error, root_mean_squared_error
from fpl_manager.calibration import compute_brier_score, compute_log_loss, compute_reliability_curve
from fpl_manager.learned_participation import (
    HierarchicalParticipationModel,
    predict_player_participation_v09,
)

def evaluate_season_participation(season_dir: Path, end_gw: int = 38):
    """Evaluate V0.8 and V0.9 across season gameweeks."""
    print(f"Evaluating {season_dir.name} up to GW {end_gw}...")
    
    # Store observations:
    # act_mins, act_started, act_sub, act_played
    data = []
    
    for gw in range(1, end_gw + 1):
        snapshot = build_historical_snapshot(season_dir, gw)
        if snapshot is None or not snapshot.players:
            continue
        outcomes = load_gameweek_outcomes(season_dir, gw)
        if not outcomes:
            continue
            
        projs_v08 = reconstruct_features_and_project(snapshot, predictor_version="v0.8")
        projs_v09 = reconstruct_features_and_project(snapshot, predictor_version="v0.9")
        projs_v09_uncal = reconstruct_features_and_project(snapshot, predictor_version="v0.9_no_calib")
        
        map_08 = {p.player_id: p for p in projs_v08}
        map_09 = {p.player_id: p for p in projs_v09}
        map_09_uncal = {p.player_id: p for p in projs_v09_uncal}
        
        for pid, out in outcomes.items():
            if pid not in map_08 or pid not in map_09:
                continue
            act_mins = float(out.minutes)
            act_started = int(out.starts > 0)
            act_played = int(act_mins > 0)
            act_sub = int(act_played and not act_started)
            
            p08 = map_08[pid]
            p09 = map_09[pid]
            p09_u = map_09_uncal.get(pid, p09)
            
            data.append({
                "pid": pid,
                "gw": gw,
                "pos": p08.position.name,
                "price": p08.price_tenths,
                "act_mins": act_mins,
                "act_started": act_started,
                "act_sub": act_sub,
                "act_played": act_played,
                
                # V0.8
                "v08_xm": p08.expected_minutes,
                "v08_p_start": p08.start_probability,
                "v08_p_play": p08.play_probability,
                
                # V0.9 Calibrated
                "v09_xm": p09.expected_minutes,
                "v09_p_start": p09.start_probability,
                "v09_p_sub": p09.sub_probability,
                "v09_p_play": p09.play_probability,
                
                # V0.9 Uncalibrated
                "v09_u_xm": p09_u.expected_minutes,
                "v09_u_p_start": p09_u.start_probability,
                "v09_u_p_sub": p09_u.sub_probability,
                "v09_u_p_play": p09_u.play_probability,
            })
            
    print(f"Loaded {len(data)} observations.")
    
    # Calculate baseline metrics for V0.8
    v08_xm_errors = [d["v08_xm"] - d["act_mins"] for d in data]
    v08_mae = sum(abs(e) for e in v08_xm_errors) / len(data)
    v08_rmse = math.sqrt(sum(e**2 for e in v08_xm_errors) / len(data))
    v08_bias = sum(v08_xm_errors) / len(data)
    
    # Calculate baseline metrics for current V0.9
    v09_xm_errors = [d["v09_xm"] - d["act_mins"] for d in data]
    v09_mae = sum(abs(e) for e in v09_xm_errors) / len(data)
    v09_rmse = math.sqrt(sum(e**2 for e in v09_xm_errors) / len(data))
    v09_bias = sum(v09_xm_errors) / len(data)
    
    # Calculate baseline metrics for V0.9 Uncalibrated
    v09_u_xm_errors = [d["v09_u_xm"] - d["act_mins"] for d in data]
    v09_u_mae = sum(abs(e) for e in v09_u_xm_errors) / len(data)
    v09_u_rmse = math.sqrt(sum(e**2 for e in v09_u_xm_errors) / len(data))
    v09_u_bias = sum(v09_u_xm_errors) / len(data)
    
    print(f"\n--- Baseline Participation Comparison ({season_dir.name}) ---")
    print(f"V0.8:           xM MAE={v08_mae:.3f}, RMSE={v08_rmse:.3f}, Bias={v08_bias:.3f}")
    print(f"V0.9 Calib:     xM MAE={v09_mae:.3f}, RMSE={v09_rmse:.3f}, Bias={v09_bias:.3f}")
    print(f"V0.9 Uncalib:   xM MAE={v09_u_mae:.3f}, RMSE={v09_u_rmse:.3f}, Bias={v09_u_bias:.3f}")
    
    # Compare candidate model
    sub_mins_map = {"GOALKEEPER": 20.0, "DEFENDER": 18.9, "MIDFIELDER": 18.1, "FORWARD": 17.0}
    start_mins_map = {"GOALKEEPER": 89.4, "DEFENDER": 85.3, "MIDFIELDER": 80.0, "FORWARD": 79.4}
    
    cand_p_starts = []
    cand_xm_errors = []
    for d in data:
        pos = d["pos"]
        # Cap start probability at realistic ceiling: 0.95 for GKP, 0.90 for outfield
        ceil = 0.95 if pos == "GOALKEEPER" else 0.90
        p_start = min(ceil, d["v09_p_start"])
        p_sub = d["v09_p_sub"]
        
        # Threshold deep bench substitutes
        if p_start < 0.15 and p_sub < 0.35:
            p_sub = 0.0
            
        mins_start = start_mins_map.get(pos, 82.0)
        mins_sub = sub_mins_map.get(pos, 18.0)
        
        cand_xm = round(p_start * mins_start + p_sub * mins_sub, 1)
        cand_xm_errors.append(cand_xm - d["act_mins"])
        cand_p_starts.append(p_start)
        
    c_mae = sum(abs(e) for e in cand_xm_errors) / len(data)
    c_rmse = math.sqrt(sum(e**2 for e in cand_xm_errors) / len(data))
    c_bias = sum(c_errors) / len(data) if 'c_errors' in locals() else sum(cand_xm_errors) / len(data)
    
    act_starts = [d["act_started"] for d in data]
    p_starts_u = [d["v09_u_p_start"] for d in data]
    rel_u = compute_reliability_curve(p_starts_u, act_starts, n_bins=10)
    print(f"\n--- Uncalibrated Reliability Diagram for V0.9 P(start) ---")
    print(f"ECE={rel_u.expected_calibration_error:.4f}, MCE={rel_u.maximum_calibration_error:.4f}, Brier={rel_u.brier_score:.4f}")
    for b in rel_u.buckets:
        if b.count > 0:
            print(f"  Bin [{b.bin_min:.1f}, {b.bin_max:.1f}]: count={b.count}, mean_pred={b.mean_predicted:.3f}, emp_rate={b.empirical_rate:.3f}, gap={b.mean_predicted - b.empirical_rate:+.3f}")

    print(f"\n--- Candidate State-Based Model (2024-25) ---")
    print(f"xM MAE={c_mae:.3f}, RMSE={c_rmse:.3f}, Bias={c_bias:.3f}")
    
    rel_cand = compute_reliability_curve(cand_p_starts, act_starts, n_bins=10)
    print(f"ECE={rel_cand.expected_calibration_error:.4f}, MCE={rel_cand.maximum_calibration_error:.4f}, Brier={rel_cand.brier_score:.4f}")
    for b in rel_cand.buckets:
        if b.count > 0:
            print(f"  Bin [{b.bin_min:.1f}, {b.bin_max:.1f}]: count={b.count}, mean_pred={b.mean_predicted:.3f}, emp_rate={b.empirical_rate:.3f}, gap={b.mean_predicted - b.empirical_rate:+.3f}")


if __name__ == "__main__":
    evaluate_season_participation(Path("data/historical/2024-25"), end_gw=15)
