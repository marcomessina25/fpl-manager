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
