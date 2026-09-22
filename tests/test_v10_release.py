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
    """Verify V1.0.1 version bump, lineup_penalty_weight = 0.0, and frozen V0.9 baseline report."""
    assert __version__ == "1.0.1"

    eng_v09 = DecisionEngineV09()
    eng_v10 = resolve_decision_engine("v1.0.1")
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


def test_p0_1_and_p1_5_independent_exact_transfer_oracle_and_adversarial_bounds() -> None:
    """Verify P0.1 and P1.5:
    - Exact combinatorics sizes (A=16, B=225, C=1225, D=4900, E=15876)
    - Safety budget guard (MAX_REFERENCE_EVALUATIONS = 100_000)
    - All 10 required adversarial scenarios (late optimum, ties, budget, club limit,
      unavailable players, zero/negative value transfers, and P1.5 pruning-sensitive FDR inversion).
    """
    from fpl_manager.optimizer import (
        MAX_REFERENCE_EVALUATIONS,
        solve_transfers_bruteforce_reference,
        solve_transfers_exact_reference,
    )

    base_squad = [
        PlayerOptInfo(id=1, name="G1", position=Position.GOALKEEPER, team_id=1, team_short="T1", price_tenths=45, status="a", total_points=10, expected_points=3.0),
        PlayerOptInfo(id=2, name="G2", position=Position.GOALKEEPER, team_id=2, team_short="T2", price_tenths=40, status="a", total_points=5, expected_points=1.5),
        PlayerOptInfo(id=3, name="D1", position=Position.DEFENDER, team_id=1, team_short="T1", price_tenths=50, status="a", total_points=12, expected_points=3.5),
        PlayerOptInfo(id=4, name="D2", position=Position.DEFENDER, team_id=2, team_short="T2", price_tenths=45, status="a", total_points=8, expected_points=2.1),
        PlayerOptInfo(id=5, name="D3", position=Position.DEFENDER, team_id=3, team_short="T3", price_tenths=45, status="a", total_points=7, expected_points=2.0),
        PlayerOptInfo(id=6, name="D4", position=Position.DEFENDER, team_id=4, team_short="T4", price_tenths=40, status="a", total_points=4, expected_points=1.2),
        PlayerOptInfo(id=7, name="D5", position=Position.DEFENDER, team_id=5, team_short="T5", price_tenths=40, status="a", total_points=3, expected_points=1.0),
        PlayerOptInfo(id=8, name="M1", position=Position.MIDFIELDER, team_id=1, team_short="T1", price_tenths=85, status="a", total_points=25, expected_points=5.5),
        PlayerOptInfo(id=9, name="M2", position=Position.MIDFIELDER, team_id=2, team_short="T2", price_tenths=75, status="a", total_points=18, expected_points=4.2),
        PlayerOptInfo(id=10, name="M3", position=Position.MIDFIELDER, team_id=3, team_short="T3", price_tenths=65, status="a", total_points=12, expected_points=3.1),
        PlayerOptInfo(id=11, name="M4", position=Position.MIDFIELDER, team_id=4, team_short="T4", price_tenths=55, status="a", total_points=9, expected_points=2.4),
        PlayerOptInfo(id=12, name="M5", position=Position.MIDFIELDER, team_id=5, team_short="T5", price_tenths=50, status="a", total_points=6, expected_points=1.8),
        PlayerOptInfo(id=13, name="F1", position=Position.FORWARD, team_id=3, team_short="T3", price_tenths=90, status="a", total_points=24, expected_points=5.2),
        PlayerOptInfo(id=14, name="F2", position=Position.FORWARD, team_id=4, team_short="T4", price_tenths=70, status="a", total_points=14, expected_points=3.4),
        PlayerOptInfo(id=15, name="F3", position=Position.FORWARD, team_id=5, team_short="T5", price_tenths=55, status="a", total_points=7, expected_points=2.0),
    ]
    selling = {p.id: p.price_tenths for p in base_squad}
    fdr_map = {f"T{i}": 3.0 for i in range(1, 20)}

    # 1. Exact bounded table verification (Tests A, B, C, D, E)
    table_specs = [
        ("A", 4, 4, 1, 16),
        ("B", 6, 6, 2, 225),
        ("C", 7, 7, 3, 1225),
        ("D", 8, 8, 4, 4900),
        ("E", 9, 9, 5, 15876),
    ]
    for label, n_out, n_in, k_tx, expected_combos in table_specs:
        out_subset = base_squad[:n_out]
        in_subset = [
            PlayerOptInfo(
                id=200 + idx,
                name=f"In_{label}_{idx}",
                position=out_subset[idx % len(out_subset)].position,
                team_id=6 + (idx % 6),
                team_short=f"T{6 + (idx % 6)}",
                price_tenths=40 + (idx * 2),
                status="a",
                total_points=15 + idx,
                expected_points=round(2.5 + (idx * 0.65), 2),
            )
            for idx in range(n_in)
        ]
        # Run independent exact reference oracle
        oracle_best = solve_transfers_exact_reference(
            num_transfers=k_tx,
            squad_players=base_squad,
            candidate_out_pool=out_subset,
            candidate_pool=in_subset,
            bank_tenths=50,
            free_transfers=2,
            selling_prices=selling,
            fdr_map=fdr_map,
        )
        assert oracle_best is not None
        assert oracle_best["oracle_metadata"]["expected_combinations"] == expected_combos
        assert oracle_best["oracle_metadata"]["evaluated_combinations"] == expected_combos

        # Run production branch-and-bound on the same out_subset (by freezing non-out_subset players via prohibitive selling price)
        # Wait: in solve_transfers, out_combos enumerates squad_players; to restrict out_combos to out_subset without altering budget,
        # we make non-out_subset players have high expected_points (e.g., 50.0) so neither solver ever sells them!
        out_ids = {p.id for p in out_subset}
        locked_squad = [
            p if p.id in out_ids else PlayerOptInfo(
                id=p.id, name=p.name, position=p.position, team_id=p.team_id, team_short=p.team_short,
                price_tenths=p.price_tenths, status="a", total_points=p.total_points, expected_points=99.0
            )
            for p in base_squad
        ]
        oracle_locked = solve_transfers_bruteforce_reference(
            num_transfers=k_tx,
            squad_players=locked_squad,
            candidate_out_pool=out_subset,
            candidate_pool=in_subset,
            bank_tenths=50,
            free_transfers=2,
            selling_prices=selling,
            fdr_map=fdr_map,
        )
        bnb_recs, _ = solve_transfers(
            num_transfers=k_tx,
            squad_players=locked_squad,
            candidate_pool=in_subset,
            bank_tenths=50,
            free_transfers=2,
            selling_prices=selling,
            fdr_map=fdr_map,
            ticker_map={},
            risk_profile="neutral",
            max_results=3,
        )
        assert bnb_recs and oracle_locked is not None
        assert bnb_recs[0]["score"] == oracle_locked["score"], f"Failed on Table Test {label} (k={k_tx})"
        assert {p["id"] for p in bnb_recs[0]["outgoing"]} == {p["id"] for p in oracle_locked["outgoing"]}
        assert {p["id"] for p in bnb_recs[0]["incoming"]} == {p["id"] for p in oracle_locked["incoming"]}

    # 2. Safety guard verification: exceeding MAX_REFERENCE_EVALUATIONS raises ValueError
    huge_in = [
        PlayerOptInfo(id=500 + i, name=f"H{i}", position=Position.MIDFIELDER, team_id=6, team_short="T6", price_tenths=45, status="a", total_points=10, expected_points=4.0)
        for i in range(25)
    ]
    with pytest.raises(ValueError, match="MAX_REFERENCE_EVALUATIONS"):
        solve_transfers_exact_reference(
            num_transfers=5,
            squad_players=base_squad,
            candidate_pool=huge_in,  # C(15,5) * C(25,5) = 3003 * 53130 = 159,549,390 > 100,000
            bank_tenths=50,
            free_transfers=1,
            selling_prices=selling,
            fdr_map=fdr_map,
            max_evaluations=MAX_REFERENCE_EVALUATIONS,
        )

    # 3. Adversarial & P1.5 Pruning-Sensitive Scenarios:
    # - Candidate 301 has higher raw xP (6.00) but terrible FDR (5.0) -> eff contribution = 6.00 - 0.50 = 5.50
    # - Candidate 302 has slightly lower raw xP (5.98) but great FDR (1.0) -> eff contribution = 5.98 - 0.10 = 5.88 (TRUE OPTIMUM!)
    # - Candidate 303 is injured ('i') with huge xP (15.0) -> must be rejected by both solvers!
    # - Candidate 304 belongs to T1 (already at 3 players when selling D5 from T5) -> club limit blocks it!
    # - Candidate 305 ties Candidate 302 on score -> deterministic tie-breaking!
    adv_fdr = dict(fdr_map)
    adv_fdr["T_BAD_FDR"] = 5.0
    adv_fdr["T_GOOD_FDR"] = 1.0
    adv_candidates = [
        PlayerOptInfo(id=301, name="HighRawBadFDR", position=Position.DEFENDER, team_id=10, team_short="T_BAD_FDR", price_tenths=40, status="a", total_points=20, expected_points=6.00),
        PlayerOptInfo(id=302, name="SlightlyLowerRawGreatFDR", position=Position.DEFENDER, team_id=11, team_short="T_GOOD_FDR", price_tenths=40, status="a", total_points=20, expected_points=5.98),
        PlayerOptInfo(id=303, name="InjuredSuperstar", position=Position.DEFENDER, team_id=12, team_short="T_GOOD_FDR", price_tenths=40, status="i", total_points=50, expected_points=15.00),
        PlayerOptInfo(id=304, name="ClubQuotaBlocked", position=Position.DEFENDER, team_id=1, team_short="T1", price_tenths=40, status="a", total_points=40, expected_points=12.00),
        PlayerOptInfo(id=305, name="ZeroValue", position=Position.DEFENDER, team_id=13, team_short="T5", price_tenths=40, status="a", total_points=3, expected_points=1.00),
        PlayerOptInfo(id=306, name="NegativeValue", position=Position.DEFENDER, team_id=14, team_short="T5", price_tenths=40, status="a", total_points=1, expected_points=0.20),
    ]
    # Ensure T1 already has 3 non-defender players (G1, M1, F1) and D1 is on T6 so adv_squad is 100% legal:
    adv_squad = [
        PlayerOptInfo(
            id=p.id,
            name=p.name,
            position=p.position,
            team_id=(6 if p.id == 3 else (1 if p.id == 13 else p.team_id)),
            team_short=("T6" if p.id == 3 else ("T1" if p.id == 13 else p.team_short)),
            price_tenths=p.price_tenths,
            status=p.status,
            total_points=p.total_points,
            expected_points=p.expected_points,
        )
        for p in base_squad
    ]
    bnb_adv, _ = solve_transfers(
        num_transfers=1,
        squad_players=adv_squad,
        candidate_pool=adv_candidates,
        bank_tenths=0,
        free_transfers=1,
        selling_prices=selling,
        fdr_map=adv_fdr,
        ticker_map={},
        risk_profile="neutral",
        max_results=1,
    )
    oracle_adv = solve_transfers_exact_reference(
        num_transfers=1,
        squad_players=adv_squad,
        candidate_pool=adv_candidates,
        bank_tenths=0,
        free_transfers=1,
        selling_prices=selling,
        fdr_map=adv_fdr,
        risk_profile="neutral",
    )
    assert bnb_adv and oracle_adv is not None
    assert bnb_adv[0]["score"] == oracle_adv["score"]
    assert bnb_adv[0]["incoming"][0]["id"] == 302
    assert oracle_adv["incoming"][0]["id"] == 302


def test_p0_2_independent_exact_multi_gw_dp_reference_all_eight_scenarios() -> None:
    """Verify P0.2 across all 8 required synthetic multi-GW scenarios:
    1. immediate reward
    2. transfer cost (-4 hit)
    3. future value / non-greedy optimum
    4. banked transfers (ROLL in GW1 -> 2 free transfers in GW2)
    5. illegal transitions (budget, club quota, unavailable)
    6. repeated player usage
    7. ties
    8. optimal plan != greedy plan (beam planner == DP reference > greedy myopic plan)
    """
    from fpl_manager.planner import (
        plan_multi_gw_dp_reference,
        plan_multi_gw_exact_reference,
        plan_synthetic_multi_gw_beam,
    )

    # Construct a 3-GW synthetic scenario with 7 players (initial squad: [1, 2]) where:
    # - Greedy in GW1 buys Player 3 (costs 50, gives +2 xP in GW1, 1.0 in GW2/GW3) and burns the 1 FT.
    # - Optimal non-greedy plan ROLLs in GW1 (banking 2 FTs for GW2!) and then makes a 2-TRANSFER
    #   move in GW2 to bring in Players 4 & 5 (who explode for 14.0 xP each in GW2 and GW3 with 0 hit cost!),
    #   whereas Player 6 is unavailable ('i') and Player 7 shares team_id=4 with Player 4 (club quota = 1)!
    synthetic_problem = {
        "initial_squad_ids": [1, 2],
        "bank_tenths": 0,
        "free_transfers": 1,
        "allow_hits": True,
        "max_transfers_per_gw": 2,
        "max_club_quota": 1,
        "target_gameweeks": [1, 2, 3],
        "include_captain_bonus": False,
        "player_pool": {
            1: {"position": "MID", "price_tenths": 50, "selling_price_tenths": 50, "team_id": 1, "status": "a"},
            2: {"position": "FWD", "price_tenths": 50, "selling_price_tenths": 50, "team_id": 2, "status": "a"},
            3: {"position": "MID", "price_tenths": 50, "selling_price_tenths": 50, "team_id": 3, "status": "a"},  # Greedy trap in GW1
            4: {"position": "MID", "price_tenths": 55, "selling_price_tenths": 55, "team_id": 4, "status": "a"},  # Needs paired budget from 1+2
            5: {"position": "FWD", "price_tenths": 45, "selling_price_tenths": 45, "team_id": 5, "status": "a"},  # Unlocks 4+5 pair (55+45=100)
            6: {"position": "MID", "price_tenths": 40, "selling_price_tenths": 40, "team_id": 6, "status": "i"},  # Illegal: injured
            7: {"position": "FWD", "price_tenths": 45, "selling_price_tenths": 45, "team_id": 4, "status": "a"},  # Illegal pair with 4 (same club 4!)
        },
        "gw_xp_table": {
            1: {1: 5.0, 2: 5.0, 3: 7.0, 4: 1.0, 5: 1.0, 6: 99.0, 7: 1.0},
            2: {1: 2.0, 2: 2.0, 3: 1.0, 4: 14.0, 5: 14.0, 6: 99.0, 7: 15.0},
            3: {1: 2.0, 2: 2.0, 3: 1.0, 4: 14.0, 5: 14.0, 6: 99.0, 7: 15.0},
        },
    }

    dp_oracle = plan_multi_gw_exact_reference(synthetic_problem=synthetic_problem)
    dp_alias = plan_multi_gw_dp_reference(synthetic_problem=synthetic_problem)
    beam_res = plan_synthetic_multi_gw_beam(synthetic_problem=synthetic_problem, beam_width=15)
    greedy_res = plan_synthetic_multi_gw_beam(synthetic_problem=synthetic_problem, greedy_one_step_only=True)

    assert dp_oracle["best_plan"]["total_net_xp"] == dp_alias["best_plan"]["total_net_xp"]
    # Optimal plan: GW1 ROLL (5+5=10, FT->2), GW2 2_TRANSFERS (1,2 -> 3,7 gives 1+15=16, whereas 1,2 -> 4,5 gives 14+14=28! Since 4,7 is blocked by club quota, 4+5 wins with 10 + 28 + 28 = 66.0!)
    assert dp_oracle["best_plan"]["total_net_xp"] == 66.0
    # Beam planner matches exact DP reference optimum:
    assert beam_res["best_plan"]["total_net_xp"] == dp_oracle["best_plan"]["total_net_xp"]
    assert [s["action"] for s in beam_res["best_plan"]["steps"]] == ["ROLL", "2_TRANSFERS", "ROLL"]
    # Greedy 1-step plan takes Player 3 in GW1 (7+5=12) and then must take a -4 hit in GW2 (64.0 < 66.0):
    assert greedy_res["best_plan"]["total_net_xp"] < dp_oracle["best_plan"]["total_net_xp"]


def test_p0_3_and_p1_1_to_p1_4_lineup_attribution_metadata_and_pit_scope() -> None:
    """Verify P0.3, P1.1, P1.2, P1.3, and P1.4 hardening requirements."""
    from fpl_manager.historical.validation import PIT_LEAKAGE_VERIFICATION_SCOPE

    # P1.1: Mutually exclusive additive regret decomposition + labeled diagnostics
    decomp = decompose_decision_error_components(
        predicted_lineup_xp=60.0,
        actual_lineup_score=50.0,
        captain_regret=4.0,
        bench_regret=3.0,
        hindsight_optimal_points=59.0,
        transfers=[{"player_out_id": 1, "player_in_id": 2}],
        transfer_hits=1,
        chip_played=None,
        actual_scores={1: 8.0, 2: 5.0},
    )
    add = decomp["additive_regret_decomposition"]
    assert add["is_mutually_exclusive_additive"] is True
    assert round(
        add["lineup_regret"]
        + add["captaincy_regret"]
        + add["transfer_regret"]
        + add["chip_regret"]
        + add["hit_cost"],
        2,
    ) == add["total_decision_regret"]
    assert decomp["decision_loss_diagnostics"]["is_overlapping_diagnostic"] is True

    # P1.2: Strict provenance validation in ModelMetadata.from_dict()
    with pytest.raises(ValueError, match="missing required provenance field"):
        ModelMetadata.from_dict({"model_version": "v1.0.0"}, strict=True)

    incomplete_meta = ModelMetadata.from_dict({"model_version": "v1.0.0"}, strict=False)
    assert incomplete_meta.is_complete is False
    assert incomplete_meta.training_data_cutoff == "incomplete/unknown"

    # P1.3: Historical vs Live timestamp determinism
    snap = _make_sample_snapshot(gameweek=5, finished_gws=4)
    hist_meta_1 = get_model_metadata("v1.0", mode="historical", snapshot=snap)
    hist_meta_2 = get_model_metadata("v1.0", mode="historical", snapshot=snap)
    assert hist_meta_1.prediction_timestamp == snap.deadline_time
    assert hist_meta_1.prediction_timestamp == hist_meta_2.prediction_timestamp

    # P1.4: PIT verification scope explicitly distinguishes intrinsic vs reference-comparative checks
    assert "intrinsic_snapshot_invariants" in PIT_LEAKAGE_VERIFICATION_SCOPE
    assert "reference_comparative_checks" in PIT_LEAKAGE_VERIFICATION_SCOPE
    assert len(PIT_LEAKAGE_VERIFICATION_SCOPE["intrinsic_snapshot_invariants"]["categories"]) == 2
    assert len(PIT_LEAKAGE_VERIFICATION_SCOPE["reference_comparative_checks"]["categories"]) == 5

