"""Bounded mechanical regression tests; never regenerate research artifacts."""

from dataclasses import replace
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from fpl_manager.expected_points import (
    project_gameweek,
    project_multi_gameweek_profiles,
    project_player_gameweek,
)
from fpl_manager.model_registry import get_model_metadata, reconstruct_historical_prediction
from fpl_manager.models import Position
from fpl_manager.optimizer import (
    PlayerOptInfo,
    get_player_profile_value,
    solve_transfers,
    solve_transfers_exact_reference,
)
from fpl_manager.storage import SnapshotStore


def _player(pid, pos=Position.MIDFIELDER, xp=1.0, price=50, dead=False):
    return PlayerOptInfo(
        id=pid, name=f"P{pid}", position=pos, team_id=pid, team_short=f"T{pid}",
        price_tenths=price, status="a", total_points=pid, expected_points=xp,
        xp_floor=xp * 0.6, xp_ceiling=xp * 1.8, standard_deviation=xp * 0.2,
        is_long_term_unavailable=dead,
    )


def _squad():
    positions = [Position.GOALKEEPER] * 2 + [Position.DEFENDER] * 5
    positions += [Position.MIDFIELDER] * 5 + [Position.FORWARD] * 3
    return [_player(pid, pos) for pid, pos in enumerate(positions, 1)]


def test_dead_capital_bonus_is_in_pruning_bound():
    squad = _squad()
    squad[12] = _player(13, Position.FORWARD, xp=0, price=40, dead=True)
    squad[13] = _player(14, Position.FORWARD, xp=0, price=90, dead=True)
    squad[14] = _player(15, Position.FORWARD, xp=50)
    pool = [_player(101, Position.FORWARD, xp=10, price=40)]
    args = dict(
        num_transfers=1, squad_players=squad, candidate_pool=pool, bank_tenths=0,
        free_transfers=1, selling_prices={p.id: p.price_tenths for p in squad},
        fdr_map={}, dead_capital_weight=3.0,
    )
    oracle = solve_transfers_exact_reference(**args)
    results, _ = solve_transfers(**args, ticker_map={}, max_results=1)
    assert results[0]["outgoing"][0]["id"] == oracle["outgoing"][0]["id"] == 14
    assert results[0]["score"] == oracle["score"] == 37


@pytest.mark.parametrize("k", range(1, 6))
@pytest.mark.parametrize("risk", ["neutral", "floor", "ceiling", "defend_lead", "chase"])
@pytest.mark.parametrize("reverse,limit,heap_size", [(False, 6, 1), (True, 6, 3), (True, 3, 1)])
def test_bnb_matches_bounded_independent_oracle(k, risk, reverse, limit, heap_size):
    squad = _squad()
    for i in range(7, 12):
        squad[i] = replace(squad[i], price_tenths=40 + 10 * (i - 7),
                           expected_points=float(i - 6), is_long_term_unavailable=i % 2 == 0)
    pool = [_player(101 + i, xp=12 - i * 0.37, price=45 + i * 9) for i in range(6)]
    limit = max(k, limit)
    fdr = {p.team_short: 1.23 + p.id % 5 * 0.71 for p in squad + pool}
    retained = sorted(pool, key=lambda p: (
        round(get_player_profile_value(p, risk) - 0.1 * fdr[p.team_short] / k, 6),
        get_player_profile_value(p, risk), p.expected_points, -fdr[p.team_short],
        p.total_points, -p.id,
    ), reverse=True)[:limit]
    args = dict(num_transfers=k, squad_players=squad, bank_tenths=20, free_transfers=1,
                selling_prices={p.id: p.price_tenths - 3 for p in squad},
                fdr_map=fdr, dead_capital_weight=3.0, risk_profile=risk)
    oracle = solve_transfers_exact_reference(**args, candidate_pool=retained)
    results, _ = solve_transfers(
        **args, candidate_pool=list(reversed(pool)) if reverse else pool,
        ticker_map={}, cand_limit=limit, max_results=heap_size,
    )
    assert bool(results) == bool(oracle)
    if oracle:
        assert results[0]["score"] == oracle["score"]
        assert {p["id"] for p in results[0]["outgoing"]} == {p["id"] for p in oracle["outgoing"]}
        assert {p["id"] for p in results[0]["incoming"]} == {p["id"] for p in oracle["incoming"]}


@pytest.fixture
def projection_db(tmp_path):
    path = tmp_path / "projection.sqlite3"
    SnapshotStore(path).save_snapshot({
        "teams": [{"id": 1, "name": "A", "short_name": "A"}, {"id": 2, "name": "B", "short_name": "B"}],
        "elements": [{"id": 1, "web_name": "P", "element_type": 3, "team": 1,
                      "now_cost": 90, "status": "a", "minutes": 900, "starts": 10,
                      "total_points": 40, "expected_goals_per_90": 0.5,
                      "expected_assists_per_90": 0.2}],
    }, [
        {"id": i, "event": gw, "team_h": 1, "team_a": 2, "team_h_difficulty": 2,
         "team_a_difficulty": 4, "finished": gw == 1, "kickoff_time": "2025-08-01T12:00:00Z"}
        for i, gw in enumerate([1, 2, 4, 4], 1)
    ], "2025-08-01T00:00:00Z")
    return path


@pytest.mark.parametrize("version", ["v0.7", "v08", "v09", "v1.0.1", "v0.9_raw", "v0.9_part_v0.8_comp"])
@pytest.mark.parametrize("gws", [[2], [3], [4], [2, 3, 4]])
def test_multi_gw_uses_single_projection_pipeline(projection_db, version, gws):
    singles = [project_gameweek(gw, database_path=projection_db, predictor_version=version)[0] for gw in gws]
    multi = project_multi_gameweek_profiles(gws, database_path=projection_db, predictor_version=version)[1]
    assert multi.expected_points == round(sum(p.expected_points for p in singles), 2)
    assert multi.xp_floor == round(sum(p.xp_floor for p in singles), 2)
    assert multi.xp_ceiling == round(sum(p.xp_ceiling for p in singles), 2)
    assert multi.expected_minutes == round(sum(p.expected_minutes for p in singles), 1)
    expected_sd = round(math.sqrt(sum(f.variance for p in singles for f in p.fixtures)), 2)
    assert multi.standard_deviation == pytest.approx(expected_sd, abs=0.01)
    assert multi.gw_breakdown_xp == {p.gameweek: p.expected_points for p in singles}
    if len(gws) == 1:
        assert multi.standard_deviation == singles[0].standard_deviation
    if gws == [3]:
        assert multi.expected_minutes == multi.expected_points == multi.standard_deviation == 0
    if gws == [4]:
        assert multi.fixtures_count == 2
        assert multi.expected_minutes == round(sum(f.expected_minutes for f in singles[0].fixtures), 1)


@pytest.mark.parametrize("alias,identity", [("v13", "v1.3.0"), ("gbdt", "v1.3.0"),
                                          ("v09", "v0.9.1"), ("v08", "v0.8.0"), ("v07", "v0.7.0")])
def test_registry_resolves_explicit_aliases(alias, identity):
    assert get_model_metadata(alias, gameweek=2).model_version == identity


def test_registry_rejects_unknown_identity():
    with pytest.raises(ValueError, match="predictor"):
        get_model_metadata("unreleased-model", gameweek=2)


def test_reconstruction_rejects_mislabeled_predictor():
    snapshot = SimpleNamespace(gameweek=2, season="2025-26", deadline_time="2025-08-01")
    metadata = get_model_metadata("v1.3", gameweek=2)
    with pytest.raises(ValueError, match="match"):
        reconstruct_historical_prediction(snapshot, metadata, {"predictor_version": "v1.0"})
    with pytest.raises(ValueError, match="match"):
        reconstruct_historical_prediction(
            snapshot, {**metadata.to_dict(), "predictor_version": "v09"},
        )
    mislabeled = SimpleNamespace(model_metadata=get_model_metadata("v1.0", gameweek=2).to_dict())
    with patch("fpl_manager.historical.reconstruction.reconstruct_features_and_project",
               return_value=[mislabeled]), pytest.raises(ValueError, match="identity"):
        reconstruct_historical_prediction(snapshot, metadata)


def test_gbdt_participation_is_not_overwritten_and_reconstruction_uses_identity():
    part = SimpleNamespace(expected_minutes=73.0, p_start=0.81, prob_60_plus=0.8,
                           p_sub=0.1, p_play=0.91, role_category="rotation")
    predictor = SimpleNamespace(
        predict_participation_from_vector=lambda *args: part,
        predict_threat=lambda *args: (0.6, 0.2, 0.3),
    )
    kwargs = dict(player_id=1, web_name="P", position=Position.MIDFIELDER, team_id=1,
                  team_short="A", price_tenths=90, status="a", total_points=20,
                  finished_matches=4, gameweek=5, team_fixtures_in_gw=[
                      {"opponent_id": 2, "opponent_short": "B", "is_home": True, "fdr": 2}])
    with patch("fpl_manager.ml.HAS_SKLEARN", True), patch(
        "fpl_manager.ml.get_canonical_gbdt_predictor", return_value=predictor
    ), patch("fpl_manager.ml.features.build_feature_vector", return_value=[0.0] * 25):
        proj = project_player_gameweek(**kwargs, predictor_version="v13")
    assert proj.expected_minutes == 73
    assert proj.start_probability == 0.81
    assert proj.model_metadata["model_version"] == "v1.3.0"
    snapshot = SimpleNamespace(gameweek=5, season="2025-26", deadline_time="2025-08-01")
    with patch("fpl_manager.historical.reconstruction.reconstruct_features_and_project",
               return_value=[proj]) as reconstruct:
        reconstruct_historical_prediction(snapshot, proj.model_metadata)
    assert reconstruct.call_args.kwargs["predictor_version"] == "v1.3"


def test_required_gbdt_never_silently_falls_back(projection_db):
    with patch("fpl_manager.ml.HAS_SKLEARN", False):
        with pytest.raises(RuntimeError, match="GBDT|scikit-learn"):
            project_multi_gameweek_profiles([2], database_path=projection_db, predictor_version="v1.3")
    with patch("fpl_manager.ml.HAS_SKLEARN", True), patch(
        "fpl_manager.ml.get_canonical_gbdt_predictor", side_effect=FileNotFoundError("missing artifact")
    ):
        with pytest.raises(RuntimeError, match="missing artifact"):
            project_multi_gameweek_profiles([2], database_path=projection_db, predictor_version="gbdt")


def test_gbdt_horizon_aggregates_single_pipeline_without_loading_artifacts(projection_db):
    part = SimpleNamespace(expected_minutes=73, p_start=0.81, prob_60_plus=0.8,
                           p_sub=0.1, p_play=0.91, role_category="rotation")
    predictor = SimpleNamespace(
        predict_participation_from_vector=lambda *args: part,
        predict_threat=lambda *args: (0.6, 0.2, 0.3),
    )
    with patch("fpl_manager.ml.HAS_SKLEARN", True), patch(
        "fpl_manager.ml.get_canonical_gbdt_predictor", return_value=predictor
    ), patch("fpl_manager.ml.features.build_feature_vector", return_value=[0.0] * 25):
        singles = [project_gameweek(gw, database_path=projection_db, predictor_version="v1.3.0")[0]
                   for gw in [2, 3, 4]]
        profiles = project_multi_gameweek_profiles([2, 3, 4], database_path=projection_db,
                                                   predictor_version="v1.3-canonical")
    profile = profiles[1]
    assert profile.expected_points == round(sum(p.expected_points for p in singles), 2)
    assert profile.xp_floor == round(sum(p.xp_floor for p in singles), 2)
    assert profile.xp_ceiling == round(sum(p.xp_ceiling for p in singles), 2)
    assert profile.expected_minutes == 219
    assert [p.expected_minutes for p in singles] == [73, 0, 146]


def _historical_snapshot(gameweek=2):
    from fpl_manager.historical.models import HistoricalGameweekSnapshot, HistoricalPlayerState
    player = HistoricalPlayerState(
        player_id=1, web_name="P", position=Position.MIDFIELDER, team_id=1,
        price_tenths=90, status="a", chance_of_playing_next_round=100,
        chance_of_playing_this_round=100, total_points=8, minutes=90, starts=1,
        expected_goals=0.5, expected_assists=0.2, expected_goal_involvements=0.7,
        expected_goals_conceded=1, expected_goals_per_90=0.5,
        expected_assists_per_90=0.2, expected_goals_conceded_per_90=1,
        clean_sheets_per_90=0.2, bps=20, ict_index=5, form=8, points_per_game=8,
        selected_by_percent=25, news="",
    )
    return HistoricalGameweekSnapshot(
        season="2025-26", gameweek=gameweek, deadline_time="2025-08-01",
        finished_gameweeks=gameweek - 1, players=(player,),
        teams=({"team_id": 1, "short_name": "A"}, {"team_id": 2, "short_name": "B"}),
        fixtures=(),
    )


def test_forward_projection_preserves_gbdt_and_rejects_mixed_identity(tmp_path):
    from fpl_manager.backtest.decision_engine import _get_forward_projections
    snapshot = _historical_snapshot()
    projection = SimpleNamespace(
        player_id=1, expected_points=7, model_metadata=get_model_metadata("v13", gameweek=2).to_dict()
    )
    fixtures = [{"team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3}]
    with patch("fpl_manager.backtest.decision_engine.get_historical_fixtures_for_gw", return_value=fixtures), patch(
        "fpl_manager.expected_points.project_player_gameweek", return_value=SimpleNamespace(expected_points=11)
    ) as project:
        result = _get_forward_projections(snapshot, [projection], horizon=3, season_dir=tmp_path)
        assert result[3][1] == result[4][1] == 11
        assert all(c.kwargs["predictor_version"] == "v1.3" for c in project.call_args_list)
        assert all(c.kwargs["strict_predictor"] for c in project.call_args_list)
        assert all(c.kwargs["eval_season"] == "2025-26" for c in project.call_args_list)
        mixed = SimpleNamespace(
            player_id=2, expected_points=5, model_metadata=get_model_metadata("v09", gameweek=2).to_dict()
        )
        with pytest.raises(ValueError, match="identity"):
            _get_forward_projections(snapshot, [projection, mixed], horizon=3, season_dir=tmp_path)


@pytest.mark.parametrize("purchase,current,corrected,legacy", [
    (60, 53, 53, 60), (60, 60, 60, 60), (60, 65, 62, 62), (60, 66, 63, 63),
])
def test_decision_pricing_is_canonical_and_legacy_requires_explicit_scope(purchase, current, corrected, legacy):
    from fpl_manager.backtest.decision_engine import _execution_selling_price
    from fpl_manager.execution import execution_scope
    assert _execution_selling_price(purchase, current) == corrected
    with execution_scope("v146"):
        assert _execution_selling_price(purchase, current) == legacy
    assert _execution_selling_price(purchase, current) == corrected


def _regret_case():
    from fpl_manager.backtest.optimizer_ablation import DecisionEngineAblation
    from fpl_manager.expected_points import ExpectedPointsProjection
    projections = []
    for player in _squad() + [_player(101, xp=12), _player(102, xp=8)]:
        projections.append(ExpectedPointsProjection(
            player_id=player.id, web_name=player.name, position=player.position,
            team_id=player.team_id, team_short=player.team_short,
            price_tenths=player.price_tenths, status="a", availability_pct=100,
            base_xp_per_match=player.expected_points, gameweek=2, fixtures=(),
            expected_points=player.expected_points, play_probability=1,
        ))
    engine = DecisionEngineAblation("B0")
    engine.horizon = 1
    return engine, projections


def test_regret_keeps_signed_components_and_measured_total():
    from fpl_manager.backtest.optimizer_ablation import compute_gameweek_decision_regret
    engine, projections = _regret_case()
    engine.decide_transfers = lambda **kwargs: [(8, 102)]
    engine.select_lineup = lambda ids, projs: (
        ([102] if 102 in ids else [101] if 101 in ids else [8]), [], 1, 2, ""
    )
    with patch("fpl_manager.optimizer.solve_transfers", return_value=([
        {"outgoing": [{"id": 8}], "incoming": [{"id": 101}]},
    ], 1)):
        record, _ = compute_gameweek_decision_regret(
            "2025-26", 2, "B0", engine, list(range(1, 16)), {}, 0, 1,
            _historical_snapshot(), projections, {101: 2, 102: 40},
        )
    assert record.realized_hindsight_points == record.realized_selected_points == 40
    assert record.prediction_regret == 38
    assert record.optimizer_regret == -38
    assert record.total_decision_regret == 0
    assert record.prediction_regret + record.optimizer_regret == record.total_decision_regret
    assert record.to_dict()["action_universe"] == "heuristic_one_transfer_shortlist_plus_selected"
    assert not record.to_dict()["is_exhaustive"]
    assert record.to_dict()["action_count"] == 3


def test_regret_rejects_unsupported_shortlist_multitransfers():
    from fpl_manager.backtest.optimizer_ablation import compute_gameweek_decision_regret
    engine, projections = _regret_case()
    with pytest.raises(ValueError, match="one.transfer|exact"):
        compute_gameweek_decision_regret(
            "2025-26", 2, "B0", engine, list(range(1, 16)), {}, 0, 1,
            _historical_snapshot(), projections, {}, max_transfers=2,
        )


def _chip_candidate(gw, ev=5, blocked=False):
    return dict(gameweek=gw, gw_type="STANDARD", rating=ev, immediate_ev=ev,
                future_opportunity=10, net_utility=ev - 10, confidence=0.9,
                reasoning="Guard blocked" if blocked else "Eligible opportunity cost",
                blocked=blocked, eligible=not blocked)


def test_chip_schedule_never_selects_blocked_and_negative_utility_is_not_a_block():
    from fpl_manager.chip_strategy import _schedule_chip_candidates
    schedule, unscheduled = _schedule_chip_candidates(
        ["wildcard", "benchboost"],
        {"wildcard": [_chip_candidate(2, 2, True)],
         "benchboost": [_chip_candidate(3, 1)]},
    )
    assert [(s["chip"], s["gameweek"]) for s in schedule] == [("benchboost", 3)]
    assert "wildcard" in unscheduled


def test_chip_matching_finds_conflict_free_dates_instead_of_greedy_collision():
    from fpl_manager.chip_strategy import _schedule_chip_candidates
    schedule, unscheduled = _schedule_chip_candidates(
        ["freehit", "triplecaptain", "wildcard"],
        {"freehit": [_chip_candidate(5, 10), _chip_candidate(6, 9)],
         "triplecaptain": [_chip_candidate(5, 8)],
         "wildcard": [_chip_candidate(9, 7), _chip_candidate(7, 11)]},
    )
    assert not unscheduled
    assert {s["chip"]: s["gameweek"] for s in schedule} == {
        "freehit": 6, "triplecaptain": 5, "wildcard": 9,
    }


def test_chip_schedule_recent_wildcard_cooldown_and_all_blocked():
    from fpl_manager.chip_strategy import _schedule_chip_candidates
    schedule, unscheduled = _schedule_chip_candidates(
        ["freehit", "wildcard", "benchboost"],
        {"freehit": [_chip_candidate(6), _chip_candidate(8)],
         "wildcard": [_chip_candidate(7)],
         "benchboost": [_chip_candidate(6, blocked=True)]}, recent_wildcard_gw=5,
    )
    assert [(s["chip"], s["gameweek"]) for s in schedule] == [("freehit", 8)]
    assert set(unscheduled) == {"wildcard", "benchboost"}


def test_live_chip_adapter_propagates_early_wildcard_guard(projection_db):
    from fpl_manager.chip_strategy import optimizer_chip_candidates
    from fpl_manager.simulation.chip_optimizer import ChipOpportunityValue, GameweekFixtureTopology
    opp = ChipOpportunityValue("wildcard", 2, 2, 18, -16, 0.9, "Early WC guard")
    topo = {2: GameweekFixtureTopology(2, 10)}
    with patch("fpl_manager.simulation.chip_optimizer.extract_season_fixture_topology", return_value=topo), patch(
        "fpl_manager.simulation.chip_optimizer.ChipOpportunityOptimizer.evaluate_all_opportunities",
        return_value={"wildcard": opp},
    ), patch("fpl_manager.chip_strategy.evaluate_chip_candidates", return_value={}):
        candidates = optimizer_chip_candidates(
            2, 2, ["wildcard"], {}, database_path=projection_db,
        )
    assert candidates["wildcard"][0]["blocked"]
    assert not candidates["wildcard"][0]["eligible"]
    assert candidates["wildcard"][0]["blocked_reason"] == "Early WC guard"


@pytest.mark.parametrize("gw,ft,count,cap,chip,expected", [
    (1, 1, 0, 5, None, (0, 1)), (1, 1, 5, 5, None, (0, 1)),
    (2, 1, 0, 5, None, (0, 2)), (4, 2, 0, 2, None, (0, 2)),
    (4, 4, 0, 5, None, (0, 5)), (4, 1, 3, 5, None, (2, 1)),
    (4, 3, 2, 5, None, (0, 2)), (4, 1, 3, 2, "wildcard_1", (0, 1)),
    (4, 1, 3, 5, "free_hit", (0, 1)), (4, 1, 3, 5, "bench_boost", (2, 1)),
])
def test_shared_planner_execution_transition(gw, ft, count, cap, chip, expected):
    from fpl_manager.planner import planner_transfer_transition
    assert planner_transfer_transition(gw, ft, count, max_free_transfers=cap, active_chip=chip) == expected


@pytest.fixture
def planning_db(tmp_path):
    path = tmp_path / "planning.sqlite3"
    squad = _squad()
    SnapshotStore(path).save_snapshot({
        "teams": [{"id": i, "name": f"T{i}", "short_name": f"T{i}"} for i in range(1, 17)],
        "elements": [{"id": p.id, "web_name": p.name, "element_type": p.position.value,
                      "team": p.team_id, "now_cost": p.price_tenths, "status": "a",
                      "minutes": 900, "starts": 10, "total_points": 40} for p in squad],
    }, [{"id": gw * 100 + i, "event": gw, "team_h": i, "team_a": i + 1,
         "team_h_difficulty": 3, "team_a_difficulty": 3,
         "finished": False, "kickoff_time": "2025-08-01T12:00:00Z"}
        for gw in range(1, 7) for i in range(1, 17, 2)], "2025-08-01T00:00:00Z")
    return path


@pytest.mark.parametrize("risk", ["neutral", "floor", "ceiling", "defend_lead", "chase"])
def test_live_planner_gw1_matches_historical_and_report_none_is_pure(planning_db, risk):
    from fpl_manager.planner import generate_multi_gameweek_plan, generate_historical_multi_gameweek_plan
    from fpl_manager.suggest_transfers import PlayerInfo
    ids = list(range(1, 16))
    with patch.object(Path, "write_text", side_effect=AssertionError("query exported a report")):
        live = generate_multi_gameweek_plan(
            database_path=planning_db, start_gw=1, initial_squad_ids=ids,
            initial_bank_tenths=0, horizon=2, allow_hits=False, risk_profile=risk,
            report_path=None,
        )
    players = {p.id: PlayerInfo(
        id=p.id, name=p.name, position=p.position, team_id=p.team_id,
        team_short=p.team_short, price_tenths=50, status="a", total_points=40,
        expected_points=5, gw_xp=5, xp_floor=3, xp_ceiling=8,
        gw_breakdown_xp={1: 5, 2: 5},
    ) for p in _squad()}
    sim = SimpleNamespace(
        session_id="bounded-parity", current_gw=1, season="2025-26", season_dir=planning_db.parent,
        get_current_snapshot=_historical_snapshot, squad_ids=ids, bank_tenths=0,
        purchase_prices_tenths={pid: 50 for pid in ids}, free_transfers=1,
        max_free_transfers=5, active_chip=None, transfers_staged=[],
    )
    with patch("fpl_manager.historical.snapshots.load_historical_players_meta", return_value=(players, {})), patch(
        "fpl_manager.historical.snapshots.analyze_historical_fixtures", return_value=({}, {})
    ):
        historical = generate_historical_multi_gameweek_plan(
            sim, horizon=2, allow_hits=False, risk_profile=risk, report_path=None,
        )
    live_steps = live["best_plan"]["gameweek_steps"]
    hist_steps = historical["best_plan"]["gameweek_steps"]
    assert [s["free_transfers_after"] for s in live_steps] == [1, 2]
    assert [s["free_transfers_after"] for s in hist_steps] == [1, 2]


def test_suggestion_and_chip_reports_can_be_disabled(planning_db):
    from fpl_manager.suggest_transfers import suggest_strategic_squad
    from fpl_manager.chip_strategy import recommend_chip_strategy
    candidate = SimpleNamespace(to_dict=lambda: {}, bank_remaining_tenths=0)
    with patch.object(Path, "write_text", side_effect=AssertionError("query exported a report")), patch(
        "fpl_manager.suggest_transfers.solve_strategic_squad", return_value=candidate
    ):
        suggest_strategic_squad(database_path=planning_db, report_path=None, generate_all_candidates=False)
        result = recommend_chip_strategy(
            squad_path=planning_db.parent / "absent-squad.json", database_path=planning_db,
            start_gw=2, end_gw=4, report_path=None,
        )
    assert len(result["recommended_schedule"]) == 3
    assert set(result["unscheduled_chips"]) == {"wildcard"}


def test_pure_transfer_suggestions_do_not_sync_state_or_export(planning_db):
    import json
    from fpl_manager.suggest_transfers import suggest_transfers
    squad_path = planning_db.parent / "squad.json"
    raw = json.dumps(dict(
        season="2026/27", gameweek=1, player_ids=list(range(1, 16)),
        purchase_prices_tenths={str(pid): 50 for pid in range(1, 16)},
        bank_tenths=0, free_transfers=1,
    ))
    squad_path.write_text(raw, encoding="utf-8")
    with patch.object(Path, "write_text", side_effect=AssertionError("query wrote a file")), patch(
        "fpl_manager.teams.sync_squad_with_current_gameweek",
        side_effect=AssertionError("query synced lifecycle state"),
    ):
        report = suggest_transfers(
            squad_path=squad_path, database_path=planning_db, report_path=None, max_results=1,
        )
    assert not report["optimization_metadata"]["is_exact_global_optimum"]
    assert squad_path.read_text(encoding="utf-8") == raw


@pytest.mark.parametrize("season,expected", [
    ("2023-24", [1, 2, 2, 2, 2, 2]),
    ("2024-25", [1, 2, 3, 4, 5, 5]),
])
def test_live_planner_obeys_season_ft_caps(planning_db, season, expected):
    from fpl_manager.planner import generate_multi_gameweek_plan
    result = generate_multi_gameweek_plan(
        database_path=planning_db, start_gw=1, initial_squad_ids=list(range(1, 16)),
        horizon=6, allow_hits=False, season=season, report_path=None,
    )
    assert [s["free_transfers_after"] for s in result["best_plan"]["gameweek_steps"]] == expected


def test_free_hit_live_horizon_requires_and_restores_permanent_state(planning_db):
    from fpl_manager.planner import generate_multi_gameweek_plan
    args = dict(
        database_path=planning_db, start_gw=2, initial_squad_ids=list(range(1, 16)),
        horizon=2, active_chip="free_hit", report_path=None,
    )
    with pytest.raises(ValueError, match="pre_free_hit_state"):
        generate_multi_gameweek_plan(**args)
    result = generate_multi_gameweek_plan(**args, pre_free_hit_state={
        "squad_ids": list(range(1, 16)), "bank_tenths": 25,
        "purchase_prices_tenths": {pid: 50 for pid in range(1, 16)},
    })
    steps = result["best_plan"]["gameweek_steps"]
    assert steps[1]["bank_after_tenths"] == 25
    assert steps[1]["free_transfers_after"] == 2


@pytest.mark.parametrize("alias", ["v1.1", "v11"])
def test_v11_alias_preserves_prior_frozen_predictor_and_metadata(projection_db, alias):
    from fpl_manager.model_registry import resolve_predictor_version
    assert resolve_predictor_version(alias) == "v1.0"
    assert get_model_metadata(alias, gameweek=2) == get_model_metadata("v1.0", gameweek=2)
    canonical = project_gameweek(2, database_path=projection_db, predictor_version="v1.0")
    aliased = project_gameweek(2, database_path=projection_db, predictor_version=alias)
    assert aliased == canonical
    profiles = project_multi_gameweek_profiles([2], database_path=projection_db, predictor_version=alias)
    assert profiles[1].expected_points == canonical[0].expected_points


def _prospective_state(planning_db):
    from fpl_manager.squad_state import CurrentSquadState
    store = SnapshotStore(planning_db)
    with store._connect() as connection, connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(players)")]
        row = dict(zip(columns, connection.execute(
            "SELECT * FROM players WHERE player_id = 8"
        ).fetchone()))
        row.update(player_id=101, web_name="Prospective", team_id=16, price_tenths=55)
        connection.execute(
            f"INSERT INTO players ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            tuple(row[column] for column in columns),
        )
    ids = tuple(101 if pid == 8 else pid for pid in range(1, 16))
    return CurrentSquadState(
        player_ids=ids, purchase_prices_tenths={pid: 60 for pid in ids},
        bank_tenths=17, free_transfers=3, chips_remaining=(),
        season="2026/27", gameweek=2,
    )


def test_transfer_suggestions_use_exact_injected_prospective_state(planning_db):
    from fpl_manager.suggest_transfers import suggest_transfers
    state = _prospective_state(planning_db)
    with patch("fpl_manager.suggest_transfers.load_current_squad",
               side_effect=AssertionError("read default squad")), patch(
        "fpl_manager.teams.sync_squad_with_current_gameweek",
        side_effect=AssertionError("synchronized default squad"),
    ), patch.object(Path, "write_text", side_effect=AssertionError("query exported a file")), patch(
        "fpl_manager.suggest_transfers.solve_transfers", wraps=solve_transfers,
    ) as solve:
        result = suggest_transfers(
            database_path=planning_db, state=state, report_path=None,
            num_gameweeks=1, engine="legacy",
        )
    args = solve.call_args.kwargs
    assert {p.id for p in args["squad_players"]} == set(state.player_ids)
    assert {p.id for p in args["candidate_pool"]} == {8}
    assert args["bank_tenths"] == 17
    assert args["free_transfers"] == 3
    assert args["selling_prices"][101] == 55
    assert args["selling_prices"][9] == 50
    assert result["target_gameweeks"] == [2]
    assert result["free_transfers_available"] == 3
    assert result["top_suggestions"]
    assert result["top_suggestions"][0]["incoming"][0]["id"] == 8
    assert state.player_ids == tuple(101 if pid == 8 else pid for pid in range(1, 16))
    assert state.purchase_prices_tenths == {pid: 60 for pid in state.player_ids}
    assert state.bank_tenths == 17


def test_injected_missing_player_rejects_without_default_squad_fallback(planning_db):
    from fpl_manager.squad_state import CurrentSquadState
    from fpl_manager.suggest_transfers import suggest_transfers
    ids = tuple(list(range(1, 15)) + [999])
    state = CurrentSquadState(ids, {pid: 50 for pid in ids}, 0, 1, (), "2026/27", 2)
    with patch("fpl_manager.suggest_transfers.load_current_squad",
               side_effect=AssertionError("read default squad")), pytest.raises(
        ValueError, match="999",
    ):
        suggest_transfers(database_path=planning_db, state=state, report_path=None)
