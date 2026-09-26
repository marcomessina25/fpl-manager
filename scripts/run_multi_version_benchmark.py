import time
from fpl_manager.backtest.strategic_analysis import run_version_comparison_backtest

t0 = time.time()
print("Starting multi-version benchmark across all available seasons (GW 1-38)...", flush=True)
res = run_version_comparison_backtest(
    seasons=("2021-22", "2022-23", "2023-24", "2024-25", "2025-26"),
    start_gw=1,
    end_gw=38,
    smoke_test=False,
)
dur = time.time() - t0
print(f"Benchmark completed in {dur:.1f}s!", flush=True)
print(f"Markdown report: {res.get('report_path')}", flush=True)
print(f"JSON ledger: {res.get('json_path')}", flush=True)
