"""Tests for historical season download utility and ingestion workflow."""

import io
import json
from pathlib import Path
import urllib.error
import urllib.request
import pytest

from fpl_manager.historical.ingestion import (
    SeasonManifest,
    download_historical_season,
    download_raw_season_data,
    normalize_season_name,
)
import scripts.download_historical as script_dl
import scripts.download_historical_season as script_dl_alias
from fpl_manager.cli import main as cli_main


def test_normalize_season_name() -> None:
    assert normalize_season_name("2021-22") == "2021-22"
    assert normalize_season_name("2021/22") == "2021-22"
    assert normalize_season_name("2021-2022") == "2021-22"
    assert normalize_season_name("2021/2022") == "2021-22"
    assert normalize_season_name("2021_22") == "2021-22"
    assert normalize_season_name("2021") == "2021-22"
    assert normalize_season_name(" 2023-24 ") == "2023-24"
    assert normalize_season_name("custom_name") == "custom_name"


class MockHTTPResponse(io.BytesIO):
    def __init__(self, data: bytes, status: int = 200) -> None:
        super().__init__(data)
        self.status = status

    def __enter__(self) -> "MockHTTPResponse":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


SAMPLE_TEAMS_CSV = b"""id,name,short_name,strength,strength_overall_home,strength_overall_away
1,Arsenal,ARS,4,1200,1150
2,Aston Villa,AVL,3,1100,1050
"""

SAMPLE_FIXTURES_CSV = b"""id,event,team_h,team_a,team_h_difficulty,team_a_difficulty,kickoff_time,finished
1,1,1,2,2,4,2021-08-13T19:00:00Z,True
2,2,2,1,4,2,2021-08-21T14:00:00Z,True
"""

SAMPLE_GW1_CSV = b"""element,name,position,team,value,total_points,minutes,goals_scored,assists,clean_sheets,goals_conceded,bonus,bps,starts,selected,expected_goals,expected_assists,ict_index,was_home,opponent_team
1,Saka,MID,1,65,5,90,0,1,0,1,0,18,1,12.5,0.25,0.30,7.5,True,2
2,Watkins,FWD,2,75,2,90,0,0,0,0,0,10,1,8.0,0.15,0.05,3.2,False,1
"""

SAMPLE_GW2_CSV = b"""element,name,position,team,value,total_points,minutes,goals_scored,assists,clean_sheets,goals_conceded,bonus,bps,starts,selected,expected_goals,expected_assists,ict_index,was_home,opponent_team
1,Saka,MID,1,65,8,90,1,0,0,0,1,26,1,14.0,0.40,0.10,9.0,False,2
2,Watkins,FWD,2,75,6,90,1,0,0,1,0,22,1,7.8,0.35,0.10,6.0,True,1
"""


def test_download_historical_season_mocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_urlopen(req: urllib.request.Request, timeout: float = 15.0) -> MockHTTPResponse:
        url = req.full_url
        if "fixtures.csv" in url:
            return MockHTTPResponse(SAMPLE_FIXTURES_CSV)
        if "teams.csv" in url:
            return MockHTTPResponse(SAMPLE_TEAMS_CSV)
        if "gw1.csv" in url:
            return MockHTTPResponse(SAMPLE_GW1_CSV)
        if "gw2.csv" in url:
            return MockHTTPResponse(SAMPLE_GW2_CSV)
        # GW3+ triggers 404 to stop downloading
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    raw_dir = tmp_path / "raw"
    dest_dir = tmp_path / "dest"
    logs: list[str] = []

    manifest = download_historical_season(
        season="2021-22",
        output_dir=dest_dir,
        raw_dir=raw_dir,
        max_gameweeks=5,
        progress_callback=logs.append,
    )

    assert isinstance(manifest, SeasonManifest)
    assert manifest.season == "2021-22"
    assert manifest.total_gameweeks == 2
    assert manifest.num_players == 2
    assert manifest.num_teams == 2

    # Check raw CSVs downloaded
    assert (raw_dir / "fixtures.csv").exists()
    assert (raw_dir / "teams.csv").exists()
    assert (raw_dir / "gws" / "gw1.csv").exists()
    assert (raw_dir / "gws" / "gw2.csv").exists()

    # Check ingested normalized JSONs
    assert (dest_dir / "fixtures.json").exists()
    assert (dest_dir / "teams.json").exists()
    assert (dest_dir / "season_manifest.json").exists()
    assert (dest_dir / "gws" / "gw1.json").exists()
    assert (dest_dir / "gws" / "gw2.json").exists()

    gw1_data = json.loads((dest_dir / "gws" / "gw1.json").read_text(encoding="utf-8"))
    assert len(gw1_data) == 2
    assert gw1_data[0]["name"] == "Saka"


def test_download_historical_season_raw_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_urlopen(req: urllib.request.Request, timeout: float = 15.0) -> MockHTTPResponse:
        url = req.full_url
        if "fixtures.csv" in url:
            return MockHTTPResponse(SAMPLE_FIXTURES_CSV)
        if "teams.csv" in url:
            return MockHTTPResponse(SAMPLE_TEAMS_CSV)
        if "gw1.csv" in url:
            return MockHTTPResponse(SAMPLE_GW1_CSV)
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    raw_dir = tmp_path / "raw"
    dest_dir = tmp_path / "dest"

    result_path = download_historical_season(
        season="2021-22",
        output_dir=dest_dir,
        raw_dir=raw_dir,
        max_gameweeks=3,
        raw_only=True,
    )

    assert isinstance(result_path, Path)
    assert result_path == raw_dir
    assert (raw_dir / "fixtures.csv").exists()
    assert not dest_dir.exists()


def test_download_historical_season_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_urlopen(req: urllib.request.Request, timeout: float = 15.0) -> MockHTTPResponse:
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", None, None)  # type: ignore

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    raw_dir = tmp_path / "raw"
    with pytest.raises(FileNotFoundError, match="not found in archive"):
        download_raw_season_data(season="1990-91", target_dir=raw_dir)


def test_script_main_execution(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    def fake_urlopen(req: urllib.request.Request, timeout: float = 15.0) -> MockHTTPResponse:
        url = req.full_url
        if "fixtures.csv" in url:
            return MockHTTPResponse(SAMPLE_FIXTURES_CSV)
        if "teams.csv" in url:
            return MockHTTPResponse(SAMPLE_TEAMS_CSV)
        if "gw1.csv" in url:
            return MockHTTPResponse(SAMPLE_GW1_CSV)
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    dest_dir = tmp_path / "normalized"
    raw_dir = tmp_path / "raw"

    # Test scripts/download_historical.py
    script_dl.main([
        "--season", "2021-22",
        "--dest-dir", str(dest_dir),
        "--raw-dir", str(raw_dir),
        "--max-gameweeks", "2",
    ])

    captured = capsys.readouterr().out
    assert "Successfully downloaded and ingested season '2021-22'" in captured
    assert (dest_dir / "season_manifest.json").exists()


def test_script_alias_execution(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    def fake_urlopen(req: urllib.request.Request, timeout: float = 15.0) -> MockHTTPResponse:
        url = req.full_url
        if "fixtures.csv" in url:
            return MockHTTPResponse(SAMPLE_FIXTURES_CSV)
        if "teams.csv" in url:
            return MockHTTPResponse(SAMPLE_TEAMS_CSV)
        if "gw1.csv" in url:
            return MockHTTPResponse(SAMPLE_GW1_CSV)
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    dest_dir = tmp_path / "alias_normalized"
    raw_dir = tmp_path / "alias_raw"

    script_dl_alias.main([
        "2021-22",
        "--dest-dir", str(dest_dir),
        "--raw-dir", str(raw_dir),
        "--max-gameweeks", "2",
        "--quiet",
    ])

    assert (dest_dir / "season_manifest.json").exists()


def test_cli_download_historical_subcommand(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    def fake_urlopen(req: urllib.request.Request, timeout: float = 15.0) -> MockHTTPResponse:
        url = req.full_url
        if "fixtures.csv" in url:
            return MockHTTPResponse(SAMPLE_FIXTURES_CSV)
        if "teams.csv" in url:
            return MockHTTPResponse(SAMPLE_TEAMS_CSV)
        if "gw1.csv" in url:
            return MockHTTPResponse(SAMPLE_GW1_CSV)
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    dest_dir = tmp_path / "cli_dest"
    raw_dir = tmp_path / "cli_raw"

    cli_main([
        "download-historical",
        "--season", "2021-22",
        "--dest-dir", str(dest_dir),
        "--raw-dir", str(raw_dir),
        "--max-gameweeks", "2",
    ])

    captured = capsys.readouterr().out
    assert "ready at" in captured
    assert (dest_dir / "season_manifest.json").exists()
