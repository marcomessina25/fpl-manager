import time
from datetime import datetime, timezone
from fpl_manager.backtest.strategic_analysis import run_version_comparison_backtest

def main():
    print(f"Starting 5-Season Multi-Version Benchmark at {datetime.now(timezone.utc).isoformat()}...")
    t0 = time.time()
    results = run_version_comparison_backtest(
        seasons=("2021-22", "2022-23", "2023-24", "2024-25", "2025-26"),
        versions=("v0.9", "v1.0", "v1.1", "v1.1.5", "v1.2"),
        tracks=("track_a_no_chips", "track_b_with_chips"),
        start_gw=1,
        end_gw=38,
        smoke_test=False,
        save_report=True,
    )
    elapsed = time.time() - t0
    print(f"\n==========================================")
    print(f"Benchmark completed successfully in {elapsed:.1f} seconds ({elapsed/60:.2f} minutes).")
    print(f"Report saved to: {results.get('report_path')}")
    print(f"==========================================\n")
    
    version_aggregates = results.get("version_aggregates", {})
    print("Track A Aggregates (No Chips):")
    for ver in ("v0.9", "v1.0", "v1.1", "v1.1.5", "v1.2"):
        agg = version_aggregates.get(ver, {}).get("track_a_no_chips", {})
        print(f"  {ver:7s}: {agg.get('mean_net_points', 0):.1f} pts (±{agg.get('std_net_points', 0):.1f})")

    print("\nTrack B Aggregates (With Chips):")
    for ver in ("v0.9", "v1.0", "v1.1", "v1.1.5", "v1.2"):
        agg = version_aggregates.get(ver, {}).get("track_b_with_chips", {})
        print(f"  {ver:7s}: {agg.get('mean_net_points', 0):.1f} pts (±{agg.get('std_net_points', 0):.1f})")

if __name__ == "__main__":
    main()
