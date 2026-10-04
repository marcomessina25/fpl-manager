"""Multi-Version Historical Benchmark Runner for V1.3.

Executes 5-season dual-track simulation across V0.9, V1.0, V1.1, V1.1.5, V1.2, V1.2.5, and V1.3.
"""

from datetime import datetime, timezone
from pathlib import Path
import time
from fpl_manager.backtest.strategic_analysis import run_version_comparison_backtest

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports" / "v13" / "multi_version_benchmark"


def main():
    print(f"Starting 5-Season Multi-Version Benchmark (V1.3) at {datetime.now(timezone.utc).isoformat()}...")
    t0 = time.time()
    results = run_version_comparison_backtest(
        seasons=("2021-22", "2022-23", "2023-24", "2024-25", "2025-26"),
        versions=("v0.9", "v1.0", "v1.1", "v1.1.5", "v1.2", "v1.2.5", "v1.3"),
        tracks=("track_a_no_chips", "track_b_with_chips"),
        start_gw=1,
        end_gw=38,
        smoke_test=False,
        save_report=True,
        output_dir=REPORTS_DIR,
        verbose=True,
    )
    elapsed = time.time() - t0
    print(f"\n==========================================")
    print(f"Benchmark completed successfully in {elapsed:.1f} seconds ({elapsed/60:.2f} minutes).")
    print(f"Report saved to: {results.get('report_path')}")
    print(f"==========================================\n")

    primary_aggregates = results.get("primary_walk_forward_aggregates", {})
    version_aggregates = results.get("version_aggregates", {})
    all_versions = ("v0.9", "v1.0", "v1.1", "v1.1.5", "v1.2", "v1.2.5", "v1.3")

    print("PRIMARY WALK-FORWARD AGGREGATES (4 Seasons: 2022-23 to 2025-26):")
    print("  Track A (No Chips):")
    for ver in all_versions:
        agg = primary_aggregates.get(ver, {}).get("track_a_no_chips", {})
        print(f"    {ver:7s}: {agg.get('mean_net_points', 0):.1f} pts (±{agg.get('std_net_points', 0):.1f})")

    print("\n  Track B (With Chips):")
    for ver in all_versions:
        agg = primary_aggregates.get(ver, {}).get("track_b_with_chips", {})
        c_gain = results.get("primary_chip_deltas", {}).get(ver, 0.0)
        print(f"    {ver:7s}: {agg.get('mean_net_points', 0):.1f} pts (±{agg.get('std_net_points', 0):.1f}) | Chip Delta: {c_gain:+.1f} pts")

    print("\nRETROSPECTIVE STRESS TEST (Season 2021-22):")
    s21 = results.get("season_ledgers", {}).get("2021-22", {})
    s21_a = s21.get("track_a_no_chips", {})
    s21_b = s21.get("track_b_with_chips", {})
    for ver in all_versions:
        ra = s21_a.get(ver, {}).get("total_net_points", "-")
        rb = s21_b.get(ver, {}).get("total_net_points", "-")
        print(f"    {ver:7s}: Track A = {ra} pts | Track B = {rb} pts")

    print("\nFULL 5-SEASON REFERENCE AGGREGATES (2021-22 to 2025-26):")
    print("  Track A (No Chips):")
    for ver in all_versions:
        agg = version_aggregates.get(ver, {}).get("track_a_no_chips", {})
        print(f"    {ver:7s}: {agg.get('mean_net_points', 0):.1f} pts (±{agg.get('std_net_points', 0):.1f})")

    print("\n  Track B (With Chips):")
    for ver in all_versions:
        agg = version_aggregates.get(ver, {}).get("track_b_with_chips", {})
        c_gain = results.get("chip_deltas", {}).get(ver, 0.0)
        print(f"    {ver:7s}: {agg.get('mean_net_points', 0):.1f} pts (±{agg.get('std_net_points', 0):.1f}) | Chip Delta: {c_gain:+.1f} pts")


if __name__ == "__main__":
    main()
