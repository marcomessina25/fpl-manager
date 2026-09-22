"""Closed-loop decision evaluation and prediction accuracy engine for FPL Manager (V1.0.1).

Provides point-in-time historical backtesting, prediction calibration analysis,
mutually exclusive additive regret decomposition (`additive_regret_decomposition`),
overlapping counterfactual diagnostics (`decision_loss_diagnostics`), decision-weighted
error (`calculate_decision_weighted_error`), and observed vs hindsight outcome separation.
"""

from contextlib import closing
import json
import math
from pathlib import Path
from typing import Any

from .decision_log import get_gameweek_decision, list_decisions
from .expected_points import project_gameweek
from .models import Position
from .rules import is_free_transfers_chip
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


LEGAL_FORMATIONS: tuple[tuple[int, int, int], ...] = (
    (3, 5, 2),
    (3, 4, 3),
    (4, 4, 2),
    (4, 3, 3),
    (4, 5, 1),
    (5, 3, 2),
    (5, 4, 1),
    (5, 2, 3),
)


def compute_decision_confidence(
    starter_xps: list[float],
    bench_xps: list[float],
    captain_xp: float,
    vice_captain_xp: float,
    starter_p_starts: list[float] | None = None,
) -> dict[str, Any]:
    """Compute pre-deadline decision confidence score and risk decomposition (V0.9.9)."""
    min_starter = min(starter_xps) if starter_xps else 0.0
    outfield_bench_xps = bench_xps[:3] if len(bench_xps) >= 3 else bench_xps
    max_bench = max(outfield_bench_xps) if outfield_bench_xps else 0.0
    lineup_margin = round(min_starter - max_bench, 2)

    captaincy_margin = round(max(0.0, captain_xp - vice_captain_xp), 2)

    p_starts = starter_p_starts or [0.90] * len(starter_xps)
    mean_p_start = sum(p_starts) / len(p_starts) if p_starts else 0.90
    rotation_risk_index = round(max(0.0, 1.0 - mean_p_start), 3)

    raw_conf = 50.0 + (lineup_margin * 10.0) + (captaincy_margin * 12.0) - (rotation_risk_index * 60.0)
    confidence_pct = round(max(5.0, min(99.0, raw_conf)), 1)

    if confidence_pct >= 75.0:
        label = "HIGH"
    elif confidence_pct >= 50.0:
        label = "MODERATE"
    elif confidence_pct >= 30.0:
        label = "LOW"
    else:
        label = "SPECULATIVE"

    return {
        "confidence_score": confidence_pct,
        "confidence_label": label,
        "lineup_certainty_margin": lineup_margin,
        "captaincy_certainty_margin": captaincy_margin,
        "rotation_risk_index": rotation_risk_index,
        "mean_starter_p_start": round(mean_p_start, 3),
    }


def compute_counterfactual_lineups(
    decision: dict[str, Any],
    recommended_lineup: dict[str, Any] | None,
    actual_scores: dict[int, float],
    players_meta: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Calculate closed-loop counterfactual analysis across Human, Model, Hybrid, and Hindsight Optimal."""
    human_starters = list(decision.get("starting_player_ids", []))
    human_cap = decision.get("captain_id")
    human_hits = 0 if is_free_transfers_chip(decision.get("chip_played")) else decision.get("transfer_hits", 0)

    human_pts = sum(actual_scores.get(pid, 0.0) for pid in human_starters) + (actual_scores.get(human_cap, 0.0) if human_cap else 0.0) - (human_hits * 4)

    model_starters: list[int] = []
    model_cap: int | None = None
    if recommended_lineup:
        model_starters = [p["id"] for p in recommended_lineup.get("starters", [])]
        model_cap = recommended_lineup.get("captain", {}).get("id")

    if model_starters:
        model_pts = sum(actual_scores.get(pid, 0.0) for pid in model_starters) + (actual_scores.get(model_cap, 0.0) if model_cap else 0.0)
    else:
        model_pts = None

    if model_starters and human_starters:
        hybrid_cap = human_cap if human_cap else model_cap
        hybrid_pts = sum(actual_scores.get(pid, 0.0) for pid in human_starters) + (actual_scores.get(hybrid_cap, 0.0) if hybrid_cap else 0.0)
    else:
        hybrid_pts = human_pts

    squad_ids = decision.get("squad_player_ids") or (human_starters + decision.get("bench_player_ids", []))
    by_pos: dict[Position, list[tuple[int, float]]] = {pos: [] for pos in Position}
    for pid in squad_ids:
        pos = players_meta.get(pid, {}).get("position", Position.MIDFIELDER)
        pts = actual_scores.get(pid, 0.0)
        by_pos[pos].append((pid, pts))

    for pos in by_pos:
        by_pos[pos].sort(key=lambda x: x[1], reverse=True)

    gks = by_pos[Position.GOALKEEPER]
    defs = by_pos[Position.DEFENDER]
    mids = by_pos[Position.MIDFIELDER]
    fwds = by_pos[Position.FORWARD]

    best_hindsight_pts = -999.0
    best_hindsight_starters: list[int] = []
    best_hindsight_cap: int | None = None

    best_gk_id = gks[0][0] if gks else (squad_ids[0] if squad_ids else 0)
    best_gk_pts = gks[0][1] if gks else 0.0

    for d_cnt, m_cnt, f_cnt in LEGAL_FORMATIONS:
        if len(defs) < d_cnt or len(mids) < m_cnt or len(fwds) < f_cnt:
            continue
        cur_starters = [best_gk_id]
        cur_pts = best_gk_pts

        sel_defs = defs[:d_cnt]
        cur_starters.extend(p[0] for p in sel_defs)
        cur_pts += sum(p[1] for p in sel_defs)

        sel_mids = mids[:m_cnt]
        cur_starters.extend(p[0] for p in sel_mids)
        cur_pts += sum(p[1] for p in sel_mids)

        sel_fwds = fwds[:f_cnt]
        cur_starters.extend(p[0] for p in sel_fwds)
        cur_pts += sum(p[1] for p in sel_fwds)

        starter_scores = [(pid, actual_scores.get(pid, 0.0)) for pid in cur_starters]
        starter_scores.sort(key=lambda x: x[1], reverse=True)
        h_cap_id, h_cap_bonus = starter_scores[0]
        total_formation_pts = cur_pts + h_cap_bonus

        if total_formation_pts > best_hindsight_pts:
            best_hindsight_pts = total_formation_pts
            best_hindsight_starters = cur_starters
            best_hindsight_cap = h_cap_id

    hindsight_gap = round(best_hindsight_pts - human_pts, 2) if best_hindsight_pts > -900 else 0.0
    human_vs_model_delta = round(human_pts - model_pts, 2) if model_pts is not None else None

    return {
        "human_actual_total": round(human_pts, 2),
        "model_actual_total": round(model_pts, 2) if model_pts is not None else None,
        "hybrid_actual_total": round(hybrid_pts, 2) if hybrid_pts is not None else None,
        "human_vs_model_delta": human_vs_model_delta,
        "human_verdict": (
            "Human beat model" if (human_vs_model_delta is not None and human_vs_model_delta > 0)
            else ("Model beat human" if (human_vs_model_delta is not None and human_vs_model_delta < 0) else "Tied / Model unavailable")
        ),
        "hindsight_optimal": {
            "disclaimer": "[HINDSIGHT ONLY] Theoretical maximum legal score achievable with perfect future information.",
            "total_points": round(best_hindsight_pts, 2) if best_hindsight_pts > -900 else None,
            "starting_player_ids": best_hindsight_starters,
            "captain_id": best_hindsight_cap,
            "hindsight_gap_points": hindsight_gap,
        },
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
    human_hits = 0 if is_free_transfers_chip(decision.get("chip_played")) else decision.get("transfer_hits", 0)
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
    strict_matchday: bool = False,
) -> dict[str, Any]:
    """Comprehensive post-gameweek evaluation combining prediction accuracy and decision regret."""
    if not actual_scores:
        from .scores import get_or_fetch_gameweek_scores
        actual_scores = get_or_fetch_gameweek_scores(gameweek, database_path=database_path)

    store = SnapshotStore(database_path)
    store.initialize()

    with closing(store._connect()) as connection:
        name_rows = connection.execute("SELECT player_id, web_name, position_id FROM players GROUP BY player_id").fetchall()
        players_by_id = {r[0]: r[1] for r in name_rows}
        players_meta = {r[0]: {"name": r[1], "position": Position(r[2]) if r[2] else Position.MIDFIELDER} for r in name_rows}

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
            "evaluation_status": "unavailable",
            "evaluation_warning": "No decision logged for this gameweek.",
            "prediction_accuracy": prediction_eval,
            "captaincy": None,
            "bench": None,
            "human_vs_model": None,
            "decision_confidence": None,
            "counterfactuals": None,
        }

    starters = decision["starting_player_ids"]
    bench = decision["bench_player_ids"]
    cap_id = decision["captain_id"]
    vc_id = decision["vice_captain_id"]

    captain_eval = evaluate_captaincy_decision(starters, cap_id, vc_id, actual_scores, players_by_id)
    bench_eval = evaluate_bench_decision(starters, bench, actual_scores, players_by_id)
    hvm_eval = compare_human_vs_model(decision, recommended_lineup, actual_scores, players_by_id)
    counterfactuals = compute_counterfactual_lineups(
        decision=decision,
        recommended_lineup=recommended_lineup,
        actual_scores=actual_scores,
        players_meta=players_meta,
    )

    # Pre-deadline decision confidence
    try:
        from .expected_points import project_gameweek
        squad_pids = decision.get("squad_player_ids") or (starters + bench)
        projs = project_gameweek(gameweek=gameweek, player_ids=squad_pids, database_path=database_path)
        p_xp_map = {p.player_id: p.expected_points for p in projs}
        p_start_map = {p.player_id: getattr(p, "start_probability", 0.90) for p in projs}
        starter_xps = [p_xp_map.get(pid, 3.0) for pid in starters]
        bench_xps = [p_xp_map.get(pid, 2.0) for pid in bench]
        cap_xp = p_xp_map.get(cap_id, 5.0)
        vc_xp = p_xp_map.get(vc_id, 4.0)
        starter_p_starts = [p_start_map.get(pid, 0.90) for pid in starters]
        decision_conf = compute_decision_confidence(starter_xps, bench_xps, cap_xp, vc_xp, starter_p_starts)
    except Exception:
        decision_conf = compute_decision_confidence([4.0] * 11, [2.0] * 4, 6.0, 5.0)

    # Actual lineup score
    evaluation_status = "authoritative"
    evaluation_warning: str | None = None
    try:
        from .live_matchday import compute_matchday_lineup_performance
        perf = compute_matchday_lineup_performance(
            gameweek=gameweek,
            starting_ids=starters,
            bench_ids=bench,
            captain_id=cap_id,
            vice_captain_id=vc_id,
            chip_played=decision.get("chip_played"),
            transfer_hits=decision.get("transfer_hits", 0),
            database_path=database_path,
            custom_scores=actual_scores,
        )
        actual_lineup = float(perf["net_points"])
    except Exception as exc:
        if strict_matchday:
            raise
        evaluation_status = "fallback"
        evaluation_warning = f"Matchday calculation failed ({exc}); using unadjusted lineup sum fallback."
        dec_hits = 0 if is_free_transfers_chip(decision.get("chip_played")) else decision.get("transfer_hits", 0)
        actual_lineup = (
            sum(actual_scores.get(pid, 0.0) for pid in starters)
            + actual_scores.get(cap_id, 0.0)
            - (dec_hits * 4)
        )

    xp_delta = round(actual_lineup - decision["predicted_lineup_xp"], 2)

    # Auto-update actual points in decision record if not yet finalized,
    # PROVIDED that evaluation is authoritative AND the gameweek is fully completed.
    # Fallback or in-progress matchday calculations must NEVER silently contaminate the decision record.
    if decision.get("actual_points") is None and actual_scores and evaluation_status == "authoritative":
        from .scores import is_gameweek_completed
        if is_gameweek_completed(gameweek, database_path=database_path):
            try:
                from .decision_log import record_actual_gameweek_score
                record_actual_gameweek_score(gameweek, round(actual_lineup), season=season, team_id=team_id, database_path=database_path)
                decision["actual_points"] = round(actual_lineup)
            except Exception:
                pass

    error_attribution = decompose_decision_error_components(
        predicted_lineup_xp=float(decision.get("predicted_lineup_xp") or 0.0),
        actual_lineup_score=round(actual_lineup, 2),
        captain_regret=float(captain_eval.get("captain_regret", 0.0)),
        bench_regret=float(bench_eval.get("bench_regret", 0.0)),
        hindsight_optimal_points=float((counterfactuals or {}).get("hindsight_optimal", {}).get("total_points", actual_lineup)),
        transfers=decision.get("transfers", []),
        transfer_hits=0 if is_free_transfers_chip(decision.get("chip_played")) else int(decision.get("transfer_hits", 0)),
        chip_played=decision.get("chip_played"),
        actual_scores=actual_scores,
    )
    if isinstance(counterfactuals, dict):
        counterfactuals["observed_outcome"] = {
            "label": "observed_outcome",
            "actual_lineup_points": round(actual_lineup, 2),
            "human_actual_total": counterfactuals.get("human_actual_total", round(actual_lineup, 2)),
        }
        counterfactuals["hindsight_counterfactual"] = {
            "label": "hindsight_counterfactual (not achievable ex-ante)",
            "hindsight_best_legal_decision": counterfactuals.get("hindsight_optimal", {}),
        }

    return {
        "gameweek": gameweek,
        "season": season,
        "team_id": team_id,
        "decision_logged": True,
        "evaluation_status": evaluation_status,
        "evaluation_warning": evaluation_warning,
        "predicted_lineup_xp": decision["predicted_lineup_xp"],
        "actual_lineup_score": round(actual_lineup, 2),
        "prediction_error_delta": xp_delta,
        "error_attribution": error_attribution,
        "prediction_accuracy": prediction_eval,
        "captaincy": captain_eval,
        "bench": bench_eval,
        "human_vs_model": hvm_eval,
        "decision_confidence": decision_conf,
        "counterfactuals": counterfactuals,
    }


def decompose_decision_error_components(
    *,
    predicted_lineup_xp: float,
    actual_lineup_score: float,
    captain_regret: float,
    bench_regret: float,
    hindsight_optimal_points: float,
    transfers: list[dict[str, Any]] | None = None,
    transfer_hits: int = 0,
    chip_played: str | None = None,
    actual_scores: dict[int, float] | None = None,
) -> dict[str, Any]:
    """Decompose decision performance into an explicitly additive regret decomposition and labeled diagnostics (P1.1).

    1. Mutually Exclusive Additive Regret Decomposition:
         total_decision_regret
             = lineup_regret
             + captaincy_regret
             + transfer_regret
             + chip_regret
             + hit_cost
       where:
         - `captaincy_regret`: Points lost by choosing actual captain vs optimal starter captain.
         - `lineup_regret`: Pure XI/bench selection regret within the 15-player squad after removing captaincy_regret.
         - `transfer_regret`: Gross points shortfall when incoming transfer(s) score less than outgoing player(s) (before hits).
         - `chip_regret`: Shortfall against chip value threshold when a chip is deployed.
         - `hit_cost`: Explicit transfer hit penalty (`4 * transfer_hits`).

    2. Overlapping Decision-Loss Diagnostics (`decision_loss_diagnostics`):
       Retains raw diagnostic metrics (`prediction_error`, `decision_error`, `captaincy_error`,
       `transfer_error`, `chip_error`) explicitly marked with `is_overlapping_diagnostic = True`.
    """
    scores = actual_scores or {}
    moves = transfers or []
    gross_transfer_gain = 0.0
    for m in moves:
        in_id = m.get("player_in_id") or m.get("in_id")
        out_id = m.get("player_out_id") or m.get("out_id")
        if in_id is not None and out_id is not None:
            gross_transfer_gain += float(scores.get(int(in_id), 0.0)) - float(scores.get(int(out_id), 0.0))

    hit_cost = round(float(max(0, int(transfer_hits)) * 4), 2)
    net_transfer_gain = round(gross_transfer_gain - hit_cost, 2)
    transfer_error = round(max(0.0, -net_transfer_gain), 2)

    chip_error = 0.0
    chip_roi = 0.0
    if chip_played:
        chip_roi = round(actual_lineup_score - predicted_lineup_xp, 2)
        chip_error = round(max(0.0, 12.0 - max(0.0, actual_lineup_score - 50.0)), 2)

    prediction_error = round(abs(predicted_lineup_xp - actual_lineup_score), 2)
    decision_error = round(max(0.0, hindsight_optimal_points - actual_lineup_score), 2)
    captaincy_error = round(max(0.0, captain_regret), 2)

    # Mutually-exclusive additive regret components:
    captaincy_regret_add = captaincy_error
    lineup_regret_add = round(max(0.0, decision_error - captaincy_regret_add), 2)
    transfer_regret_add = round(max(0.0, -gross_transfer_gain), 2)
    chip_regret_add = chip_error
    total_decision_regret = round(
        lineup_regret_add + captaincy_regret_add + transfer_regret_add + chip_regret_add + hit_cost,
        2,
    )

    return {
        "semantics": "additive_regret_decomposition_and_decision_loss_diagnostics",
        "lineup_regret": lineup_regret_add,
        "captaincy_regret": captaincy_regret_add,
        "transfer_regret": transfer_regret_add,
        "chip_regret": chip_regret_add,
        "hit_cost": hit_cost,
        "total_decision_regret": total_decision_regret,
        "additive_regret_decomposition": {
            "lineup_regret": lineup_regret_add,
            "captaincy_regret": captaincy_regret_add,
            "transfer_regret": transfer_regret_add,
            "chip_regret": chip_regret_add,
            "hit_cost": hit_cost,
            "total_decision_regret": total_decision_regret,
            "is_mutually_exclusive_additive": True,
        },
        "decision_loss_diagnostics": {
            "prediction_error": prediction_error,
            "decision_error": decision_error,
            "captaincy_error": captaincy_error,
            "transfer_error": transfer_error,
            "chip_error": chip_error,
            "is_overlapping_diagnostic": True,
        },
        "prediction_error": prediction_error,
        "decision_error": decision_error,
        "captaincy_error": captaincy_error,
        "transfer_error": transfer_error,
        "chip_error": chip_error,
        "bench_regret": round(max(0.0, bench_regret), 2),
        "transfer_gross_gain": round(gross_transfer_gain, 2),
        "transfer_hit_cost": hit_cost,
        "transfer_net_gain": net_transfer_gain,
        "transfer_roi": net_transfer_gain,
        "chip_played": chip_played,
        "chip_roi": chip_roi,
    }


def calculate_decision_weighted_error(
    *,
    predicted_xp: float,
    actual_points: float,
    squad_selection_prob: float = 0.0,
    captaincy_prob: float = 0.0,
    price_tenths: int = 50,
    optimizer_exposure: float = 0.0,
    transfer_relevance: float = 0.0,
) -> dict[str, float]:
    """Compute V1.0 decision-weighted prediction error (P5.5).

    Weighting formula:
        w = 1.0
            + 0.50 * clamp(squad_selection_prob, 0, 1)
            + 1.00 * clamp(captaincy_prob, 0, 1)
            + 0.25 * (max(0, predicted_xp) / 5.0)
            + 0.15 * (max(35, price_tenths) / 100.0)
            + 0.30 * clamp(optimizer_exposure, 0, 1)
            + 0.30 * clamp(transfer_relevance, 0, 1)
    """
    s_prob = max(0.0, min(1.0, float(squad_selection_prob)))
    c_prob = max(0.0, min(1.0, float(captaincy_prob)))
    opt_exp = max(0.0, min(1.0, float(optimizer_exposure)))
    tr_rel = max(0.0, min(1.0, float(transfer_relevance)))
    xp_term = 0.25 * (max(0.0, float(predicted_xp)) / 5.0)
    price_term = 0.15 * (max(35, int(price_tenths)) / 100.0)

    weight = round(1.0 + 0.50 * s_prob + 1.00 * c_prob + xp_term + price_term + 0.30 * opt_exp + 0.30 * tr_rel, 4)
    abs_error = round(abs(float(predicted_xp) - float(actual_points)), 4)
    weighted_error = round(weight * abs_error, 4)

    return {
        "raw_abs_error": abs_error,
        "decision_weight": weight,
        "decision_weighted_error": weighted_error,
    }



def evaluate_season_decisions(
    season: str = "2026/27",
    team_id: str = "default",
    database_path: Path = DATABASE_PATH,
    report_path: Path = EVALUATION_REPORT_PATH,
) -> dict[str, Any]:
    """Aggregate decision evaluation across all finalized gameweeks in the season."""
    decisions = list_decisions(season=season, team_id=team_id, database_path=database_path)

    # Auto-finalize any unfinalized decisions if scores are available AND gameweek is fully completed
    from .scores import is_gameweek_completed
    for d in decisions:
        if d.get("actual_points") is None:
            gw = d["gameweek"]
            if not is_gameweek_completed(gw, database_path=database_path):
                continue
            starters = d["starting_player_ids"]
            bench = d["bench_player_ids"]
            cap_id = d["captain_id"]
            vc_id = d["vice_captain_id"]
            hits = d.get("transfer_hits", 0)
            try:
                from .live_matchday import compute_matchday_lineup_performance
                perf = compute_matchday_lineup_performance(
                    gameweek=gw,
                    starting_ids=starters,
                    bench_ids=bench,
                    captain_id=cap_id,
                    vice_captain_id=vc_id,
                    chip_played=d.get("chip_played"),
                    transfer_hits=hits,
                    database_path=database_path,
                )
                if perf.get("has_match_data"):
                    actual_lineup = perf["net_points"]
                    from .decision_log import record_actual_gameweek_score
                    record_actual_gameweek_score(gw, round(actual_lineup), season=season, team_id=team_id, database_path=database_path)
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
    total_hits = sum(
        0 if is_free_transfers_chip(d.get("chip_played")) else d.get("transfer_hits", 0)
        for d in finalized
    )

    gw_details = []
    total_human_cf = 0.0
    total_model_cf = 0.0
    total_hybrid_cf = 0.0
    total_hindsight_cf = 0.0
    human_wins = 0
    model_wins = 0
    ties = 0
    conf_scores = []

    for d in finalized:
        gw = d["gameweek"]
        pred_xp = d["predicted_lineup_xp"]
        act_pts = float(d["actual_points"])
        delta = round(act_pts - pred_xp, 1)

        gw_eval = evaluate_gameweek_decision(gw, season=season, team_id=team_id, database_path=database_path)
        cf = gw_eval.get("counterfactuals") or {}
        conf = gw_eval.get("decision_confidence") or {}

        if conf.get("confidence_score") is not None:
            conf_scores.append(conf["confidence_score"])

        h_score = cf.get("human_actual_total", act_pts)
        m_score = cf.get("model_actual_total")
        hyb_score = cf.get("hybrid_actual_total", h_score)
        opt_score = cf.get("hindsight_optimal", {}).get("total_points")

        total_human_cf += h_score
        if m_score is not None:
            total_model_cf += m_score
            if h_score > m_score:
                human_wins += 1
            elif m_score > h_score:
                model_wins += 1
            else:
                ties += 1
        total_hybrid_cf += hyb_score
        if opt_score is not None:
            total_hindsight_cf += opt_score

        effective_gw_hits = 0 if is_free_transfers_chip(d.get("chip_played")) else d.get("transfer_hits", 0)
        gw_details.append({
            "gameweek": gw,
            "captain_name": d.get("captain_name"),
            "chip_played": d.get("chip_played"),
            "transfer_hits": effective_gw_hits,
            "predicted_xp": pred_xp,
            "actual_points": act_pts,
            "delta": delta,
            "decision_confidence": conf.get("confidence_score"),
            "confidence_label": conf.get("confidence_label"),
            "model_actual_points": m_score,
            "hindsight_optimal_points": opt_score,
        })

    avg_conf = round(sum(conf_scores) / len(conf_scores), 1) if conf_scores else 50.0

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
        "average_decision_confidence": avg_conf,
        "counterfactual_summary": {
            "total_human_points": round(total_human_cf, 1),
            "total_model_points": round(total_model_cf, 1),
            "total_hybrid_points": round(total_hybrid_cf, 1),
            "total_hindsight_optimal_points": round(total_hindsight_cf, 1),
            "human_vs_model_net_advantage": round(total_human_cf - total_model_cf, 1),
            "human_wins": human_wins,
            "model_wins": model_wins,
            "ties": ties,
            "total_hindsight_gap": round(total_hindsight_cf - total_human_cf, 1),
        },
        "gameweeks": gw_details,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result
