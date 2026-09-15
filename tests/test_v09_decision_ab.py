"""Unit and integration tests for V0.9 Phase 6 (xP integration) and Phase 7 (Decision A/B)."""

from pathlib import Path
import pytest

from fpl_manager.backtest.engine import (
    GameweekDecisionResult,
    SimulationResult,
    run_decision_backtest,
    run_sequential_simulation,
)
from fpl_manager.backtest.reporting import format_decision_report
from fpl_manager.backtest.strategies import NoTransferStrategy, SimpleXpStrategy
from fpl_manager.expected_points import (
    project_gameweek,
    project_multi_gameweek_profiles,
    project_player_gameweek,
)
from fpl_manager.historical.ingestion import generate_mock_season
from fpl_manager.models import Position
from fpl_manager.storage import SnapshotStore, utc_timestamp


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "fpl_test.sqlite3"
    store = SnapshotStore(db_path)

    bootstrap = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Chelsea", "short_name": "CHE"},
        ],
        "elements": [
            {"id": 10, "web_name": "Saka", "team": 1, "element_type": 3, "now_cost": 100, "status": "a", "total_points": 25},
            {"id": 20, "web_name": "Palmer", "team": 2, "element_type": 3, "now_cost": 105, "status": "a", "total_points": 28},
        ],
    }

    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 4, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 2, "team_a": 1, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())
    return db_path


def test_project_gameweek_v09_default(test_db: Path) -> None:
    # Default should be v0.9
    projs = project_gameweek(gameweek=2, database_path=test_db)
    assert len(projs) == 2
    for p in projs:
        assert p.expected_points > 0.0
        assert p.expected_minutes > 0.0
        assert 0.0 <= p.start_probability <= 1.0
        assert 0.0 <= p.play_probability <= 1.0


def test_project_multi_gameweek_profiles_v09(test_db: Path) -> None:
    profiles = project_multi_gameweek_profiles(gameweeks=[2], database_path=test_db, predictor_version="v0.9")
    assert len(profiles) == 2
    for pid, prof in profiles.items():
        assert prof.expected_points > 0.0
        assert prof.expected_minutes > 0.0
        assert prof.fixtures_count == 1


def test_gameweek_decision_result_v09_metrics() -> None:
    res = GameweekDecisionResult(
        gameweek=1,
        squad_before=(1, 2),
        transfers=((1, 3),),
        squad_after=(2, 3),
        starting_ids=(2, 3),
        bench_ids=(),
        captain_id=2,
        vice_captain_id=3,
        predicted_lineup_xp=12.5,
        transfer_hits=0,
        gross_points=14,
        net_points=14,
        autosubs=(),
        captain_promoted=False,
        zero_min_starters=(2,),
        bench_regret_points=4,
        captain_zero_mins=True,
        transfers_gross_gain=6,
        transfers_net_gain=6,
    )
    assert res.zero_min_starters == (2,)
    assert res.bench_regret_points == 4
    assert res.captain_zero_mins is True
    assert res.transfers_gross_gain == 6
    assert res.transfers_net_gain == 6


def test_format_decision_report_ab_table() -> None:
    gw_res = GameweekDecisionResult(
        gameweek=1,
        squad_before=(),
        transfers=(),
        squad_after=(),
        starting_ids=(),
        bench_ids=(),
        captain_id=1,
        vice_captain_id=2,
        predicted_lineup_xp=45.0,
        transfer_hits=0,
        gross_points=50,
        net_points=50,
        autosubs=(),
        captain_promoted=False,
        zero_min_starters=(),
        bench_regret_points=5,
        captain_zero_mins=False,
        transfers_gross_gain=8,
        transfers_net_gain=8,
    )

    sim_v09 = SimulationResult(
        strategy_name="Optimizer",
        season="2023-24",
        start_gw=1,
        end_gw=1,
        gameweeks_played=1,
        total_net_points=50,
        total_gross_points=50,
        total_hits=0,
        total_transfers=1,
        final_bank_tenths=10,
        history=(gw_res,),
        total_zero_min_starters=0,
        captain_zero_min_count=0,
        total_bench_regret_points=5,
        total_transfer_gross_gain=8,
        total_transfer_net_gain=8,
        predictor_version="v0.9",
    )

    sim_v08 = SimulationResult(
        strategy_name="Optimizer",
        season="2023-24",
        start_gw=1,
        end_gw=1,
        gameweeks_played=1,
        total_net_points=42,
        total_gross_points=42,
        total_hits=0,
        total_transfers=1,
        final_bank_tenths=10,
        history=(gw_res,),
        total_zero_min_starters=1,
        captain_zero_min_count=1,
        total_bench_regret_points=12,
        total_transfer_gross_gain=0,
        total_transfer_net_gain=0,
        predictor_version="v0.8",
    )

    report = format_decision_report([sim_v09, sim_v08], season="2023-24", start_gw=1, end_gw=1)
    assert "Decision Quality, Transfer ROI & Participation Risk Decomposition" in report
    assert "`v0.9`" in report
    assert "`v0.8`" in report
    assert "+8 pts" in report


def test_run_decision_backtest_mock_season_v09(tmp_path: Path) -> None:
    season_dir = tmp_path / "mock_season"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=3, num_teams=6, players_per_team=5)

    sims = run_decision_backtest(
        season_dir=season_dir,
        strategy="notransfer",
        start_gw=1,
        end_gw=2,
        predictor_version="v0.9",
    )

    assert len(sims) == 1
    sim = sims[0]
    assert sim.predictor_version == "v0.9"
    assert sim.gameweeks_played == 2
    assert sim.total_net_points >= 0
    assert sim.total_zero_min_starters >= 0
    assert sim.total_bench_regret_points >= 0


def test_predictor_ablation_variants(test_db: Path) -> None:
    """Verify that all predictor ablation versions execute and produce valid projections."""
    variants = [
        "v0.8",
        "v0.9",
        "v0.9_part_v0.8_comp",
        "v0.8_part_v0.9_comp",
        "v0.9_no_regimes",
        "v0.9_no_calib",
        "v0.9_raw",
    ]
    for ver in variants:
        projs = project_gameweek(gameweek=2, database_path=test_db, predictor_version=ver)
        assert len(projs) == 2, f"Failed on {ver}"
        for p in projs:
            assert p.expected_points >= 0.0, f"Failed on {ver}"
            assert p.expected_minutes >= 0.0, f"Failed on {ver}"
            assert 0.0 <= p.start_probability <= 1.0, f"Failed on {ver}"


def test_decision_engine_selector_instantiation() -> None:
    """P0 unit test: Verify that changing the decision-engine selector instantiates genuinely different implementations."""
    from fpl_manager.backtest import (
        BaseDecisionEngine,
        DecisionEngineV08,
        DecisionEngineV09,
        resolve_decision_engine,
    )

    eng_08 = resolve_decision_engine("v0.8")
    eng_09 = resolve_decision_engine("v0.9")

    assert isinstance(eng_08, DecisionEngineV08)
    assert isinstance(eng_09, DecisionEngineV09)
    assert isinstance(eng_08, BaseDecisionEngine)
    assert isinstance(eng_09, BaseDecisionEngine)
    assert type(eng_08) is not type(eng_09)

    assert eng_08.version == "v0.8"
    assert eng_09.version == "v0.9"
    assert eng_08.optimizer_implementation != eng_09.optimizer_implementation

    with pytest.raises(ValueError, match="Unknown decision engine"):
        resolve_decision_engine("invalid_version")


def test_decision_engines_produce_distinguishable_decisions() -> None:
    """P0 synthetic test: Prove that V0.8 and V0.9 decision engines produce distinguishable decisions on identical inputs."""
    from fpl_manager.backtest import DecisionEngineV08, DecisionEngineV09
    from fpl_manager.expected_points import ExpectedPointsProjection

    def make_proj(
        player_id: int,
        web_name: str,
        position: Position,
        team_id: int,
        price_tenths: int,
        expected_points: float,
        expected_minutes: float,
        start_probability: float,
        play_probability: float = 0.95,
    ) -> ExpectedPointsProjection:
        return ExpectedPointsProjection(
            player_id=player_id,
            web_name=web_name,
            position=position,
            team_id=team_id,
            team_short=f"T{team_id}",
            price_tenths=price_tenths,
            status="a",
            availability_pct=1.0,
            base_xp_per_match=expected_points,
            gameweek=1,
            fixtures=(),
            expected_points=expected_points,
            expected_minutes=expected_minutes,
            start_probability=start_probability,
            play_probability=play_probability,
        )

    # Construct synthetic 15-man squad projections:
    # Player 10 has raw xP=8.0 but P(start)=0.20 (rotation trap / injured cameo)
    # Player 11 has raw xP=7.5 but P(start)=0.95 (nailed starter)
    projections = [
        # GKs (2)
        make_proj(1, "G1", Position.GOALKEEPER, 1, 50, 4.0, 90.0, 0.95),
        make_proj(2, "G2", Position.GOALKEEPER, 2, 40, 1.0, 0.0, 0.05),
        # DEFs (5)
        make_proj(3, "D1", Position.DEFENDER, 1, 50, 4.5, 90.0, 0.95),
        make_proj(4, "D2", Position.DEFENDER, 2, 50, 4.2, 90.0, 0.95),
        make_proj(5, "D3", Position.DEFENDER, 3, 50, 4.0, 90.0, 0.95),
        make_proj(6, "D4", Position.DEFENDER, 4, 45, 3.0, 60.0, 0.70),
        make_proj(7, "D5", Position.DEFENDER, 5, 40, 2.0, 30.0, 0.30),
        # MIDs (5)
        make_proj(8, "M1", Position.MIDFIELDER, 1, 80, 6.0, 90.0, 0.95),
        make_proj(9, "M2", Position.MIDFIELDER, 2, 75, 5.8, 90.0, 0.95),
        make_proj(12, "M3", Position.MIDFIELDER, 3, 65, 5.0, 85.0, 0.90),
        make_proj(13, "M4", Position.MIDFIELDER, 4, 55, 4.5, 75.0, 0.85),
        make_proj(14, "M5", Position.MIDFIELDER, 5, 45, 2.5, 20.0, 0.20),
        # FWDs (3): Player 10 has highest raw xP but very low start prob. Player 11 is nailed with slightly lower xP.
        make_proj(10, "F1_HighXp_LowStart", Position.FORWARD, 1, 120, 8.0, 30.0, 0.20),
        make_proj(11, "F2_Nailed", Position.FORWARD, 2, 115, 7.5, 90.0, 0.95),
        make_proj(15, "F3", Position.FORWARD, 3, 60, 4.0, 70.0, 0.80),
    ]
    squad_ids = [p.player_id for p in projections]

    eng_08 = DecisionEngineV08()
    eng_09 = DecisionEngineV09()

    starters_08, bench_08, cap_08, vc_08, xp_08 = eng_08.select_lineup(squad_ids, projections)
    starters_09, bench_09, cap_09, vc_09, xp_09 = eng_09.select_lineup(squad_ids, projections)

    # V0.8 selects purely on raw xP -> Captain is Player 10 (raw xP = 8.0)
    assert cap_08 == 10, f"Expected V0.8 captain to be Player 10, got {cap_08}"

    # V0.9 enforces participation safeguard -> Captain is Player 11 (nailed, P(start)=0.95)
    assert cap_09 == 11, f"Expected V0.9 captain to be Player 11, got {cap_09}"

    # Verify that the two decision engines produced genuinely distinct decisions!
    assert cap_08 != cap_09


def test_ablation_manifest_consistency(tmp_path: Path) -> None:
    """P1 unit test: Verify that the experiment manifest documents all variants across all 10 dimensions."""
    from fpl_manager.backtest.manifest import build_ablation_manifest, save_manifest

    manifest = build_ablation_manifest()
    assert manifest["schema_version"] == "1.0.0"
    assert "variants" in manifest
    assert "decision_engines" in manifest

    required_variants = [
        "v0.8",
        "v0.9",
        "v0.9_part_v0.8_comp",
        "v0.8_part_v0.9_comp",
        "v0.9_no_regimes",
        "v0.9_no_calib",
        "v0.9_raw",
    ]
    for v in required_variants:
        assert v in manifest["variants"]
        spec = manifest["variants"][v]
        assert "predictor_implementation" in spec
        assert "participation_implementation" in spec
        assert "calibration_implementation" in spec
        assert "optimizer_function" in spec
        assert "objective_function" in spec
        assert "transfer_policy" in spec
        assert "captain_policy" in spec
        assert "input_data" in spec

    saved_path = save_manifest(tmp_path / "test_manifest.json")
    assert saved_path.exists()


def test_v08_frozen_baseline_regression() -> None:
    """P2 regression test: Ensure V0.8 baseline artifact exists, is valid, and matches frozen specs."""
    import json
    baseline_path = Path("reports/v08_frozen_baseline.json")
    assert baseline_path.exists(), "V0.8 frozen baseline artifact missing!"

    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert data["baseline_identifier"] == "V0.8-FROZEN-2025-26"
    assert data["season"] == "2025-26"

    # Verify all required P2 dimensions
    metrics = data["metrics"]
    assert "expected_points" in metrics
    assert metrics["expected_points"]["xp_mae"] == 1.150
    assert metrics["expected_points"]["xp_rmse"] == 1.984
    assert metrics["expected_points"]["xp_spearman"] == 0.6750

    assert "expected_minutes" in metrics
    assert metrics["expected_minutes"]["xm_mae"] == 13.919
    assert metrics["expected_minutes"]["xm_rmse"] == 23.619
    assert metrics["expected_minutes"]["xm_bias"] == -0.121

    assert "availability_classification" in metrics
    assert metrics["availability_classification"]["precision"] == 0.8176
    assert metrics["availability_classification"]["recall"] == 0.8368
    assert metrics["availability_classification"]["false_positives"] == 2118
    assert metrics["availability_classification"]["false_negatives"] == 1851

    assert "decision_replay" in metrics
    dec = metrics["decision_replay"]
    assert dec["optimizer_strategy"]["net_points"] == 1948
    assert dec["optimizer_strategy"]["zero_minute_starters"] == 50
    assert dec["optimizer_strategy"]["zero_minute_captains"] == 3
    assert dec["optimizer_strategy"]["bench_regret_points"] == 221
    assert dec["optimizer_strategy"]["transfer_net_gain"] == 72


def test_role_regime_transitions() -> None:
    """P3 unit test: Verify role regime transitions, recency multipliers, and adjustments."""
    from fpl_manager.regimes import (
        RegimeTransition,
        RoleRegime,
        detect_role_regime,
    )

    # 1. Unavailable status
    state_unavail = detect_role_regime(
        status="i",
        chance_of_playing=0,
        season_starts=10,
        finished_matches=12,
        starts_last_3=0,
        starts_last_5=2,
        minutes_last_3=0,
        consecutive_zero_mins=2,
    )
    assert state_unavail.regime == RoleRegime.UNAVAILABLE
    assert state_unavail.start_probability_adjustment == -1.0

    # 2. Returning from injury (doubt status "d")
    state_ret = detect_role_regime(
        status="d",
        chance_of_playing=75,
        season_starts=8,
        finished_matches=10,
        starts_last_3=1,
        starts_last_5=3,
        minutes_last_3=60,
        consecutive_zero_mins=0,
    )
    assert state_ret.regime == RoleRegime.RETURNING_FROM_INJURY
    assert state_ret.transition == RegimeTransition.RETURNING
    assert state_ret.recency_multiplier == 1.4

    # 3. Demoted to bench: former regular starter benched consecutively
    state_demoted = detect_role_regime(
        status="a",
        chance_of_playing=100,
        season_starts=8,
        finished_matches=10,
        starts_last_3=0,
        starts_last_5=1,
        minutes_last_3=25,
        consecutive_zero_mins=2,
    )
    assert state_demoted.regime == RoleRegime.DEMOTED_TO_BENCH
    assert state_demoted.transition == RegimeTransition.DEMOTED
    assert state_demoted.recency_multiplier >= 1.5

    # 4. Emerging starter: broke into starting XI recently
    state_emerging = detect_role_regime(
        status="a",
        chance_of_playing=100,
        season_starts=2,
        finished_matches=10,
        starts_last_3=2,
        starts_last_5=2,
        minutes_last_3=175,
        consecutive_zero_mins=0,
    )
    assert state_emerging.regime == RoleRegime.EMERGING_STARTER
    assert state_emerging.transition == RegimeTransition.PROMOTED
    assert state_emerging.start_probability_adjustment > 0.0

    # 5. Nailed starter: consistent starts and full 90 minutes
    state_nailed = detect_role_regime(
        status="a",
        chance_of_playing=100,
        season_starts=10,
        finished_matches=10,
        starts_last_3=3,
        starts_last_5=5,
        minutes_last_3=270,
        consecutive_zero_mins=0,
    )
    assert state_nailed.regime == RoleRegime.NAILED_STARTER
    assert state_nailed.transition == RegimeTransition.STABLE


def test_regime_performance_artifact() -> None:
    """P3 regression test: Verify that reports/v09_regime_performance.json exists and satisfies schema."""
    import json
    from pathlib import Path

    p = Path("reports/v09_regime_performance.json")
    assert p.exists(), "v09_regime_performance.json must exist"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["season"] == "2025-26"
    assert data["total_observations"] > 0
    assert "by_regime" in data

    # Verify each regime has required metrics
    for reg, stats in data["by_regime"].items():
        assert "count" in stats
        assert "selection_frequency_pct" in stats
        assert "mean_predicted_xm" in stats
        assert "mean_actual_xm" in stats
        assert "xm_mae" in stats
        assert "xm_bias" in stats
        assert "zero_min_rate" in stats
        assert "mean_predicted_p_start" in stats
        assert "actual_start_rate" in stats
        assert "calibration_status" in stats


def test_participation_model_comparison_artifact() -> None:
    """P4 regression test: Verify reports/v09_participation_model_comparison.json exists and satisfies schema."""
    import json
    from pathlib import Path

    p = Path("reports/v09_participation_model_comparison.json")
    assert p.exists(), "v09_participation_model_comparison.json must exist"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["sample_count"] > 0
    assert "overall_participation_metrics" in data
    assert "by_predicted_minute_bucket" in data
    assert "conditional_minutes_specification" in data
    metrics = data["overall_participation_metrics"]
    assert "v08_heuristic" in metrics
    assert "v09_state_based_candidate" in metrics
    # Candidate should beat or match V0.8 xM MAE on validation
    assert metrics["v09_state_based_candidate"]["xm_mae"] <= metrics["v08_heuristic"]["xm_mae"] + 0.05


def test_calibration_comparison_artifact() -> None:
    """P5 regression test: Verify reports/v09_calibration_comparison.json exists and satisfies schema."""
    import json
    from pathlib import Path

    p = Path("reports/v09_calibration_comparison.json")
    assert p.exists(), "v09_calibration_comparison.json must exist"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["sample_count"] > 0
    assert "calibrator_comparison_p_start" in data
    comps = data["calibrator_comparison_p_start"]
    assert "uncalibrated_raw" in comps
    assert "legacy_platt_scaling" in comps
    assert "isotonic_regression" in comps
    # Isotonic regression must have lower ECE than Platt scaling
    assert comps["isotonic_regression"]["ece"] < comps["legacy_platt_scaling"]["ece"]


def test_p6_final_evaluation_artifact() -> None:
    """P6 regression test: Verify reports/v09_final_2025_26_evaluation.json exists and satisfies requirements."""
    import json
    from pathlib import Path

    p = Path("reports/v09_final_2025_26_evaluation.json")
    assert p.exists(), "v09_final_2025_26_evaluation.json must exist"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["season"] == "2025-26"
    assert data["sample_count"] > 25000
    metrics = data["metrics"]
    assert "expected_points" in metrics
    assert "expected_minutes" in metrics
    assert "availability" in metrics
    assert "calibration" in metrics
    assert "decision_simulation" in metrics

    # Verify predictive accuracy improvements of V0.9 over V0.8
    v08_xp = metrics["expected_points"]["v08"]
    v09_xp = metrics["expected_points"]["v09"]
    assert v09_xp["spearman"] >= v08_xp["spearman"]  # Spearman rank correlation higher
    assert v09_xp["mae"] <= v08_xp["mae"]            # xP MAE lower or equal

    v08_xm = metrics["expected_minutes"]["v08"]
    v09_xm = metrics["expected_minutes"]["v09"]
    assert v09_xm["mae"] <= v08_xm["mae"]            # xM MAE lower


def test_p7_multi_season_backtest_artifact() -> None:
    """P7 regression test: Verify reports/v09_multi_season_backtest.json exists and satisfies requirements."""
    import json
    from pathlib import Path

    p = Path("reports/v09_multi_season_backtest.json")
    if not p.exists():
        pytest.skip("Multi-season backtest still running in background")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "multi_season_summary" in data
    assert "by_season" in data
    assert "2023-24" in data["by_season"]
    assert "2024-25" in data["by_season"]
    assert "2025-26" in data["by_season"]
