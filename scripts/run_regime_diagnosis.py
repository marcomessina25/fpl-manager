"""Diagnose role regime performance across seasons and save report."""
import json
from pathlib import Path
from fpl_manager.regimes import diagnose_regime_performance

def main():
    season_dir = Path("data/historical/2025-26")
    print(f"Running regime diagnosis on {season_dir}...")
    metrics = diagnose_regime_performance(season_dir, start_gw=1, end_gw=28, predictor_version="v0.9")
    
    out_file = Path("reports/v09_regime_performance.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"Saved {out_file}")
    
    print("\nRegime Performance Summary:")
    for reg, stats in metrics.get("by_regime", {}).items():
        print(f"  {reg}: obs={stats['count']}, mean_pred_xm={stats['mean_predicted_xm']}, mean_act_mins={stats['mean_actual_xm']}, MAE={stats['xm_mae']}, bias={stats['xm_bias']}, zero_min_rate={stats['zero_min_rate']}, status={stats['calibration_status']}")

if __name__ == "__main__":
    main()
