"""Backtesting and model accuracy evaluation engine for FPL Manager V0.4.

Provides point-in-time historical backtesting, prediction calibration analysis,
captaincy/bench regret analysis, and human vs model divergence tracking.
"""

from contextlib import closing
import json
import math
from pathlib import Path
from typing import Any

from .decision_log import get_gameweek_decision, list_decisions
from .expected_points import project_gameweek
from .storage import SnapshotStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
EVALUATION_REPORT_PATH = PROJECT_ROOT / "reports" / "evaluation_summary.json"


def _rank_data(values: list[float]) -> list[float]:
    """Assign fractional ranks to data, handling ties with average rank."""
    n = len(values)
    if n == 0:
        return []
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and indexed[j][1] == indexed[j + 1][1]:
            j += 1
        avg_rank = 1.0 + (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def spearman_rank_correlation(x: list[float], y: list[float]) -> float:
    """Compute Spearman's rank correlation coefficient between two numeric series.

    Returns a value between -1.0 and +1.0. Returns 0.0 if variance is zero or length < 2.
    """
    if len(x) != len(y) or len(x) < 2:
        return 0.0

    rx = _rank_data(x)
    ry = _rank_data(y)

    n = len(rx)
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n

    num = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    den_x = sum((rx[i] - mean_rx) ** 2 for i in range(n))
    den_y = sum((ry[i] - mean_ry) ** 2 for i in range(n))

    denominator = math.sqrt(den_x * den_y)
    if denominator == 0.0:
        return 0.0
    return round(num / denominator, 4)


def mean_absolute_error(predicted: list[float], actual: list[float]) -> float:
    """Compute Mean Absolute Error (MAE)."""
    if not predicted or len(predicted) != len(actual):
        return 0.0
    return round(sum(abs(p - a) for p, a in zip(predicted, actual)) / len(predicted), 3)


def root_mean_squared_error(predicted: list[float], actual: list[float]) -> float:
    """Compute Root Mean Squared Error (RMSE)."""
    if not predicted or len(predicted) != len(actual):
        return 0.0
    mse = sum((p - a) ** 2 for p, a in zip(predicted, actual)) / len(predicted)
    return round(math.sqrt(mse), 3)


def uncertainty_calibration(
    predictions: list[dict[str, Any]],
    actuals: dict[int, float],
) -> dict[str, Any]:
    """Calculate the calibration coverage of [floor, ceiling] intervals against actual outcomes.

    Assesses what fraction of players scored within their predicted confidence interval.
    """
    within_count = 0
    below_floor = 0
    above_ceiling = 0
    total = 0

    for pred in predictions:
        pid = pred["player_id"]
        if pid in actuals:
            actual = actuals[pid]
            floor = pred.get("xp_floor", pred.get("expected_points", 0.0))
            ceiling = pred.get("xp_ceiling", pred.get("expected_points", 0.0))
            total += 1
            if floor <= actual <= ceiling:
                within_count += 1
            elif actual < floor:
                below_floor += 1
            else:
                above_ceiling += 1

    if total == 0:
        return {
            "total_evaluated": 0,
            "coverage_percent": 0.0,
            "below_floor_percent": 0.0,
            "above_ceiling_percent": 0.0,
        }

    return {
        "total_evaluated": total,
        "coverage_percent": round(within_count / total * 100.0, 1),
        "below_floor_percent": round(below_floor / total * 100.0, 1),
        "above_ceiling_percent": round(above_ceiling / total * 100.0, 1),
    }


def evaluate_captaincy_decision(
    starting_ids: list[int],
    captain_id: int,
    vice_captain_id: int,
    actual_scores: dict[int, float],
    players_by_id: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Calculate captaincy points, optimal captain in XI, and captaincy regret."""
    p_map = players_by_id or {}
    cap_score = actual_scores.get(captain_id, 0.0)
    vc_score = actual_scores.get(vice_captain_id, 0.0)

    starter_scores = [(pid, actual_scores.get(pid, 0.0)) for pid in starting_ids]
    starter_scores.sort(key=lambda x: x[1], reverse=True)

    best_starter_id, best_score = starter_scores[0] if starter_scores else (captain_id, cap_score)
    regret = max(0.0, round(best_score - cap_score, 2))

    return {
        "captain_id": captain_id,
        "captain_name": p_map.get(captain_id, f"ID {captain_id}"),
        "captain_actual_points": cap_score,
        "vice_captain_id": vice_captain_id,
        "vice_captain_name": p_map.get(vice_captain_id, f"ID {vice_captain_id}"),
        "vice_captain_actual_points": vc_score,
        "optimal_captain_id": best_starter_id,
        "optimal_captain_name": p_map.get(best_starter_id, f"ID {best_starter_id}"),
        "optimal_captain_actual_points": best_score,
        "captaincy_regret_points": regret,
        "captaincy_bonus_points": cap_score,
    }


def evaluate_bench_decision(
    starting_ids: list[int],
    bench_ids: list[int],
    actual_scores: dict[int, float],
    players_by_id: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Calculate bench points left unplayed and comparison with starting XI."""
    p_map = players_by_id or {}
    bench_scores = [(pid, actual_scores.get(pid, 0.0)) for pid in bench_ids]
    starter_scores = [(pid, actual_scores.get(pid, 0.0)) for pid in starting_ids]

    total_bench_points = sum(score for _, score in bench_scores)
    max_bench_id, max_bench_score = max(bench_scores, key=lambda x: x[1]) if bench_scores else (None, 0.0)
    min_starter_id, min_starter_score = min(starter_scores, key=lambda x: x[1]) if starter_scores else (None, 0.0)

    bench_regret = max(0.0, round(max_bench_score - min_starter_score, 2)) if max_bench_id is not None else 0.0

    return {
        "total_bench_points": total_bench_points,
        "highest_bench_player_id": max_bench_id,
        "highest_bench_player_name": p_map.get(max_bench_id, f"ID {max_bench_id}") if max_bench_id else None,
        "highest_bench_points": max_bench_score,
        "lowest_starter_id": min_starter_id,
        "lowest_starter_name": p_map.get(min_starter_id, f"ID {min_starter_id}") if min_starter_id else None,
        "lowest_starter_points": min_starter_score,
        "bench_regret_points": bench_regret,
    }


def compare_human_vs_model(
    decision: dict[str, Any],
    recommended_lineup: dict[str, Any] | None,
    actual_scores: dict[int, float],
    players_by_id: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Compare manager's chosen starting lineup vs baseline model recommendation."""
    p_map = players_by_id or {}
    human_starters = set(decision.get("starting_player_ids", []))
    human_cap = decision.get("captain_id")

    human_starters_pts = sum(actual_scores.get(pid, 0.0) for pid in human_starters)
    human_cap_pts = actual_scores.get(human_cap, 0.0) if human_cap else 0.0
    human_hits = decision.get("transfer_hits", 0)
    human_total = human_starters_pts + human_cap_pts - (human_hits * 4)

    if not recommended_lineup:
        return {
            "human_actual_total": human_total,
            "model_actual_total": None,
            "delta_points": None,
            "starters_in_common": len(human_starters),
            "human_only_starters": [],
            "model_only_starters": [],
        }

    rec_starters = set(p["id"] for p in recommended_lineup.get("starters", []))
    rec_cap = recommended_lineup.get("captain", {}).get("id")

    rec_starters_pts = sum(actual_scores.get(pid, 0.0) for pid in rec_starters)
    rec_cap_pts = actual_scores.get(rec_cap, 0.0) if rec_cap else 0.0
    rec_total = rec_starters_pts + rec_cap_pts

    common = human_starters.intersection(rec_starters)
    human_only = human_starters - rec_starters
    model_only = rec_starters - human_starters

    delta = round(human_total - rec_total, 2)

    return {
        "human_actual_total": round(human_total, 2),
        "model_actual_total": round(rec_total, 2),
        "delta_points": delta,
        "delta_verdict": "Human outperformed Model" if delta > 0 else ("Model outperformed Human" if delta < 0 else "Tied"),
        "starters_in_common": len(common),
        "human_only_starters": [{"id": pid, "name": p_map.get(pid, f"ID {pid}"), "actual_points": actual_scores.get(pid, 0.0)} for pid in human_only],
        "model_only_starters": [{"id": pid, "name": p_map.get(pid, f"ID {pid}"), "actual_points": actual_scores.get(pid, 0.0)} for pid in model_only],
    }


def evaluate_predictions(
    gameweek: int,
    actual_scores: dict[int, float],
    database_path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    """Evaluate accuracy of xP predictions for a gameweek against actual scores.

    Computes MAE, RMSE, Spearman rank correlation, and interval coverage calibration.
    """
    projections = project_gameweek(gameweek=gameweek, database_path=database_path)

    predicted_list = []
    actual_list = []
    pred_dicts = []

    for p in projections:
        if p.player_id in actual_scores:
            predicted_list.append(p.expected_points)
            actual_list.append(actual_scores[p.player_id])
            pred_dicts.append({
                "player_id": p.player_id,
                "player_name": p.web_name,
                "expected_points": p.expected_points,
                "xp_floor": p.xp_floor,
                "xp_ceiling": p.xp_ceiling,
            })

    mae = mean_absolute_error(predicted_list, actual_list)
    rmse = root_mean_squared_error(predicted_list, actual_list)
    rank_corr = spearman_rank_correlation(predicted_list, actual_list)
    calibration = uncertainty_calibration(pred_dicts, actual_scores)

    return {
        "gameweek": gameweek,
        "players_evaluated": len(predicted_list),
        "mae": mae,
        "rmse": rmse,
        "spearman_rank_correlation": rank_corr,
        "calibration": calibration,
    }


def evaluate_gameweek_decision(
    gameweek: int,
    actual_scores: dict[int, float] | None = None,
    season: str = "2026/27",
    team_id: str = "default",
    database_path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    """Comprehensive post-gameweek evaluation combining prediction accuracy and decision regret."""
    if not actual_scores:
        from .scores import get_or_fetch_gameweek_scores
        actual_scores = get_or_fetch_gameweek_scores(gameweek, database_path=database_path)

    store = SnapshotStore(database_path)
    store.initialize()

    with closing(store._connect()) as connection:
        name_rows = connection.execute("SELECT player_id, web_name FROM players GROUP BY player_id").fetchall()
        players_by_id = dict(name_rows)

        rec_row = connection.execute(
            """
            SELECT r.recommended_lineup_json
            FROM decision_recommendations r
            JOIN decisions d ON d.id = r.decision_id
            WHERE d.team_id = ? AND d.season = ? AND d.gameweek = ?
            """,
            (team_id, season, gameweek),
        ).fetchone()
        recommended_lineup = json.loads(rec_row[0]) if (rec_row and rec_row[0]) else None

    decision = get_gameweek_decision(gameweek, season=season, team_id=team_id, database_path=database_path)
    prediction_eval = evaluate_predictions(gameweek, actual_scores, database_path=database_path)

    if decision is None:
        return {
            "gameweek": gameweek,
            "team_id": team_id,
            "decision_logged": False,
            "prediction_accuracy": prediction_eval,
            "captaincy": None,
            "bench": None,
            "human_vs_model": None,
        }

    starters = decision["starting_player_ids"]
    bench = decision["bench_player_ids"]
    cap_id = decision["captain_id"]
    vc_id = decision["vice_captain_id"]

    captain_eval = evaluate_captaincy_decision(starters, cap_id, vc_id, actual_scores, players_by_id)
    bench_eval = evaluate_bench_decision(starters, bench, actual_scores, players_by_id)
    hvm_eval = compare_human_vs_model(decision, recommended_lineup, actual_scores, players_by_id)

    # Actual lineup score
    actual_lineup = (
        sum(actual_scores.get(pid, 0.0) for pid in starters)
        + actual_scores.get(cap_id, 0.0)
        - (decision.get("transfer_hits", 0) * 4)
    )

    xp_delta = round(actual_lineup - decision["predicted_lineup_xp"], 2)

    # Auto-update actual points in decision record if not yet finalized
    if decision.get("actual_points") is None and actual_scores:
        try:
            from .decision_log import record_actual_gameweek_score
            record_actual_gameweek_score(gameweek, round(actual_lineup), season=season, team_id=team_id, database_path=database_path)
            decision["actual_points"] = round(actual_lineup)
        except Exception:
            pass

    return {
        "gameweek": gameweek,
        "season": season,
        "team_id": team_id,
        "decision_logged": True,
        "predicted_lineup_xp": decision["predicted_lineup_xp"],
        "actual_lineup_score": round(actual_lineup, 2),
        "prediction_error_delta": xp_delta,
        "prediction_accuracy": prediction_eval,
        "captaincy": captain_eval,
        "bench": bench_eval,
        "human_vs_model": hvm_eval,
    }


def evaluate_season_decisions(
    season: str = "2026/27",
    team_id: str = "default",
    database_path: Path = DATABASE_PATH,
    report_path: Path = EVALUATION_REPORT_PATH,
) -> dict[str, Any]:
    """Aggregate decision evaluation across all finalized gameweeks in the season."""
    decisions = list_decisions(season=season, team_id=team_id, database_path=database_path)

    # Auto-finalize any unfinalized decisions if scores are available
    from .scores import get_or_fetch_gameweek_scores
    for d in decisions:
        if d.get("actual_points") is None:
            gw_scores = get_or_fetch_gameweek_scores(d["gameweek"], database_path=database_path)
            if gw_scores:
                starters = d["starting_player_ids"]
                cap_id = d["captain_id"]
                hits = d.get("transfer_hits", 0)
                actual_lineup = (
                    sum(gw_scores.get(pid, 0.0) for pid in starters)
                    + gw_scores.get(cap_id, 0.0)
                    - (hits * 4)
                )
                try:
                    from .decision_log import record_actual_gameweek_score
                    record_actual_gameweek_score(d["gameweek"], round(actual_lineup), season=season, team_id=team_id, database_path=database_path)
                    d["actual_points"] = round(actual_lineup)
                except Exception:
                    pass

    finalized = [d for d in decisions if d.get("actual_points") is not None]

    if not finalized:
        return {
            "season": season,
            "team_id": team_id,
            "finalized_gameweeks": 0,
            "summary": "No decisions with finalized actual scores recorded yet.",
            "gameweeks": [],
        }

    predicted_list = [d["predicted_lineup_xp"] for d in finalized]
    actual_list = [float(d["actual_points"]) for d in finalized]

    mae = mean_absolute_error(predicted_list, actual_list)
    rmse = root_mean_squared_error(predicted_list, actual_list)
    mean_bias = round(sum(p - a for p, a in zip(predicted_list, actual_list)) / len(predicted_list), 2)

    total_pred = round(sum(predicted_list), 1)
    total_act = round(sum(actual_list), 1)
    total_hits = sum(d.get("transfer_hits", 0) for d in finalized)

    gw_details = []
    for d in finalized:
        pred_xp = d["predicted_lineup_xp"]
        act_pts = float(d["actual_points"])
        delta = round(act_pts - pred_xp, 1)
        gw_details.append({
            "gameweek": d["gameweek"],
            "captain_name": d.get("captain_name"),
            "chip_played": d.get("chip_played"),
            "transfer_hits": d.get("transfer_hits", 0),
            "predicted_xp": pred_xp,
            "actual_points": act_pts,
            "delta": delta,
        })

    result = {
        "season": season,
        "finalized_gameweeks": len(finalized),
        "total_predicted_xp": total_pred,
        "total_actual_points": total_act,
        "total_transfer_hits": total_hits,
        "lineup_mae": mae,
        "lineup_rmse": rmse,
        "mean_prediction_bias": mean_bias,
        "bias_interpretation": (
            f"Model over-predicts by {mean_bias:.1f} pts/GW on average"
            if mean_bias > 0
            else (f"Model under-predicts by {abs(mean_bias):.1f} pts/GW on average" if mean_bias < 0 else "Neutral")
        ),
        "gameweeks": gw_details,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result
