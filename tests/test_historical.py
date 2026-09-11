"""Tests for historical data ingestion and foundation (V0.7.0)."""

import csv
import json
from pathlib import Path
import pytest

from fpl_manager.historical.ingestion import (
    generate_mock_season,
    ingest_season,
    parse_fixtures_csv,
    parse_gw_csv,
    parse_teams_csv,
)
from fpl_manager.historical.models import Position, SeasonManifest


def test_generate_mock_season(tmp_path: Path) -> None:
    season_dir = tmp_path / "mock_2023_24"
    manifest = generate_mock_season(
        dest_dir=season_dir,
        season="2023-24",
        num_gameweeks=4,
        num_teams=4,
        players_per_team=5,
    )

    assert isinstance(manifest, SeasonManifest)
    assert manifest.season == "2023-24"
    assert manifest.total_gameweeks == 4
    assert manifest.num_teams == 4
    assert manifest.num_players == 20  # 4 * 5
    assert len(manifest.deadlines) == 4

    # Check files exist
    assert (season_dir / "teams.json").exists()
    assert (season_dir / "fixtures.json").exists()
    assert (season_dir / "season_manifest.json").exists()
    for gw in range(1, 5):
        assert (season_dir / "gws" / f"gw{gw}.json").exists()

    # Verify parsed content
    teams = json.loads((season_dir / "teams.json").read_text(encoding="utf-8"))
    assert len(teams) == 4
    assert teams[0]["short_name"] == "M01"

    gw1_players = json.loads((season_dir / "gws" / "gw1.json").read_text(encoding="utf-8"))
    assert len(gw1_players) == 20
    assert gw1_players[0]["player_id"] == 1


def test_parse_csv_and_ingest_season(tmp_path: Path) -> None:
    source_dir = tmp_path / "raw_source"
    source_dir.mkdir(parents=True)
    gws_dir = source_dir / "gws"
    gws_dir.mkdir(parents=True)

    # Create dummy teams.csv
    teams_csv = source_dir / "teams.csv"
    with teams_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "name", "short_name", "strength", "strength_overall_home", "strength_overall_away"])
        writer.writerow([1, "Arsenal", "ARS", 4, 1200, 1150])
        writer.writerow([2, "Aston Villa", "AVL", 3, 1100, 1050])

    # Create dummy fixtures.csv
    fixtures_csv = source_dir / "fixtures.csv"
    with fixtures_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "event", "team_h", "team_a", "team_h_difficulty", "team_a_difficulty", "kickoff_time", "finished"])
        writer.writerow([101, 1, 1, 2, 2, 4, "2023-08-12T11:30:00Z", "True"])

    # Create dummy gw1.csv
    gw1_csv = gws_dir / "gw1.csv"
    with gw1_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "element", "name", "position", "team", "value", "total_points",
            "minutes", "goals_scored", "assists", "clean_sheets", "goals_conceded",
            "bonus", "bps", "starts", "selected", "expected_goals", "expected_assists",
            "ict_index", "was_home", "opponent_team"
        ])
        writer.writerow([
            1, "Saka", "MID", 1, 85, 10,
            89, 1, 1, 0, 1,
            3, 38, 1, 55.4, 0.45, 0.35,
            12.4, "True", 2
        ])

    dest_dir = tmp_path / "normalized"
    manifest = ingest_season(season="2023-24", source_dir=source_dir, dest_dir=dest_dir)

    assert manifest.total_gameweeks == 1
    assert manifest.num_teams == 2
    assert manifest.num_players == 1
    assert manifest.deadlines[1] == "2023-08-12T11:30:00Z"

    # Verify JSON output
    gw1_json = json.loads((dest_dir / "gws" / "gw1.json").read_text(encoding="utf-8"))
    assert len(gw1_json) == 1
    p = gw1_json[0]
    assert p["name"] == "Saka"
    assert p["position"] == int(Position.MIDFIELDER)
    assert p["price_tenths"] == 85
    assert p["total_points"] == 10


def test_build_historical_snapshot_and_validation(tmp_path: Path) -> None:
    from fpl_manager.historical.snapshots import build_historical_snapshot, load_gameweek_outcomes
    from fpl_manager.historical.validation import (
        validate_no_future_leakage,
        validate_season_dataset,
        validate_snapshot_integrity,
    )

    season_dir = tmp_path / "mock_season"
    generate_mock_season(season_dir, season="2023-24", num_gameweeks=5, num_teams=6, players_per_team=5)

    # Validate dataset structure
    dataset_report = validate_season_dataset(season_dir)
    assert dataset_report["valid"] is True
    assert dataset_report["gameweeks_verified"] == 5

    # GW1 snapshot: MUST have 0 prior points and 0 prior minutes
    gw1_snapshot = build_historical_snapshot(season_dir, gameweek=1)
    assert gw1_snapshot.gameweek == 1
    assert gw1_snapshot.finished_gameweeks == 0
    assert len(gw1_snapshot.players) == 30  # 6 * 5

    gw1_issues = validate_snapshot_integrity(gw1_snapshot)
    assert gw1_issues == []

    gw1_outcomes = load_gameweek_outcomes(season_dir, gameweek=1)
    gw1_leakage = validate_no_future_leakage(gw1_snapshot, gw1_outcomes)
    assert gw1_leakage == []

    for p in gw1_snapshot.players:
        assert p.minutes == 0
        assert p.total_points == 0
        assert p.starts == 0

    # GW3 snapshot: Prior stats must strictly reflect GW1 + GW2 only
    gw3_snapshot = build_historical_snapshot(season_dir, gameweek=3)
    assert gw3_snapshot.gameweek == 3
    assert gw3_snapshot.finished_gameweeks == 2
    assert len(gw3_snapshot.fixtures) == 3  # 6 teams = 3 fixtures

    gw3_issues = validate_snapshot_integrity(gw3_snapshot)
    assert gw3_issues == []

    gw3_outcomes = load_gameweek_outcomes(season_dir, gameweek=3)
    gw3_leakage = validate_no_future_leakage(gw3_snapshot, gw3_outcomes)
    assert gw3_leakage == []

    # Check that a player who played in GW1 & GW2 has positive cumulative minutes,
    # but does NOT have GW3 minutes added into their snapshot!
    gw1_data = json.loads((season_dir / "gws" / "gw1.json").read_text(encoding="utf-8"))
    gw2_data = json.loads((season_dir / "gws" / "gw2.json").read_text(encoding="utf-8"))
    gw3_data = json.loads((season_dir / "gws" / "gw3.json").read_text(encoding="utf-8"))

    p1_gw1 = next(x for x in gw1_data if x["player_id"] == 1)
    p1_gw2 = next(x for x in gw2_data if x["player_id"] == 1)
    p1_gw3 = next(x for x in gw3_data if x["player_id"] == 1)

    p1_snap = next(x for x in gw3_snapshot.players if x.player_id == 1)
    expected_pts_prior = p1_gw1["total_points"] + p1_gw2["total_points"]
    assert p1_snap.total_points == expected_pts_prior
    # Invariant: GW3 points must NOT be in snapshot
    assert p1_snap.total_points != expected_pts_prior + p1_gw3["total_points"]

