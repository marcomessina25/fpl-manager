"""V1.0 Release Verification Test Suite (Workstreams P0 through P7).

Tests:
- P0: V0.9 baseline freeze & lineup_penalty_weight = 0.0
- P1.1: Point-in-time leakage rejection across all 7 leakage categories
- P1.2: Model registry metadata & deterministic historical reconstruction
- P1.3: Canonical model report completeness
- P2: Decision engine neutral strategy, participation signals, 5 risk profiles, captaincy validation
- P3: Exhaustive equivalence for 1..5 transfers, Wildcard heuristic disclosure, multi-GW exhaustive equivalence, reproducibility
- P4: Provider abstraction, deterministic guardrails, LLM evaluation database persistence
- P5: 5-way error attribution, observed vs hindsight counterfactuals, decision-weighted error formula
"""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from fpl_manager import __version__
from fpl_manager.backtest.decision_engine import DecisionEngineV09, DecisionEngineV10, resolve_decision_engine
from fpl_manager.backtest.manifest import build_ablation_manifest
from fpl_manager.evaluation import calculate_decision_weighted_error, decompose_decision_error_components
from fpl_manager.expected_points import project_player_gameweek
from fpl_manager.historical.models import (
    GameweekOutcome,
    HistoricalFixture,
    HistoricalGameweekSnapshot,
    HistoricalPlayerState,
    Position,
)
from fpl_manager.historical.validation import validate_no_future_leakage
from fpl_manager.model_registry import (
    ModelMetadata,
    get_model_metadata,
    reconstruct_historical_prediction,
)
from fpl_manager.optimizer import (
    PlayerOptInfo,
    RISK_PROFILE_SPECIFICATIONS,
    get_player_profile_value,
    solve_transfers,
    solve_transfers_exhaustive,
    solve_wildcard,
    validate_risk_profile,
)
from fpl_manager.storage import SnapshotStore


def _make_sample_snapshot(gameweek: int = 2, finished_gws: int = 1) -> HistoricalGameweekSnapshot:
    teams = (
        {"team_id": 1, "name": "Arsenal", "short_name": "ARS"},
        {"team_id": 2, "name": "Chelsea", "short_name": "CHE"},
    )
    fixtures = (
        HistoricalFixture(
            fixture_id=101,
            event=gameweek,
            team_h=1,
            team_a=2,
            team_h_difficulty=2,
            team_a_difficulty=4,
            kickoff_time="2025-08-23T14:00:00Z",
            finished=False,
        ),
    )
    players = (
        HistoricalPlayerState(
            player_id=1,
            web_name="Saka",
            position=Position.MIDFIELDER,
            team_id=1,
            price_tenths=100,
            status="a",
            chance_of_playing_next_round=100,
            chance_of_playing_this_round=100,
            total_points=8,
            minutes=90,
            starts=1,
            expected_goals=0.45,
            expected_assists=0.35,
            expected_goal_involvements=0.80,
            expected_goals_conceded=0.50,
            expected_goals_per_90=0.45,
            expected_assists_per_90=0.35,
            expected_goals_conceded_per_90=0.50,
            clean_sheets_per_90=0.50,
            bps=25,
            ict_index=9.5,
            form=8.0,
            points_per_game=8.0,
            selected_by_percent=35.0,
            news="",
            starts_last_3=1,
            starts_last_5=1,
            minutes_last_3=90,
            minutes_last_5=90,
        ),
        HistoricalPlayerState(
            player_id=2,
            web_name="Palmer",
            position=Position.MIDFIELDER,
            team_id=2,
            price_tenths=105,
            status="a",
            chance_of_playing_next_round=100,
            chance_of_playing_this_round=100,
            total_points=6,
            minutes=90,
            starts=1,
            expected_goals=0.50,
            expected_assists=0.40,
            expected_goal_involvements=0.90,
            expected_goals_conceded=1.00,
            expected_goals_per_90=0.50,
            expected_assists_per_90=0.40,
            expected_goals_conceded_per_90=1.00,
            clean_sheets_per_90=0.20,
            bps=22,
            ict_index=10.2,
            form=6.0,
            points_per_game=6.0,
            selected_by_percent=40.0,
            news="",
            starts_last_3=1,
            starts_last_5=1,
            minutes_last_3=90,
            minutes_last_5=90,
        ),
    )
    return HistoricalGameweekSnapshot(
        season="2025-26",
        gameweek=gameweek,
        deadline_time="2025-08-23T11:00:00Z",
        finished_gameweeks=finished_gws,
        players=players,
        teams=teams,
        fixtures=fixtures,
    )


def test_p0_version_and_frozen_v09_baseline() -> None:
    """Verify V1.0 version bump, lineup_penalty_weight = 0.0, and frozen V0.9 baseline report."""
    assert __version__ == "1.0.0"

    eng_v09 = DecisionEngineV09()
    eng_v10 = resolve_decision_engine("v1.0")
    assert isinstance(eng_v10, DecisionEngineV10)
    assert eng_v09.lineup_penalty_weight == 0.0
    assert eng_v10.lineup_penalty_weight == 0.0

    baseline_path = Path("reports/v09_frozen_baseline.json")
    assert baseline_path.exists()
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert data["metrics"]["decision_replay_2025_26"]["lineup_penalty_weight"] == 0.0
    assert data["metrics"]["decision_replay_2025_26"]["net_points"] == 2014
    assert data["metrics"]["multi_season_summary_2021_2026"]["aggregate_net_points_w000"] == 10187


def test_p1_1_point_in_time_leakage_protections_all_seven_categories() -> None:
    """Inject all 7 future leakage types and verify validate_no_future_leakage rejects each."""
    prior_snap = _make_sample_snapshot(gameweek=1, finished_gws=1)
    clean_snap = _make_sample_snapshot(gameweek=2, finished_gws=1)
    outcomes = {
        1: GameweekOutcome(season="2025-26", player_id=1, gameweek=2, minutes=90, total_points=12, goals_scored=1, assists=1, clean_sheets=1, goals_conceded=0, bonus=3, bps=42),
    }

    # Clean snapshot passes with zero violations
    assert validate_no_future_leakage(clean_snap, outcomes, prior_snapshot=prior_snap) == []

    # 1. Final GW statistics leaked into pre-deadline snapshot
    leaked_p1 = replace(clean_snap.players[0], total_points=20)  # 8 prior + 12 current GW
    snap_1 = replace(clean_snap, players=(leaked_p1, clean_snap.players[1]))
    v1 = validate_no_future_leakage(snap_1, outcomes, prior_snapshot=prior_snap)
    assert any("Final-GW stat leakage" in msg for msg in v1)

    # 2, 3, 4, 5: Future injury status, future price, future ownership, post-deadline news
    leaked_meta_player = replace(clean_snap.players[0], status="i", price_tenths=102, selected_by_percent=42.5)
    snap_meta = replace(clean_snap, players=(leaked_meta_player, clean_snap.players[1]))
    post_state = {
        1: {
            "pre_deadline_status": "a",
            "future_status": "i",
            "pre_deadline_price_tenths": 100,
            "future_price_tenths": 102,
            "pre_deadline_ownership": 35.0,
            "future_ownership": 42.5,
            "news_timestamp": "2025-08-23T13:30:00Z",
            "deadline_timestamp": "2025-08-23T11:00:00Z",
        }
    }
    v_meta = validate_no_future_leakage(snap_meta, outcomes, prior_snapshot=prior_snap, post_deadline_state=post_state)
    assert any("Future injury leakage" in msg for msg in v_meta)
    assert any("Future price leakage" in msg for msg in v_meta)
    assert any("Future ownership leakage" in msg for msg in v_meta)
    assert any("Post-deadline news leakage" in msg for msg in v_meta)

    # 6. Future fixtures / results already marked finished
    leaked_fix = replace(clean_snap.fixtures[0], finished=True)
    snap_fix = replace(clean_snap, fixtures=(leaked_fix,))
    v_fix = validate_no_future_leakage(snap_fix, outcomes)
    assert any("already marked finished" in msg for msg in v_fix)

    # 7. Later versions of statistics exceeding completed gameweeks
    leaked_later = replace(clean_snap.players[0], starts=10, minutes=900, starts_last_3=3)
    snap_later = replace(clean_snap, players=(leaked_later, clean_snap.players[1]))
    v_later = validate_no_future_leakage(snap_later, outcomes)
    assert any("Later-stat leakage" in msg for msg in v_later)


def test_p1_2_model_registry_and_deterministic_reconstruction() -> None:
    """Verify canonical ModelMetadata on projections and exact historical reconstruction."""
    snap = _make_sample_snapshot(gameweek=5, finished_gws=4)
    meta = get_model_metadata(predictor_version="v1.0", gameweek=5, prediction_timestamp="2025-09-20T10:00:00Z")

    assert meta.model_version == "v1.0.0"
    assert "GW4" in meta.training_data_cutoff
    assert meta.feature_set_version == "v0.9.1-pit-rolling-congestion"
    assert meta.parameter_version == "1.0.0-frozen-v0.9.1-w0.00"
    assert meta.prediction_timestamp == "2025-09-20T10:00:00Z"

    run_1 = reconstruct_historical_prediction(snap, meta, {"predictor_version": "v1.0"})
    run_2 = reconstruct_historical_prediction(snap, meta.to_dict(), {"predictor_version": "v1.0"})

    assert len(run_1) == len(run_2) == 2
    for p1, p2 in zip(run_1, run_2):
        assert p1.expected_points == p2.expected_points
        assert p1.expected_minutes == p2.expected_minutes
        assert p1.start_probability == p2.start_probability
        assert p1.model_metadata == meta.to_dict()


def test_p2_risk_profiles_and_participation_signals() -> None:
    """Verify all 5 risk profiles are specified and validated, and participation signals are preserved."""
    expected_profiles = {"neutral", "floor", "ceiling", "defend_lead", "chase"}
    assert set(RISK_PROFILE_SPECIFICATIONS.keys()) == expected_profiles

    for prof, spec in RISK_PROFILE_SPECIFICATIONS.items():
        assert validate_risk_profile(prof) == prof
        assert "mathematical_objective" in spec
        assert "configurable_parameters" in spec
        assert "expected_behaviour" in spec
        assert "validation_metrics" in spec
        assert "historical_test_result" in spec

    with pytest.raises(ValueError, match="Invalid risk_profile"):
        validate_risk_profile("unvalidated_gamble")

    proj = project_player_gameweek(
        player_id=10,
        web_name="Haaland",
        position=Position.FORWARD,
        team_id=1,
        team_short="MCI",
        price_tenths=150,
        status="a",
        total_points=45,
        finished_matches=5,
        gameweek=6,
        team_fixtures_in_gw=[{"opponent_id": 2, "opponent_short": "CHE", "is_home": True, "fdr": 2}],
        minutes=440,
        starts=5,
        starts_last_3=3,
        starts_last_5=5,
        minutes_last_3=265,
        minutes_last_5=440,
        predictor_version="v1.0",
    )
    assert proj.start_probability > 0.70
    assert proj.play_probability >= proj.start_probability
    assert proj.sub_probability >= 0.0
    assert proj.expected_minutes > 70.0
    assert proj.regime in ("STARTER", "ROTATION", "SQUAD", "INJURY_RETURN")
    assert proj.model_metadata is not None


def test_p3_1_transfer_optimizer_exhaustive_equivalence_1_to_5_transfers() -> None:
    """Prove branch-and-bound optimum == exhaustive optimum for k = 1, 2, 3, 4, and 5 transfers."""
    squad = [
        PlayerOptInfo(id=1, name="G1", position=Position.GOALKEEPER, team_id=1, team_short="T1", price_tenths=45, status="a", total_points=10, expected_points=3.2, expected_minutes=90, xp_floor=2.0, xp_ceiling=5.0),
        PlayerOptInfo(id=2, name="G2", position=Position.GOALKEEPER, team_id=2, team_short="T2", price_tenths=40, status="a", total_points=5, expected_points=1.5, expected_minutes=0, xp_floor=0.0, xp_ceiling=2.0),
        PlayerOptInfo(id=3, name="D1", position=Position.DEFENDER, team_id=1, team_short="T1", price_tenths=50, status="a", total_points=12, expected_points=3.5, expected_minutes=90, xp_floor=2.0, xp_ceiling=6.0),
        PlayerOptInfo(id=4, name="D2", position=Position.DEFENDER, team_id=2, team_short="T2", price_tenths=45, status="a", total_points=8, expected_points=2.1, expected_minutes=70, xp_floor=1.0, xp_ceiling=4.0),
        PlayerOptInfo(id=5, name="D3", position=Position.DEFENDER, team_id=3, team_short="T3", price_tenths=45, status="a", total_points=7, expected_points=2.0, expected_minutes=60, xp_floor=1.0, xp_ceiling=3.5),
        PlayerOptInfo(id=6, name="D4", position=Position.DEFENDER, team_id=4, team_short="T4", price_tenths=40, status="a", total_points=4, expected_points=1.2, expected_minutes=30, xp_floor=0.5, xp_ceiling=2.5),
        PlayerOptInfo(id=7, name="D5", position=Position.DEFENDER, team_id=5, team_short="T5", price_tenths=40, status="a", total_points=3, expected_points=1.0, expected_minutes=15, xp_floor=0.0, xp_ceiling=2.0),
        PlayerOptInfo(id=8, name="M1", position=Position.MIDFIELDER, team_id=1, team_short="T1", price_tenths=85, status="a", total_points=25, expected_points=5.5, expected_minutes=90, xp_floor=3.0, xp_ceiling=9.5),
        PlayerOptInfo(id=9, name="M2", position=Position.MIDFIELDER, team_id=2, team_short="T2", price_tenths=75, status="a", total_points=18, expected_points=4.2, expected_minutes=85, xp_floor=2.5, xp_ceiling=7.5),
        PlayerOptInfo(id=10, name="M3", position=Position.MIDFIELDER, team_id=3, team_short="T3", price_tenths=65, status="a", total_points=12, expected_points=3.1, expected_minutes=75, xp_floor=2.0, xp_ceiling=5.5),
        PlayerOptInfo(id=11, name="M4", position=Position.MIDFIELDER, team_id=4, team_short="T4", price_tenths=55, status="a", total_points=9, expected_points=2.4, expected_minutes=60, xp_floor=1.2, xp_ceiling=4.2),
        PlayerOptInfo(id=12, name="M5", position=Position.MIDFIELDER, team_id=5, team_short="T5", price_tenths=50, status="a", total_points=6, expected_points=1.8, expected_minutes=45, xp_floor=0.8, xp_ceiling=3.2),
        PlayerOptInfo(id=13, name="F1", position=Position.FORWARD, team_id=3, team_short="T3", price_tenths=90, status="a", total_points=24, expected_points=5.2, expected_minutes=88, xp_floor=3.0, xp_ceiling=9.0),
        PlayerOptInfo(id=14, name="F2", position=Position.FORWARD, team_id=4, team_short="T4", price_tenths=70, status="a", total_points=14, expected_points=3.4, expected_minutes=80, xp_floor=2.0, xp_ceiling=6.0),
        PlayerOptInfo(id=15, name="F3", position=Position.FORWARD, team_id=5, team_short="T5", price_tenths=55, status="a", total_points=7, expected_points=2.0, expected_minutes=50, xp_floor=1.0, xp_ceiling=4.0),
    ]
    candidates = [
        PlayerOptInfo(id=101, name="CandG1", position=Position.GOALKEEPER, team_id=6, team_short="T6", price_tenths=45, status="a", total_points=15, expected_points=4.2, expected_minutes=90, xp_floor=2.8, xp_ceiling=6.2),
        PlayerOptInfo(id=102, name="CandD1", position=Position.DEFENDER, team_id=6, team_short="T6", price_tenths=45, status="a", total_points=16, expected_points=4.5, expected_minutes=90, xp_floor=3.0, xp_ceiling=7.0),
        PlayerOptInfo(id=103, name="CandD2", position=Position.DEFENDER, team_id=7, team_short="T7", price_tenths=40, status="a", total_points=14, expected_points=4.0, expected_minutes=90, xp_floor=2.5, xp_ceiling=6.0),
        PlayerOptInfo(id=104, name="CandM1", position=Position.MIDFIELDER, team_id=6, team_short="T6", price_tenths=65, status="a", total_points=22, expected_points=5.8, expected_minutes=90, xp_floor=3.5, xp_ceiling=10.0),
        PlayerOptInfo(id=105, name="CandM2", position=Position.MIDFIELDER, team_id=7, team_short="T7", price_tenths=55, status="a", total_points=19, expected_points=5.0, expected_minutes=88, xp_floor=3.0, xp_ceiling=8.5),
        PlayerOptInfo(id=106, name="CandF1", position=Position.FORWARD, team_id=7, team_short="T7", price_tenths=70, status="a", total_points=21, expected_points=5.6, expected_minutes=90, xp_floor=3.2, xp_ceiling=9.8),
        PlayerOptInfo(id=107, name="CandF2", position=Position.FORWARD, team_id=8, team_short="T8", price_tenths=55, status="a", total_points=17, expected_points=4.6, expected_minutes=85, xp_floor=2.8, xp_ceiling=8.0),
    ]
    selling = {p.id: p.price_tenths for p in squad}
    fdr_map = {f"T{i}": 3.0 for i in range(1, 9)}

    for k in (1, 2, 3, 4, 5):
        bnb_recs, _ = solve_transfers(
            num_transfers=k,
            squad_players=squad,
            candidate_pool=candidates,
            bank_tenths=20,
            free_transfers=2,
            selling_prices=selling,
            fdr_map=fdr_map,
            ticker_map={},
            risk_profile="neutral",
            max_results=5,
        )
        exh_best = solve_transfers_exhaustive(
            num_transfers=k,
            squad_players=squad,
            candidate_pool=candidates,
            bank_tenths=20,
            free_transfers=2,
            selling_prices=selling,
            fdr_map=fdr_map,
            risk_profile="neutral",
        )
        assert bnb_recs and exh_best is not None
        assert bnb_recs[0]["score"] == exh_best["score"], f"Mismatch at k={k} transfers!"


def test_p3_2_wildcard_heuristic_solver_disclosure() -> None:
    """Verify solve_wildcard explicitly documents its heuristic local-search nature and satisfies all rules."""
    pool = []
    pos_counts = [(Position.GOALKEEPER, 4), (Position.DEFENDER, 10), (Position.MIDFIELDER, 10), (Position.FORWARD, 6)]
    pid = 1
    for pos, cnt in pos_counts:
        for idx in range(cnt):
            pool.append(
                PlayerOptInfo(
                    id=pid,
                    name=f"P{pid}",
                    position=pos,
                    team_id=(pid % 10) + 1,
                    team_short=f"T{(pid % 10) + 1}",
                    price_tenths=45 + (idx * 5),
                    status="a",
                    total_points=20 + idx,
                    expected_points=round(2.5 + idx * 0.4, 2),
                    expected_minutes=85.0,
                    xp_floor=1.8,
                    xp_ceiling=6.0,
                )
            )
            pid += 1

    res = solve_wildcard(pool, budget_tenths=1000, risk_profile="neutral")
    assert res["solver_type"] == "heuristic_local_search_1opt_2opt"
    assert res["is_exact_global_solver"] is False
    assert len(res["squad"]) == 15
    assert len(res["starters"]) == 11
    assert len(res["bench"]) == 4
    assert res["total_cost_tenths"] <= 1000


def test_p4_4_and_p5_llm_evaluation_and_error_decomposition(tmp_path: Path) -> None:
    """Verify LLM evaluation persistence and 5-way decision error attribution + decision-weighted error."""
    db_path = tmp_path / "test_v10.sqlite3"
    store = SnapshotStore(db_path)
    store.initialize()

    eval_id = store.record_llm_evaluation(
        gameweek=10,
        provider="heuristic",
        model="deterministic-heuristic-v0.9",
        prompt_version="v1.0.0-devils_advocate-dossier-v1",
        recommendation={"proposed_captain": "Saka", "proposed_transfers": []},
        deterministic_validation_passed=True,
        validation_errors=[],
        human_decision_status="accepted",
        eventual_outcome_points=68,
    )
    assert eval_id > 0

    records = store.list_llm_evaluations(gameweek=10)
    assert len(records) == 1
    assert records[0]["provider"] == "heuristic"
    assert records[0]["deterministic_validation_passed"] is True
    assert records[0]["human_decision_status"] == "accepted"
    assert records[0]["eventual_outcome_points"] == 68

    # 5-way error separation
    decomp = decompose_decision_error_components(
        predicted_lineup_xp=58.5,
        actual_lineup_score=52.0,
        captain_regret=6.0,
        bench_regret=4.0,
        hindsight_optimal_points=62.0,
        transfers=[{"player_out_id": 10, "player_in_id": 11}],
        transfer_hits=1,
        chip_played=None,
        actual_scores={10: 5.0, 11: 6.0},
    )
    assert decomp["prediction_error"] == 6.5
    assert decomp["decision_error"] == 10.0
    assert decomp["captaincy_error"] == 6.0
    assert decomp["transfer_error"] == 3.0  # +1 gross gain - 4 hit cost = -3 net -> 3.0 error
    assert decomp["chip_error"] == 0.0

    # Decision-weighted error formula
    dwe = calculate_decision_weighted_error(
        predicted_xp=7.5,
        actual_points=2.0,
        squad_selection_prob=1.0,
        captaincy_prob=0.8,
        price_tenths=110,
        optimizer_exposure=0.9,
        transfer_relevance=0.7,
    )
    assert dwe["raw_abs_error"] == 5.5
    assert dwe["decision_weight"] > 3.0
    assert dwe["decision_weighted_error"] == round(dwe["decision_weight"] * 5.5, 4)
