"""Run genuine 2x2 Four-Way Ablation across 2025-26 Season (P0).

Cells:
- A: V0.8 Predictor + V0.8 Decision Engine
- B: V0.9 Predictor + V0.8 Decision Engine
- C: V0.8 Predictor + V0.9 Decision Engine
- D: V0.9 Predictor + V0.9 Decision Engine
"""

import json
from pathlib import Path
import time

from fpl_manager.backtest.engine import run_decision_backtest

HISTORICAL_2025_26 = Path("data/historical/2025-26")
OUTPUT_PATH = Path("reports/v09_four_way_ablation_matrix.json")


def evaluate_cell(cell_name: str, pred_ver: str, engine_ver: str) -> dict:
    print(f"\n==========================================")
    print(f"Evaluating Cell {cell_name}: Pred={pred_ver}, Engine={engine_ver}")
    print(f"==========================================")
    t0 = time.time()
    sims = run_decision_backtest(
        season_dir=HISTORICAL_2025_26,
        strategy="all",
        start_gw=1,
        end_gw=38,
        predictor_version=pred_ver,
        decision_engine=engine_ver,
        save_report=False,
    )
    duration = round(time.time() - t0, 2)
    print(f"Cell {cell_name} completed in {duration}s")

    cell_results = {
        "cell": cell_name,
        "predictor_version": pred_ver,
        "decision_engine_version": engine_ver,
        "duration_seconds": duration,
        "strategies": {},
    }
    for s in sims:
        cell_results["strategies"][s.strategy_name] = {
            "net_points": s.total_net_points,
            "gross_points": s.total_gross_points,
            "hits": s.total_hits,
            "transfers": s.total_transfers,
            "zero_min_starters": s.total_zero_min_starters,
            "captain_zero_mins": s.captain_zero_min_count,
            "bench_regret": s.total_bench_regret_points,
            "transfer_gross_gain": s.total_transfer_gross_gain,
            "transfer_net_gain": s.total_transfer_net_gain,
            "final_bank_tenths": s.final_bank_tenths,
            "optimizer_implementation": s.optimizer_implementation,
            "optimizer_config": s.optimizer_config,
        }
        print(f"  [{s.strategy_name}] Net Pts: {s.total_net_points}, 0-min starters: {s.total_zero_min_starters}, 0-min caps: {s.captain_zero_min_count}")
    return cell_results


def main():
    matrix = {}
    matrix["A"] = evaluate_cell("A", pred_ver="v0.8", engine_ver="v0.8")
    matrix["B"] = evaluate_cell("B", pred_ver="v0.9", engine_ver="v0.8")
    matrix["C"] = evaluate_cell("C", pred_ver="v0.8", engine_ver="v0.9")
    matrix["D"] = evaluate_cell("D", pred_ver="v0.9", engine_ver="v0.9")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nSaved four-way ablation matrix to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
