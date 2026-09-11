"""Reporting utilities for historical backtests and research evaluations (V0.7.1)."""

from typing import Any


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
