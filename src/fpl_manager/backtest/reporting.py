"""Reporting utilities for historical backtests and research evaluations (V0.7.1)."""

from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BACKTEST_REPORTS_DIR = PROJECT_ROOT / "reports" / "backtests"


def build_backtest_report_path(
    report_type: str,
    *inputs: Any,
    directory: Path | None = None,
    version: str | None = None,
) -> Path:
    """Build standardized backtest report path.

    Naming convention:
        {version}_backtest_{report_type}_{input1}_{input2}_....md
    Example:
        0.7.0_backtest_predictions_2023-24_1_38.md
        0.7.0_backtest_decisions_2023-24_all_1_10.md
    """
    if version is None:
        from .. import __version__
        version = __version__

    clean_inputs: list[str] = []
    for inp in inputs:
        if inp is not None:
            text = str(inp).strip()
            if text:
                clean_inputs.append(text.replace(" ", "_"))

    parts = [version, "backtest", report_type] + clean_inputs
    filename = f"{'_'.join(parts)}.md"
    target_dir = directory or DEFAULT_BACKTEST_REPORTS_DIR
    return target_dir / filename


def save_backtest_report(content: str, path: Path) -> Path:
    """Save backtest report content to specified markdown path, ensuring parent dirs exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def format_decision_report(
    simulations: list[Any],
    season: str = "2023-24",
    start_gw: int = 1,
    end_gw: int = 10,
) -> str:
    """Format sequential decision backtest simulations into a Markdown research report."""
    if not simulations:
        return f"# Historical Decision Simulation Backtest Report: Season {season} (GW {start_gw}-{end_gw})\n\nNo simulations run.\n"

    sorted_sims = sorted(simulations, key=lambda s: s.total_net_points, reverse=True)

    lines = [
        f"# Historical Decision Simulation Backtest Report: Season {season} (GW {start_gw}-{end_gw})",
        "",
        f"**Simulated Gameweeks:** {start_gw} - {end_gw} ({end_gw - start_gw + 1} gameweeks)",
        f"**Evaluated Strategies:** {len(simulations)}",
        "",
        "## 1. Strategy Rankings & Executive Summary",
        "",
        "| Rank | Strategy | Net Points | Gross Points | Transfer Hits | Total Transfers | Final Bank | Points / GW |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for rank, s in enumerate(sorted_sims, 1):
        bank_str = f"£{s.final_bank_tenths / 10:.1f}m"
        gw_count = s.gameweeks_played if s.gameweeks_played > 0 else (end_gw - start_gw + 1)
        pts_per_gw = round(s.total_net_points / gw_count, 1) if gw_count > 0 else 0.0
        pred_label = getattr(s, "predictor_version", "v0.9")
        strat_display = f"**{s.strategy_name}** (`{pred_label}`)"
        lines.append(
            f"| {rank} | {strat_display} | {s.total_net_points} | {s.total_gross_points} | -{s.total_hits} | {s.total_transfers} | {bank_str} | {pts_per_gw:.1f} |"
        )

    lines.extend([
        "",
        "## 2. Decision Quality, Transfer ROI & Participation Risk Decomposition",
        "",
        "| Strategy | Predictor | 0-Min Starters | 0-Min Captains | Bench Regret | Gross Transfer Gain | Transfer Net ROI |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])

    for s in sorted_sims:
        pred_label = getattr(s, "predictor_version", "v0.9")
        zero_starts = getattr(s, "total_zero_min_starters", 0)
        cap_zeros = getattr(s, "captain_zero_min_count", 0)
        bench_regret = getattr(s, "total_bench_regret_points", 0)
        t_gross = getattr(s, "total_transfer_gross_gain", 0)
        t_net = getattr(s, "total_transfer_net_gain", 0)
        net_roi_str = f"+{t_net}" if t_net > 0 else str(t_net)

        lines.append(
            f"| **{s.strategy_name}** | `{pred_label}` | {zero_starts} | {cap_zeros} | {bench_regret} pts | {t_gross:+} pts | **{net_roi_str} pts** |"
        )

    lines.extend([
        "",
        "## 3. Head-to-Head Comparisons",
        "",
    ])

    if len(simulations) > 1:
        # Find baseline strategy (e.g. NoTransferStrategy or last)
        baseline = next(
            (
                s for s in simulations
                if "baseline" in s.strategy_name.lower() or "notransfer" in s.strategy_name.lower() or "no-transfer" in s.strategy_name.lower()
            ),
            simulations[-1],
        )
        base_pred = getattr(baseline, "predictor_version", "v0.9")
        lines.extend([
            f"**Baseline Strategy:** {baseline.strategy_name} (`{base_pred}`) — {baseline.total_net_points} net pts",
            "",
            "| Strategy | vs Baseline Net Pts | Net Difference | Wins | Losses | Ties | Mean GW Diff |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
        ])
        for s in sorted_sims:
            if s is baseline:
                continue
            net_diff = s.total_net_points - baseline.total_net_points
            diff_str = f"+{net_diff}" if net_diff > 0 else str(net_diff)
            gw_diffs = [
                b.net_points - a.net_points
                for a, b in zip(baseline.history, s.history)
            ]
            wins = sum(1 for d in gw_diffs if d > 0)
            losses = sum(1 for d in gw_diffs if d < 0)
            ties = sum(1 for d in gw_diffs if d == 0)
            mean_d = round(sum(gw_diffs) / len(gw_diffs), 2) if gw_diffs else 0.0
            mean_d_str = f"+{mean_d:.2f}" if mean_d > 0 else f"{mean_d:.2f}"
            s_pred = getattr(s, "predictor_version", "v0.9")
            lines.append(
                f"| **{s.strategy_name}** (`{s_pred}`) | {s.total_net_points} vs {baseline.total_net_points} | **{diff_str}** | {wins} | {losses} | {ties} | {mean_d_str} pts/GW |"
            )
        lines.append("")
    else:
        lines.extend([
            "Single strategy evaluated. Run with `--strategy all` to compare multiple decision strategies.",
            "",
        ])

    lines.extend([
        "## 4. Gameweek-by-Gameweek Progression",
        "",
        "| GW | Strategy | Predictor | Net Points | Gross Points | Hits | Transfers | Auto-Subs | Captain Promoted |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])

    for s in sorted_sims:
        s_pred = getattr(s, "predictor_version", "v0.9")
        for rec in s.history:
            subs_str = len(rec.autosubs) if rec.autosubs else 0
            cap_prom = "Yes" if rec.captain_promoted else "No"
            lines.append(
                f"| GW{rec.gameweek} | {s.strategy_name} | `{s_pred}` | {rec.net_points} | {rec.gross_points} | -{rec.transfer_hits} | {len(rec.transfers)} | {subs_str} | {cap_prom} |"
            )

    lines.append("")
    return "\n".join(lines)


def format_prediction_report(results: dict[str, Any], season: str = "2023-24", gameweek_range: str = "1-38") -> str:
    """Format quantitative prediction backtesting metrics into a Markdown research report."""
    xp = results.get("xp", {})
    xm = results.get("xm", {})
    avail = results.get("availability", {})
    by_pos = results.get("by_position", {})
    by_price = results.get("by_price_tier", {})
    total = results.get("total_records", 0)

    lines = [
        f"# Historical Prediction Backtest Report: Season {season} (GW {gameweek_range})",
        "",
        f"**Evaluated Player-Gameweeks:** {total:,}",
        "",
        "## 1. Overall Expected Points (xP) Accuracy",
        "",
        "| Metric | Value | Description |",
        "| :--- | :---: | :--- |",
        f"| **MAE** | {xp.get('overall_mae', 0.0):.3f} pts | Mean Absolute Error across all player-GWs |",
        f"| **RMSE** | {xp.get('overall_rmse', 0.0):.3f} pts | Root Mean Squared Error (penalizes large misses) |",
        f"| **Spearman Correlation** | {xp.get('spearman_correlation', 0.0):.4f} | Rank-order alignment of predictions vs actual points |",
        f"| **Prediction Bias** | {xp.get('bias', 0.0):+.3f} pts | Mean(Predicted - Actual) across sample |",
        f"| **Active Players MAE** | {xp.get('active_players_mae', 0.0):.3f} pts | MAE for players who played >0 minutes |",
        f"| **Active Players Spearman** | {xp.get('active_players_spearman', 0.0):.4f} | Rank correlation among active starters/subs |",
        "",
        "## 2. Expected Minutes (xM) Accuracy & Calibration",
        "",
        f"- **Minutes MAE:** {xm.get('overall_mae', 0.0):.2f} mins",
        f"- **Minutes RMSE:** {xm.get('overall_rmse', 0.0):.2f} mins",
        f"- **Minutes Bias:** {xm.get('bias', 0.0):+.2f} mins",
        "",
        "### Calibration by Predicted Minutes Bucket",
        "",
        "| Predicted Minutes Bucket | Count | Mean Predicted | Mean Actual | MAE |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ]

    cal_buckets = xm.get("calibration_buckets", {})
    for b_name in ("0-15", "16-30", "31-60", "61-75", "76-90"):
        b_data = cal_buckets.get(b_name, {})
        lines.append(
            f"| **{b_name} mins** | {b_data.get('count', 0):,} | {b_data.get('mean_predicted', 0.0):.1f} | {b_data.get('mean_actual', 0.0):.1f} | {b_data.get('mae', 0.0):.1f} |"
        )

    lines.extend([
        "",
        "## 3. Availability Model Evaluation",
        "",
        "| Metric | Value | Interpretation |",
        "| :--- | :---: | :--- |",
        f"| **Accuracy** | {avail.get('accuracy', 0.0) * 100:.1f}% | Percentage of correctly classified playing states |",
        f"| **Precision** | {avail.get('precision', 0.0) * 100:.1f}% | True starters/subs out of predicted available |",
        f"| **Recall** | {avail.get('recall', 0.0) * 100:.1f}% | Available players identified by model |",
        f"| **False Positives** | {avail.get('false_positives', 0):,} | Predicted available but played 0 mins (rotation/injury) |",
        f"| **False Negatives** | {avail.get('false_negatives', 0):,} | Predicted unavailable but played minutes |",
        "",
        "## 4. Performance Breakdown by Position",
        "",
        "| Position | Count | xP MAE | xP RMSE | Spearman | Mean Pred | Mean Act |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])

    for pos_name, p_data in by_pos.items():
        lines.append(
            f"| **{pos_name}** | {p_data.get('count', 0):,} | {p_data.get('xp_mae', 0.0):.2f} | {p_data.get('xp_rmse', 0.0):.2f} | {p_data.get('xp_spearman', 0.0):.4f} | {p_data.get('mean_predicted', 0.0):.2f} | {p_data.get('mean_actual', 0.0):.2f} |"
        )

    lines.extend([
        "",
        "## 5. Performance Breakdown by Price Tier",
        "",
        "| Price Tier | Count | xP MAE | xP RMSE | Spearman |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ])

    for tier_name, t_data in by_price.items():
        lines.append(
            f"| **{tier_name}** | {t_data.get('count', 0):,} | {t_data.get('xp_mae', 0.0):.2f} | {t_data.get('xp_rmse', 0.0):.2f} | {t_data.get('xp_spearman', 0.0):.4f} |"
        )

    lines.append("")
    return "\n".join(lines)
