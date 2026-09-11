"""Strict temporal isolation tests verifying absence of future data leakage (V0.7.1)."""

import json
from pathlib import Path
import pytest

from fpl_manager.historical.ingestion import generate_mock_season
from fpl_manager.historical.reconstruction import reconstruct_features_and_project
from fpl_manager.historical.snapshots import build_historical_snapshot


def test_future_gw_data_does_not_affect_past_predictions(tmp_path: Path) -> None:
    """Verifies that altering data in GW3 has zero effect on GW1 and GW2 predictions."""
    season_dir = tmp_path / "leakage_test_season"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=4, num_teams=4, players_per_team=5)

    # 1. Generate predictions for GW1 and GW2
    snap_gw1_initial = build_historical_snapshot(season_dir, gameweek=1)
    proj_gw1_initial = reconstruct_features_and_project(snap_gw1_initial)

    snap_gw2_initial = build_historical_snapshot(season_dir, gameweek=2)
    proj_gw2_initial = reconstruct_features_and_project(snap_gw2_initial)

    # 2. Mutate future GW3 data dramatically (e.g. give player 1 50 goals and 100 points in GW3)
    gw3_path = season_dir / "gws" / "gw3.json"
    gw3_data = json.loads(gw3_path.read_text(encoding="utf-8"))
    for p in gw3_data:
        if p["player_id"] == 1:
            p["total_points"] = 100
            p["goals_scored"] = 25
            p["minutes"] = 90
            p["bonus"] = 3
    gw3_path.write_text(json.dumps(gw3_data, indent=2), encoding="utf-8")

    # 3. Regenerate GW1 and GW2 predictions
    snap_gw1_after = build_historical_snapshot(season_dir, gameweek=1)
    proj_gw1_after = reconstruct_features_and_project(snap_gw1_after)

    snap_gw2_after = build_historical_snapshot(season_dir, gameweek=2)
    proj_gw2_after = reconstruct_features_and_project(snap_gw2_after)

    # Assert exact identical projections for GW1
    for p_init, p_after in zip(proj_gw1_initial, proj_gw1_after):
        assert p_init.expected_points == p_after.expected_points
        assert p_init.expected_minutes == p_after.expected_minutes
        assert p_init.start_probability == p_after.start_probability

    # Assert exact identical projections for GW2
    for p_init, p_after in zip(proj_gw2_initial, proj_gw2_after):
        assert p_init.expected_points == p_after.expected_points
        assert p_init.expected_minutes == p_after.expected_minutes
        assert p_init.start_probability == p_after.start_probability


def test_gw_predictions_do_not_leak_current_gw_outcome(tmp_path: Path) -> None:
    """Verifies that altering GW2 outcome in gw2.json does NOT alter GW2 pre-deadline snapshot or prediction."""
    season_dir = tmp_path / "leakage_current_season"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=3, num_teams=4, players_per_team=5)

    snap_before = build_historical_snapshot(season_dir, gameweek=2)
    proj_before = reconstruct_features_and_project(snap_before)

    # Now change GW2 outcome points and minutes
    gw2_path = season_dir / "gws" / "gw2.json"
    gw2_data = json.loads(gw2_path.read_text(encoding="utf-8"))
    for p in gw2_data:
        p["total_points"] += 20
        p["minutes"] = 90
    gw2_path.write_text(json.dumps(gw2_data, indent=2), encoding="utf-8")

    snap_after = build_historical_snapshot(season_dir, gameweek=2)
    proj_after = reconstruct_features_and_project(snap_after)

    # Snapshot cumulative points and minutes must be unchanged because GW2 outcome is post-deadline
    for s_b, s_a in zip(snap_before.players, snap_after.players):
        assert s_b.total_points == s_a.total_points
        assert s_b.minutes == s_a.minutes

    # Predictions must be completely invariant to GW2 match outcomes
    for p_b, p_a in zip(proj_before, proj_after):
        assert p_b.expected_points == p_a.expected_points
        assert p_b.expected_minutes == p_a.expected_minutes


def test_inferred_status_does_not_leak_current_gw_minutes(tmp_path: Path) -> None:
    """Verifies that the inferred status heuristic for players with zero minutes in finished GWs (N >= 4)
    does NOT peek into the current Gameweek N minutes field.
    """
    season_dir = tmp_path / "inferred_status_leakage_season"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=5, num_teams=4, players_per_team=5)

    # Set player 1 to have 0 minutes across finished gameweeks 1, 2, 3
    for gw in (1, 2, 3):
        gw_path = season_dir / "gws" / f"gw{gw}.json"
        data = json.loads(gw_path.read_text(encoding="utf-8"))
        for p in data:
            if p["player_id"] == 1:
                p["minutes"] = 0
                p["starts"] = 0
                p["total_points"] = 0
        gw_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # Scenario A: In GW4 matchday, player 1 did not play (minutes = 0)
    gw4_path = season_dir / "gws" / "gw4.json"
    gw4_data = json.loads(gw4_path.read_text(encoding="utf-8"))
    for p in gw4_data:
        if p["player_id"] == 1:
            p["minutes"] = 0
            p["starts"] = 0
            p["total_points"] = 0
    gw4_path.write_text(json.dumps(gw4_data, indent=2), encoding="utf-8")

    snap_zero_mins = build_historical_snapshot(season_dir, gameweek=4)
    proj_zero_mins = reconstruct_features_and_project(snap_zero_mins)
    p1_snap_zero = next(p for p in snap_zero_mins.players if p.player_id == 1)
    p1_proj_zero = next(p for p in proj_zero_mins if p.player_id == 1)

    # Inferred status is 'd' because player had 0 minutes across 3 finished gameweeks (GW1..3)
    assert p1_snap_zero.status == "d"

    # Scenario B: In GW4 matchday, player 1 played 90 minutes and scored 15 points
    for p in gw4_data:
        if p["player_id"] == 1:
            p["minutes"] = 90
            p["starts"] = 1
            p["total_points"] = 15
            p["goals_scored"] = 2
    gw4_path.write_text(json.dumps(gw4_data, indent=2), encoding="utf-8")

    snap_full_mins = build_historical_snapshot(season_dir, gameweek=4)
    proj_full_mins = reconstruct_features_and_project(snap_full_mins)
    p1_snap_full = next(p for p in snap_full_mins.players if p.player_id == 1)
    p1_proj_full = next(p for p in proj_full_mins if p.player_id == 1)

    # Invariant: Prior to GW4 deadline, matchday GW4 minutes are strictly unrevealed.
    # Player's pre-deadline status and projections must be 100% identical between Scenario A and Scenario B.
    assert p1_snap_full.status == "d"
    assert p1_snap_full.status == p1_snap_zero.status
    assert p1_snap_full.minutes == p1_snap_zero.minutes == 0
    assert p1_snap_full.total_points == p1_snap_zero.total_points == 0
    assert p1_proj_full.expected_points == p1_proj_zero.expected_points
    assert p1_proj_full.expected_minutes == p1_proj_zero.expected_minutes
    assert p1_proj_full.start_probability == p1_proj_zero.start_probability


def test_complete_matchday_outcome_isolation_for_current_gw(tmp_path: Path) -> None:
    """Verifies that arbitrarily mutating all matchday outcome fields in gwN.json
    has zero effect on the pre-deadline snapshot and expected points projections.
    """
    season_dir = tmp_path / "complete_isolation_season"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=5, num_teams=4, players_per_team=5)

    snap_clean = build_historical_snapshot(season_dir, gameweek=4)
    proj_clean = reconstruct_features_and_project(snap_clean)

    # Mutate every single matchday outcome field in gw4.json
    gw4_path = season_dir / "gws" / "gw4.json"
    gw4_data = json.loads(gw4_path.read_text(encoding="utf-8"))
    for p in gw4_data:
        p["minutes"] = 120
        p["total_points"] = 50
        p["goals_scored"] = 5
        p["assists"] = 3
        p["clean_sheets"] = 1
        p["goals_conceded"] = 4
        p["bonus"] = 3
        p["bps"] = 99
        p["expected_goals"] = 4.5
        p["expected_assists"] = 3.2
        p["expected_goal_involvements"] = 7.7
        p["expected_goals_conceded"] = 2.8
        p["ict_index"] = 25.0
    gw4_path.write_text(json.dumps(gw4_data, indent=2), encoding="utf-8")

    snap_mutated = build_historical_snapshot(season_dir, gameweek=4)
    proj_mutated = reconstruct_features_and_project(snap_mutated)

    # Verify every player in snapshot is identical
    assert len(snap_clean.players) == len(snap_mutated.players)
    for p_clean, p_mut in zip(snap_clean.players, snap_mutated.players):
        assert p_clean.player_id == p_mut.player_id
        assert p_clean.status == p_mut.status
        assert p_clean.total_points == p_mut.total_points
        assert p_clean.minutes == p_mut.minutes
        assert p_clean.starts == p_mut.starts
        assert p_clean.expected_goals == p_mut.expected_goals
        assert p_clean.expected_assists == p_mut.expected_assists
        assert p_clean.expected_goal_involvements == p_mut.expected_goal_involvements
        assert p_clean.expected_goals_conceded == p_mut.expected_goals_conceded
        assert p_clean.bps == p_mut.bps
        assert p_clean.ict_index == p_mut.ict_index
        assert p_clean.form == p_mut.form
        assert p_clean.points_per_game == p_mut.points_per_game

    # Verify every projection is identical
    for pr_clean, pr_mut in zip(proj_clean, proj_mutated):
        assert pr_clean.player_id == pr_mut.player_id
        assert pr_clean.expected_points == pr_mut.expected_points
        assert pr_clean.expected_minutes == pr_mut.expected_minutes
        assert pr_clean.start_probability == pr_mut.start_probability
        assert pr_clean.standard_deviation == pr_mut.standard_deviation
        assert pr_clean.xp_floor == pr_mut.xp_floor
        assert pr_clean.xp_ceiling == pr_mut.xp_ceiling

