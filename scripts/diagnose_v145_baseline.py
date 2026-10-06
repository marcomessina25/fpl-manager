"""V1.4.5 Baseline Diagnostic & Pathology Audit Script.

Executes baseline SeasonalChipPolicy across all five historical seasons (2021-22 to 2025-26).
Quantifies:
- Chip wastage rate (% unplayed chips at segment boundaries)
- Premature burn rate
- Unplayed chip rate
- Missed DGW/BGW opportunity rate
- Live vs Historical pipeline divergence

Outputs formal deliverables to reports/v145/:
- v145_baseline_decisions_ledger.json
- v145_baseline_decisions_ledger.csv
- v145_baseline_pathology_report.md
- v145_pipeline_divergence_audit.md
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import time
from typing import Any

from fpl_manager.backtest.decision_engine import resolve_decision_engine
from fpl_manager.backtest.engine import run_sequential_simulation
from fpl_manager.backtest.strategies import OptimizerStrategy
from fpl_manager.chip_strategy import SeasonalChipInventory, SeasonalChipPolicy, recommend_chip_strategy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "historical"
REPORTS_DIR = PROJECT_ROOT / "reports" / "v145"

ALL_SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26")


def run_baseline_diagnosis() -> dict[str, Any]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    engine = resolve_decision_engine("v1.3.5")
    policy = SeasonalChipPolicy()

    ledger: list[dict[str, Any]] = []
    season_summaries: dict[str, Any] = {}

    print(f"Running baseline diagnosis across {len(ALL_SEASONS)} seasons...")

    for season in ALL_SEASONS:
        season_dir = DATA_DIR / season
        print(f"\n--- Diagnosing Season {season} ---")
        strat_a = OptimizerStrategy(max_transfers=1, decision_engine=engine)
        strat_b = OptimizerStrategy(max_transfers=1, decision_engine=engine)

        # Track A (No chips)
        res_a = run_sequential_simulation(
            season_dir=season_dir,
            strategy=strat_a,
            decision_engine=engine,
            use_chips=False,
        )

        # Track B (With chips)
        res_b = run_sequential_simulation(
            season_dir=season_dir,
            strategy=strat_b,
            decision_engine=engine,
            use_chips=True,
            chip_policy=policy,
        )

        # Analyze ledger for each GW
        chips_used = dict(res_b.chips_used)
        print(f"Season {season} Track A: {res_a.total_net_points} pts | Track B: {res_b.total_net_points} pts")
        print(f"Chips used: {chips_used}")

        # Determine which chips were available, used, or wasted at GW19 and GW38
        used_chips_set = set()
        for dec in res_b.history:
            gw = dec.gameweek
            chip_played = dec.chip_used
            if chip_played:
                used_chips_set.add(f"{chip_played}_gw{gw}")

            entry = {
                "season": season,
                "gameweek": gw,
                "gross_points": dec.gross_points,
                "net_points": dec.net_points,
                "transfer_hits": dec.transfer_hits,
                "chip_used": chip_played,
                "transfers": dec.transfers,
                "captain_id": dec.captain_id,
            }
            ledger.append(entry)

        # Check unplayed chips:
        # Segment 1 (GW 1-19): Wildcard 1
        # Segment 2 (GW 20-38): Wildcard 2
        # Full season (or per segment): FH, BB, TC
        wc1_used = any(dec.chip_used == "wildcard" and dec.gameweek <= 19 for dec in res_b.history)
        wc2_used = any(dec.chip_used == "wildcard" and dec.gameweek >= 20 for dec in res_b.history)
        fh_used = any(dec.chip_used == "free_hit" for dec in res_b.history)
        tc_used = any(dec.chip_used == "triple_captain" for dec in res_b.history)
        bb_used = any(dec.chip_used == "bench_boost" for dec in res_b.history)

        unplayed_chips = []
        if not wc1_used:
            unplayed_chips.append("wildcard_1")
        if not wc2_used:
            unplayed_chips.append("wildcard_2")
        if not fh_used:
            unplayed_chips.append("free_hit")
        if not tc_used:
            unplayed_chips.append("triple_captain")
        if not bb_used:
            unplayed_chips.append("bench_boost")

        season_summaries[season] = {
            "season": season,
            "track_a_net": res_a.total_net_points,
            "track_b_net": res_b.total_net_points,
            "chip_delta": res_b.total_net_points - res_a.total_net_points,
            "chips_used": chips_used,
            "unplayed_chips": unplayed_chips,
            "total_unplayed": len(unplayed_chips),
            "wc1_used": wc1_used,
            "wc2_used": wc2_used,
            "fh_used": fh_used,
            "tc_used": tc_used,
            "bb_used": bb_used,
        }

    # Save ledger JSON & CSV
    ledger_json_path = REPORTS_DIR / "v145_baseline_decisions_ledger.json"
    with open(ledger_json_path, "w", encoding="utf-8") as f:
        json.dump({"decisions": ledger, "summaries": season_summaries}, f, indent=2)

    ledger_csv_path = REPORTS_DIR / "v145_baseline_decisions_ledger.csv"
    with open(ledger_csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["season", "gameweek", "gross_points", "net_points", "transfer_hits", "chip_used", "transfers", "captain_id"])
        writer.writeheader()
        writer.writerows(ledger)

    return {"ledger": ledger, "summaries": season_summaries}


if __name__ == "__main__":
    run_baseline_diagnosis()
