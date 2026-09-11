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
