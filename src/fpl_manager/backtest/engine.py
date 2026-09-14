"""Sequential manager simulation and backtest execution engine for V0.7.2."""

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from ..expected_points import ExpectedPointsProjection
from ..historical.models import GameweekOutcome, HistoricalGameweekSnapshot, Position
from ..historical.reconstruction import reconstruct_features_and_project
from ..historical.snapshots import build_historical_snapshot, load_gameweek_outcomes
from ..rules import validate_starting_lineup
from .strategies import BacktestStrategy

LEGAL_FORMATIONS = (
    (3, 5, 2),
    (3, 4, 3),
    (4, 4, 2),
    (4, 3, 3),
    (4, 5, 1),
    (5, 3, 2),
    (5, 4, 1),
    (5, 2, 3),
)


@dataclass(frozen=True, slots=True)
class GameweekDecisionResult:
    """Audit record for a simulated gameweek decision and revealed outcome."""
    gameweek: int
    squad_before: tuple[int, ...]
    transfers: tuple[tuple[int, int], ...]
    squad_after: tuple[int, ...]
    starting_ids: tuple[int, ...]
    bench_ids: tuple[int, ...]
    captain_id: int
    vice_captain_id: int
    predicted_lineup_xp: float
    transfer_hits: int
    gross_points: int
    net_points: int
    autosubs: tuple[tuple[int, int], ...]
    captain_promoted: bool


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Complete season or multi-gameweek simulation report for a strategy."""
    strategy_name: str
    season: str
    start_gw: int
    end_gw: int
    gameweeks_played: int
    total_net_points: int
    total_gross_points: int
    total_hits: int
    total_transfers: int
    final_bank_tenths: int
    history: tuple[GameweekDecisionResult, ...]
    saved_report_path: str | None = None



def select_best_lineup(
    squad_ids: list[int],
    projections: list[ExpectedPointsProjection],
) -> tuple[list[int], list[int], int, int, float]:
    """Select the optimal legal starting 11, captain, vice-captain, and ordered bench."""
    proj_map = {p.player_id: p for p in projections}
    by_pos: dict[Position, list[ExpectedPointsProjection]] = {pos: [] for pos in Position}
    for pid in squad_ids:
        p = proj_map.get(pid)
        if p:
            by_pos[p.position].append(p)

    for pos in by_pos:
        by_pos[pos].sort(key=lambda p: (p.expected_points, p.base_xp_per_match), reverse=True)

    gks = by_pos[Position.GOALKEEPER]
    defs = by_pos[Position.DEFENDER]
    mids = by_pos[Position.MIDFIELDER]
    fwds = by_pos[Position.FORWARD]

    best_starters: list[int] = []
    best_xp = -1.0

    starting_gk = gks[0].player_id if gks else squad_ids[0]

    for d_cnt, m_cnt, f_cnt in LEGAL_FORMATIONS:
        if len(defs) < d_cnt or len(mids) < m_cnt or len(fwds) < f_cnt:
            continue
        cur_starters = [starting_gk]
        cur_starters.extend(p.player_id for p in defs[:d_cnt])
        cur_starters.extend(p.player_id for p in mids[:m_cnt])
        cur_starters.extend(p.player_id for p in fwds[:f_cnt])

        tot_xp = sum(proj_map[pid].expected_points for pid in cur_starters if pid in proj_map)
        if tot_xp > best_xp:
            best_xp = tot_xp
            best_starters = cur_starters

    if not best_starters:
        best_starters = squad_ids[:11]
        best_xp = sum(proj_map[pid].expected_points for pid in best_starters if pid in proj_map)

    # Order starters by xP descending for captaincy
    starters_sorted = sorted(best_starters, key=lambda pid: proj_map.get(pid).expected_points if proj_map.get(pid) else 0.0, reverse=True)
    captain_id = starters_sorted[0]
    vice_captain_id = starters_sorted[1] if len(starters_sorted) > 1 else starters_sorted[0]

    # Bench ordering: reserve GK goes to the end, outfield bench ordered by xP descending
    bench_set = set(squad_ids) - set(best_starters)
    outfield_bench = [pid for pid in squad_ids if pid in bench_set and proj_map.get(pid) and proj_map[pid].position != Position.GOALKEEPER]
    outfield_bench.sort(key=lambda pid: proj_map.get(pid).expected_points if proj_map.get(pid) else 0.0, reverse=True)
    gk_bench = [pid for pid in squad_ids if pid in bench_set and proj_map.get(pid) and proj_map[pid].position == Position.GOALKEEPER]

    ordered_bench = outfield_bench + gk_bench
    return best_starters, ordered_bench, captain_id, vice_captain_id, round(best_xp, 2)


def simulate_autosubs_and_score(
    starting_ids: list[int],
    bench_ids: list[int],
    captain_id: int,
    vice_captain_id: int,
    outcomes: dict[int, GameweekOutcome],
    player_positions: dict[int, Position],
) -> tuple[int, tuple[tuple[int, int], ...], bool]:
    """Calculate matchday score incorporating formation-legal autosubs and captain promotion."""
    active_starters = list(starting_ids)
    remaining_bench = list(bench_ids)
    autosubs: list[tuple[int, int]] = []

    # Autosub simulation
    for idx, s_id in enumerate(list(active_starters)):
        s_outcome = outcomes.get(s_id)
        s_mins = s_outcome.minutes if s_outcome else 0
        if s_mins > 0:
            continue

        s_pos = player_positions.get(s_id, Position.MIDFIELDER)

        # Look for eligible replacement from bench
        eligible_sub_idx = None
        for b_idx, b_id in enumerate(remaining_bench):
            b_outcome = outcomes.get(b_id)
            b_mins = b_outcome.minutes if b_outcome else 0
            if b_mins <= 0:
                continue

            b_pos = player_positions.get(b_id, Position.MIDFIELDER)

            if s_pos == Position.GOALKEEPER:
                if b_pos == Position.GOALKEEPER:
                    eligible_sub_idx = b_idx
                    break
            else:
                if b_pos == Position.GOALKEEPER:
                    continue  # outfield starter cannot be replaced by GK

                # Check if replacing s_id with b_id maintains legal formation (min 3 DEF, 2 MID, 1 FWD)
                test_starters = [pid for pid in active_starters if pid != s_id] + [b_id]
                pos_counts = {Position.DEFENDER: 0, Position.MIDFIELDER: 0, Position.FORWARD: 0}
                for p_id in test_starters:
                    pos = player_positions.get(p_id)
                    if pos in pos_counts:
                        pos_counts[pos] += 1

                if (3 <= pos_counts[Position.DEFENDER] <= 5 and
                    2 <= pos_counts[Position.MIDFIELDER] <= 5 and
                    1 <= pos_counts[Position.FORWARD] <= 3):
                    eligible_sub_idx = b_idx
                    break

        if eligible_sub_idx is not None:
            sub_in_id = remaining_bench.pop(eligible_sub_idx)
            active_starters[idx] = sub_in_id
            autosubs.append((s_id, sub_in_id))

    # Captaincy evaluation
    cap_outcome = outcomes.get(captain_id)
    cap_mins = cap_outcome.minutes if cap_outcome else 0

    vc_outcome = outcomes.get(vice_captain_id)
    vc_mins = vc_outcome.minutes if vc_outcome else 0

    captain_promoted = False
    effective_cap = captain_id
    if cap_mins == 0 and vc_mins > 0:
        effective_cap = vice_captain_id
        captain_promoted = True

    # Gross points calculation
    gross_points = 0
    for s_id in active_starters:
        outcome = outcomes.get(s_id)
        pts = outcome.total_points if outcome else 0
        if s_id == effective_cap:
            gross_points += pts * 2
        else:
            gross_points += pts

    return gross_points, tuple(autosubs), captain_promoted


def initialize_greedy_squad(
    snapshot: HistoricalGameweekSnapshot,
    projections: list[ExpectedPointsProjection],
    budget_tenths: int = 1000,
) -> tuple[list[int], dict[int, int], int]:
    """Build a legal starting 15-player squad (2 GKP, 5 DEF, 5 MID, 3 FWD, max 3 per club) within budget."""
    target_formation = {
        Position.GOALKEEPER: 2,
        Position.DEFENDER: 5,
        Position.MIDFIELDER: 5,
        Position.FORWARD: 3,
    }

    selected_ids: list[int] = []
    purchase_prices: dict[int, int] = {}
    team_counts: dict[int, int] = {}
    spent = 0

    by_pos: dict[Position, list[ExpectedPointsProjection]] = {pos: [] for pos in Position}
    for p in projections:
        by_pos[p.position].append(p)

    for pos in by_pos:
        # Sort by xP per cost efficiency
        by_pos[pos].sort(key=lambda p: (p.expected_points / max(40, p.price_tenths), p.expected_points), reverse=True)

    for pos, needed in target_formation.items():
        candidates = by_pos[pos]
        picked = 0
        for cand in candidates:
            if picked >= needed:
                break
            if cand.player_id in selected_ids:
                continue
            if team_counts.get(cand.team_id, 0) >= 3:
                continue
            remaining_slots = 15 - len(selected_ids) - 1
            if spent + cand.price_tenths + remaining_slots * 40 > budget_tenths:
                continue

            selected_ids.append(cand.player_id)
            purchase_prices[cand.player_id] = cand.price_tenths
            team_counts[cand.team_id] = team_counts.get(cand.team_id, 0) + 1
            spent += cand.price_tenths
            picked += 1

        # Fallback if budget/filters were too strict: pick cheapest valid candidates
        if picked < needed:
            cheapest = sorted(candidates, key=lambda p: p.price_tenths)
            for cand in cheapest:
                if picked >= needed:
                    break
                if cand.player_id in selected_ids:
                    continue
                if team_counts.get(cand.team_id, 0) >= 3:
                    continue
                selected_ids.append(cand.player_id)
                purchase_prices[cand.player_id] = cand.price_tenths
                team_counts[cand.team_id] = team_counts.get(cand.team_id, 0) + 1
                spent += cand.price_tenths
                picked += 1

    remaining_bank = budget_tenths - spent
    return selected_ids, purchase_prices, remaining_bank


def run_sequential_simulation(
    season_dir: Path,
    strategy: BacktestStrategy,
    initial_squad_ids: list[int] | None = None,
    start_gw: int = 1,
    end_gw: int = 38,
    save_report: bool = False,
    output_path: Path | None = None,
    predictor_version: str = "v0.8",
) -> SimulationResult:
    """Replay a complete historical season as a sequential deterministic FPL manager simulation."""
    # 1. Initialize squad at start_gw
    init_snap = build_historical_snapshot(season_dir, start_gw)
    init_projs = reconstruct_features_and_project(init_snap, predictor_version=predictor_version)

    if initial_squad_ids is None:
        squad_ids, purchase_prices, bank = initialize_greedy_squad(init_snap, init_projs, budget_tenths=1000)
    else:
        squad_ids = list(initial_squad_ids)
        proj_map = {p.player_id: p.price_tenths for p in init_projs}
        purchase_prices = {pid: proj_map.get(pid, 50) for pid in squad_ids}
        bank = 1000 - sum(purchase_prices.values())

    free_transfers = 1
    total_net_points = 0
    total_gross_points = 0
    total_hits = 0
    total_transfers = 0
    history: list[GameweekDecisionResult] = []

    # 2. Sequential simulation loop
    for gw in range(start_gw, end_gw + 1):
        snapshot = build_historical_snapshot(season_dir, gw)
        projections = reconstruct_features_and_project(snapshot, predictor_version=predictor_version)
        proj_map = {p.player_id: p for p in projections}
        player_positions = {p.player_id: p.position for p in projections}

        squad_before = list(squad_ids)

        # Strategy decides transfers
        chosen_transfers = strategy.decide_transfers(
            current_squad_ids=squad_ids,
            purchase_prices=purchase_prices,
            bank_tenths=bank,
            free_transfers=free_transfers,
            snapshot=snapshot,
            projections=projections,
        )

        # Apply transfers
        num_transfers = len(chosen_transfers)
        hits = max(0, num_transfers - free_transfers) * 4
        rem_ft = max(0, free_transfers - num_transfers)
        free_transfers = min(5, rem_ft + 1)  # roll 1 free transfer for next week (max 5 in modern FPL rules)

        for out_id, in_id in chosen_transfers:
            out_p = proj_map.get(out_id)
            in_p = proj_map.get(in_id)
            if out_p and in_p and out_id in squad_ids:
                cur_out_price = out_p.price_tenths
                bought_price = purchase_prices.get(out_id, cur_out_price)
                sell_price = bought_price + max(0, (cur_out_price - bought_price) // 2)

                bank += sell_price
                bank -= in_p.price_tenths

                squad_ids.remove(out_id)
                squad_ids.append(in_id)
                purchase_prices[in_id] = in_p.price_tenths
                if out_id in purchase_prices:
                    del purchase_prices[out_id]

        total_transfers += num_transfers
        total_hits += hits

        # Lineup selection
        starters, bench, cap_id, vc_id, pred_xp = select_best_lineup(squad_ids, projections)

        # Matchday execution
        outcomes = load_gameweek_outcomes(season_dir, gw)
        gross_pts, autosubs, cap_promoted = simulate_autosubs_and_score(
            starters, bench, cap_id, vc_id, outcomes, player_positions
        )
        net_pts = gross_pts - hits
        total_gross_points += gross_pts
        total_net_points += net_pts

        history.append(
            GameweekDecisionResult(
                gameweek=gw,
                squad_before=tuple(squad_before),
                transfers=tuple(chosen_transfers),
                squad_after=tuple(squad_ids),
                starting_ids=tuple(starters),
                bench_ids=tuple(bench),
                captain_id=cap_id,
                vice_captain_id=vc_id,
                predicted_lineup_xp=pred_xp,
                transfer_hits=hits,
                gross_points=gross_pts,
                net_points=net_pts,
                autosubs=autosubs,
                captain_promoted=cap_promoted,
            )
        )

    target_path_str: str | None = None
    if save_report:
        from .reporting import build_backtest_report_path, save_backtest_report

        season_name = season_dir.name
        strategy_slug = strategy.name.lower().replace(" ", "_")
        target_path = output_path or build_backtest_report_path(
            "decisions",
            season_name,
            strategy_slug,
            start_gw,
            end_gw,
        )
        target_path_str = str(target_path)

    result = SimulationResult(
        strategy_name=strategy.name,
        season=snapshot.season,
        start_gw=start_gw,
        end_gw=end_gw,
        gameweeks_played=(end_gw - start_gw + 1),
        total_net_points=total_net_points,
        total_gross_points=total_gross_points,
        total_hits=total_hits,
        total_transfers=total_transfers,
        final_bank_tenths=bank,
        history=tuple(history),
        saved_report_path=target_path_str,
    )

    if save_report and target_path_str is not None:
        from .reporting import format_decision_report, save_backtest_report

        report_text = format_decision_report(
            [result],
            season=season_dir.name,
            start_gw=start_gw,
            end_gw=end_gw,
        )
        save_backtest_report(report_text, Path(target_path_str))

    return result


def run_decision_backtest(
    season_dir: Path,
    strategy: str | BacktestStrategy | list[BacktestStrategy] = "all",
    start_gw: int = 1,
    end_gw: int = 10,
    max_transfers: int = 1,
    initial_squad_ids: list[int] | None = None,
    save_report: bool = False,
    output_path: Path | None = None,
    predictor_version: str = "v0.8",
) -> list[SimulationResult]:
    """Execute sequential manager decision simulations across one or more strategies.

    Args:
        season_dir: Path to ingested historical season (e.g. data/historical/2023-24).
        strategy: Strategy selector ("all", "notransfer", "simplexp", "optimizer" or BacktestStrategy).
        start_gw: First simulated gameweek (default: 1).
        end_gw: Final simulated gameweek (default: 10).
        max_transfers: Max transfer branch limit for OptimizerStrategy (default: 1).
        initial_squad_ids: Optional fixed starting squad of 15 player IDs.
        save_report: Whether to save formatted Markdown decision report to reports/backtests/.
        output_path: Optional custom path for the saved Markdown report.
        predictor_version: Prediction model version to evaluate ("v0.7" or "v0.8").

    Returns:
        List of SimulationResult objects for each evaluated strategy.
    """
    from .reporting import build_backtest_report_path, format_decision_report, save_backtest_report
    from .strategies import NoTransferStrategy, OptimizerStrategy, SimpleXpStrategy

    strategies: list[BacktestStrategy] = []
    strategy_label = "all"

    if isinstance(strategy, str):
        strat_key = strategy.lower().strip()
        strategy_label = strat_key
        if strat_key in ("all", "notransfer"):
            strategies.append(NoTransferStrategy())
        if strat_key in ("all", "simplexp"):
            strategies.append(SimpleXpStrategy())
        if strat_key in ("all", "optimizer"):
            strategies.append(OptimizerStrategy(max_transfers=max_transfers))
        if not strategies:
            raise ValueError(f"Unknown strategy name: '{strategy}'. Supported: all, notransfer, simplexp, optimizer")
    elif isinstance(strategy, BacktestStrategy):
        strategies.append(strategy)
        strategy_label = strategy.name.lower().replace(" ", "_")
    elif isinstance(strategy, (list, tuple)):
        strategies.extend(strategy)
        strategy_label = "_".join(s.name.lower().replace(" ", "_") for s in strategies) if len(strategies) > 1 else strategies[0].name.lower().replace(" ", "_")
    else:
        raise ValueError(f"Unsupported strategy argument type: {type(strategy)}")

    simulations: list[SimulationResult] = []
    for s in strategies:
        sim = run_sequential_simulation(
            season_dir=season_dir,
            strategy=s,
            initial_squad_ids=initial_squad_ids,
            start_gw=start_gw,
            end_gw=end_gw,
            save_report=False,
            predictor_version=predictor_version,
        )
        simulations.append(sim)

    if save_report and simulations:
        season_name = season_dir.name
        report_text = format_decision_report(
            simulations,
            season=season_name,
            start_gw=start_gw,
            end_gw=end_gw,
        )
        target_path = output_path or build_backtest_report_path(
            "decisions",
            season_name,
            strategy_label,
            start_gw,
            end_gw,
        )
        save_backtest_report(report_text, target_path)

        simulations = [
            SimulationResult(
                strategy_name=s.strategy_name,
                season=s.season,
                start_gw=s.start_gw,
                end_gw=s.end_gw,
                gameweeks_played=s.gameweeks_played,
                total_net_points=s.total_net_points,
                total_gross_points=s.total_gross_points,
                total_hits=s.total_hits,
                total_transfers=s.total_transfers,
                final_bank_tenths=s.final_bank_tenths,
                history=s.history,
                saved_report_path=str(target_path),
            )
            for s in simulations
        ]

    return simulations



def compare_simulations(sim_a: SimulationResult, sim_b: SimulationResult) -> dict[str, Any]:
    """Perform a paired comparative analysis between two simulation runs."""
    if len(sim_a.history) != len(sim_b.history):
        raise ValueError("Cannot compare simulations with different gameweek counts.")

    gw_diffs = [b.net_points - a.net_points for a, b in zip(sim_a.history, sim_b.history)]
    b_wins = sum(1 for d in gw_diffs if d > 0)
    a_wins = sum(1 for d in gw_diffs if d < 0)
    ties = sum(1 for d in gw_diffs if d == 0)

    mean_diff = round(sum(gw_diffs) / len(gw_diffs), 2) if gw_diffs else 0.0

    return {
        "strategy_a": sim_a.strategy_name,
        "strategy_b": sim_b.strategy_name,
        "gameweeks": len(gw_diffs),
        "total_net_points_a": sim_a.total_net_points,
        "total_net_points_b": sim_b.total_net_points,
        "net_difference": sim_b.total_net_points - sim_a.total_net_points,
        "gross_difference": sim_b.total_gross_points - sim_a.total_gross_points,
        "hits_difference": sim_b.total_hits - sim_a.total_hits,
        "transfers_difference": sim_b.total_transfers - sim_a.total_transfers,
        "strategy_b_wins": b_wins,
        "strategy_a_wins": a_wins,
        "ties": ties,
        "mean_gw_difference": mean_diff,
        "gw_differences": gw_diffs,
    }

