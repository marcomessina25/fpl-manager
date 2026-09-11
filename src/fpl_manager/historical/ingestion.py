"""Historical data ingestion engine for FPL Manager V0.7.

Downloads, normalizes, and validates historical season data from public archives
(such as the standard vaastav Fantasy-Premier-League repository) or local directories.
Provides synthetic season generation for hermetic, fast testing.
"""

import csv
import json
import logging
from pathlib import Path
import re
from typing import Any, Callable
import urllib.request
import urllib.error

from .models import Position, SeasonManifest

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_HISTORICAL_DIR = DEFAULT_DATA_DIR / "historical"
DEFAULT_HISTORICAL_RAW_DIR = DEFAULT_HISTORICAL_DIR / "raw"

GITHUB_RAW_BASE = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"


def normalize_season_name(season: str) -> str:
    """Normalize season input strings into canonical 'YYYY-YY' format.

    Examples:
        '2021-22' -> '2021-22'
        '2021/22' -> '2021-22'
        '2021-2022' -> '2021-22'
        '2021/2022' -> '2021-22'
        '2021_22' -> '2021-22'
        '2021' -> '2021-22'
    """
    s = season.strip()
    m_full = re.match(r"^(\d{4})[-/_](\d{4})$", s)
    if m_full:
        y1, y2 = m_full.groups()
        return f"{y1}-{y2[-2:]}"
    m_short = re.match(r"^(\d{4})[-/_](\d{2})$", s)
    if m_short:
        y1, y2 = m_short.groups()
        return f"{y1}-{y2}"
    m_single = re.match(r"^(\d{4})$", s)
    if m_single:
        y1 = int(m_single.group(1))
        y2 = (y1 + 1) % 100
        return f"{y1}-{y2:02d}"
    return s


def _safe_int(val: Any, default: int = 0) -> int:
    if val is None or val == "":
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def download_raw_season_data(
    season: str,
    target_dir: Path,
    max_gameweeks: int = 38,
    timeout_seconds: float = 15.0,
    overwrite: bool = False,
    progress_callback: Callable[[str], None] | None = None,
) -> Path:
    """Download raw CSV files for a historical season from the Vaastav FPL archive."""
    canonical_season = normalize_season_name(season)
    target_dir.mkdir(parents=True, exist_ok=True)
    gws_dir = target_dir / "gws"
    gws_dir.mkdir(parents=True, exist_ok=True)

    base_url = f"{GITHUB_RAW_BASE}/{canonical_season}"

    def report(msg: str) -> None:
        LOGGER.info(msg)
        if progress_callback:
            progress_callback(msg)

    # Download fixtures.csv
    fixtures_path = target_dir / "fixtures.csv"
    if overwrite or not fixtures_path.exists():
        url = f"{base_url}/fixtures.csv"
        report(f"Fetching {url}...")
        req = urllib.request.Request(url, headers={"User-Agent": "fpl-manager"})
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                fixtures_path.write_bytes(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(
                    f"Season '{canonical_season}' not found in archive ({url}). Please verify the season format (e.g., '2021-22')."
                ) from exc
            raise

    # Download teams.csv
    teams_path = target_dir / "teams.csv"
    if overwrite or not teams_path.exists():
        url = f"{base_url}/teams.csv"
        report(f"Fetching {url}...")
        req = urllib.request.Request(url, headers={"User-Agent": "fpl-manager"})
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                teams_path.write_bytes(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(
                    f"teams.csv for season '{canonical_season}' not found in archive ({url})."
                ) from exc
            raise

    # Download each GW file
    downloaded_any = False
    for gw in range(1, max_gameweeks + 1):
        gw_path = gws_dir / f"gw{gw}.csv"
        if not overwrite and gw_path.exists():
            downloaded_any = True
            continue
        url = f"{base_url}/gws/gw{gw}.csv"
        report(f"Fetching Gameweek {gw}/{max_gameweeks} ({url})...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "fpl-manager"})
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                gw_path.write_bytes(resp.read())
            downloaded_any = True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                LOGGER.warning("Gameweek %d not found for season %s. Stopping at GW %d.", gw, canonical_season, gw - 1)
                break
            raise

    if not downloaded_any and not any(gws_dir.glob("gw*.csv")):
        raise FileNotFoundError(f"No gameweek files found for season '{canonical_season}' in archive.")

    return target_dir


def parse_teams_csv(teams_csv_path: Path) -> list[dict[str, Any]]:
    """Parse teams.csv into normalized team records."""
    teams: list[dict[str, Any]] = []
    with teams_csv_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            team_id = _safe_int(row.get("id"))
            name = str(row.get("name", f"Team {team_id}"))
            short_name = str(row.get("short_name", name[:3].upper()))
            strength = _safe_int(row.get("strength"), 3)
            strength_overall_home = _safe_int(row.get("strength_overall_home"), 1000)
            strength_overall_away = _safe_int(row.get("strength_overall_away"), 1000)
            teams.append({
                "team_id": team_id,
                "name": name,
                "short_name": short_name,
                "strength": strength,
                "strength_overall_home": strength_overall_home,
                "strength_overall_away": strength_overall_away,
            })
    teams.sort(key=lambda t: t["team_id"])
    return teams


def parse_fixtures_csv(fixtures_csv_path: Path) -> list[dict[str, Any]]:
    """Parse fixtures.csv into normalized fixture records."""
    fixtures: list[dict[str, Any]] = []
    with fixtures_csv_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            event_val = row.get("event")
            if not event_val or event_val == "None":
                continue
            event = _safe_int(event_val)
            fid = _safe_int(row.get("id"))
            team_h = _safe_int(row.get("team_h"))
            team_a = _safe_int(row.get("team_a"))
            h_diff = _safe_int(row.get("team_h_difficulty"), 3)
            a_diff = _safe_int(row.get("team_a_difficulty"), 3)
            finished = 1 if str(row.get("finished", "")).lower() in ("true", "1") else 0
            kickoff = row.get("kickoff_time")
            fixtures.append({
                "fixture_id": fid,
                "event": event,
                "team_h": team_h,
                "team_a": team_a,
                "team_h_difficulty": h_diff,
                "team_a_difficulty": a_diff,
                "kickoff_time": kickoff,
                "finished": finished,
            })
    fixtures.sort(key=lambda f: (f["event"], f["fixture_id"]))
    return fixtures


def parse_gw_csv(gw_csv_path: Path, team_name_to_id: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Parse a single gameweek CSV into normalized player performance dictionaries."""
    records: list[dict[str, Any]] = []
    t_map = team_name_to_id or {}
    with gw_csv_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            element = _safe_int(row.get("element", row.get("id")))
            name = str(row.get("name", row.get("web_name", f"Player {element}")))
            pos_str = str(row.get("position", "MID")).upper()
            if pos_str in ("1", "GK", "GKP"):
                pos = Position.GOALKEEPER
            elif pos_str in ("2", "DEF", "DEFENDER"):
                pos = Position.DEFENDER
            elif pos_str in ("3", "MID", "MIDFIELDER"):
                pos = Position.MIDFIELDER
            elif pos_str in ("4", "FWD", "FORWARD"):
                pos = Position.FORWARD
            else:
                pos = Position.MIDFIELDER

            team_raw = row.get("team", row.get("team_id", 1))
            if str(team_raw) in t_map:
                team_id = t_map[str(team_raw)]
            else:
                team_id = _safe_int(team_raw, 0)
                if team_id == 0 and str(team_raw).strip() in t_map:
                    team_id = t_map[str(team_raw).strip()]
                elif team_id == 0:
                    # fallback to 1 if entirely unknown
                    team_id = 1
            val = _safe_int(row.get("value"), 50)  # in tenths (e.g. 50 = £5.0m)
            total_points = _safe_int(row.get("total_points"))
            minutes = _safe_int(row.get("minutes"))
            goals_scored = _safe_int(row.get("goals_scored"))
            assists = _safe_int(row.get("assists"))
            clean_sheets = _safe_int(row.get("clean_sheets"))
            goals_conceded = _safe_int(row.get("goals_conceded"))
            bonus = _safe_int(row.get("bonus"))
            bps = _safe_int(row.get("bps"))
            starts = _safe_int(row.get("starts"), 1 if minutes >= 60 else 0)
            selected = _safe_float(row.get("selected", row.get("selected_by_percent", 0.0)))
            xg = _safe_float(row.get("expected_goals", 0.0))
            xa = _safe_float(row.get("expected_assists", 0.0))
            xgi = _safe_float(row.get("expected_goal_involvements", xg + xa))
            xgc = _safe_float(row.get("expected_goals_conceded", 0.0))
            ict = _safe_float(row.get("ict_index", 0.0))
            was_home = str(row.get("was_home", "True")).lower() in ("true", "1")
            opp_team = _safe_int(row.get("opponent_team", 0))

            records.append({
                "player_id": element,
                "name": name,
                "position": int(pos),
                "team_id": team_id,
                "price_tenths": val,
                "total_points": total_points,
                "minutes": minutes,
                "starts": starts,
                "goals_scored": goals_scored,
                "assists": assists,
                "clean_sheets": clean_sheets,
                "goals_conceded": goals_conceded,
                "bonus": bonus,
                "bps": bps,
                "selected": selected,
                "expected_goals": xg,
                "expected_assists": xa,
                "expected_goal_involvements": xgi,
                "expected_goals_conceded": xgc,
                "ict_index": ict,
                "was_home": was_home,
                "opponent_team_id": opp_team,
            })
    records.sort(key=lambda r: r["player_id"])
    return records


def ingest_season(
    season: str,
    source_dir: Path,
    dest_dir: Path,
) -> SeasonManifest:
    """Normalize raw CSV files from source_dir and compile structured JSON data into dest_dir."""
    canonical_season = normalize_season_name(season)
    dest_dir.mkdir(parents=True, exist_ok=True)
    teams = parse_teams_csv(source_dir / "teams.csv")
    fixtures = parse_fixtures_csv(source_dir / "fixtures.csv")

    (dest_dir / "teams.json").write_text(json.dumps(teams, indent=2), encoding="utf-8")
    (dest_dir / "fixtures.json").write_text(json.dumps(fixtures, indent=2), encoding="utf-8")

    gws_source = source_dir / "gws"
    gw_files = sorted(gws_source.glob("gw*.csv"), key=lambda p: int(p.stem.replace("gw", "")))
    if not gw_files:
        raise ValueError(f"No gw*.csv files found in {gws_source}")

    gws_dest = dest_dir / "gws"
    gws_dest.mkdir(parents=True, exist_ok=True)

    all_player_ids: set[int] = set()
    deadlines: dict[int, str] = {}
    team_map = {t["name"]: t["team_id"] for t in teams}
    team_map.update({t["short_name"]: t["team_id"] for t in teams})

    for gw_file in gw_files:
        gw_num = int(gw_file.stem.replace("gw", ""))
        gw_data = parse_gw_csv(gw_file, team_name_to_id=team_map)
        for r in gw_data:
            all_player_ids.add(r["player_id"])
        (gws_dest / f"gw{gw_num}.json").write_text(json.dumps(gw_data, indent=2), encoding="utf-8")

        # Derive nominal deadline from earliest fixture kickoff in that gameweek
        gw_fixtures = [f for f in fixtures if f["event"] == gw_num and f.get("kickoff_time")]
        if gw_fixtures:
            earliest_kickoff = min(f["kickoff_time"] for f in gw_fixtures if f["kickoff_time"])
            deadlines[gw_num] = earliest_kickoff
        else:
            deadlines[gw_num] = f"2023-08-11T18:00:00Z"

    manifest = SeasonManifest(
        season=canonical_season,
        total_gameweeks=len(gw_files),
        num_players=len(all_player_ids),
        num_teams=len(teams),
        num_fixtures=len(fixtures),
        deadlines=deadlines,
    )

    manifest_dict = {
        "season": manifest.season,
        "total_gameweeks": manifest.total_gameweeks,
        "num_players": manifest.num_players,
        "num_teams": manifest.num_teams,
        "num_fixtures": manifest.num_fixtures,
        "deadlines": manifest.deadlines,
    }
    (dest_dir / "season_manifest.json").write_text(json.dumps(manifest_dict, indent=2), encoding="utf-8")

    LOGGER.info("Ingested season %s: %d gameweeks, %d players, %d teams.", canonical_season, len(gw_files), len(all_player_ids), len(teams))
    return manifest


def download_historical_season(
    season: str,
    output_dir: Path | None = None,
    raw_dir: Path | None = None,
    max_gameweeks: int = 38,
    timeout_seconds: float = 15.0,
    overwrite: bool = False,
    raw_only: bool = False,
    progress_callback: Callable[[str], None] | None = None,
) -> SeasonManifest | Path:
    """Download and optionally ingest a historical season dataset.

    Args:
        season: Historical season string (e.g. '2021-22').
        output_dir: Target destination for normalized JSON dataset (default: data/historical/<season>).
        raw_dir: Target destination for downloaded raw CSVs (default: data/historical/raw/<season>).
        max_gameweeks: Maximum number of gameweeks to download (default: 38).
        timeout_seconds: Network request timeout in seconds.
        overwrite: If True, re-download existing files.
        raw_only: If True, download raw CSVs without compiling normalized JSON files.
        progress_callback: Optional callable receiving progress messages.

    Returns:
        SeasonManifest if normalized/ingested, or Path to raw directory if raw_only is True.
    """
    canonical_season = normalize_season_name(season)
    target_raw_dir = Path(raw_dir) if raw_dir is not None else (DEFAULT_HISTORICAL_RAW_DIR / canonical_season)
    target_dest_dir = Path(output_dir) if output_dir is not None else (DEFAULT_HISTORICAL_DIR / canonical_season)

    download_raw_season_data(
        season=canonical_season,
        target_dir=target_raw_dir,
        max_gameweeks=max_gameweeks,
        timeout_seconds=timeout_seconds,
        overwrite=overwrite,
        progress_callback=progress_callback,
    )

    if raw_only:
        return target_raw_dir

    if progress_callback:
        progress_callback(f"Normalizing and ingesting season '{canonical_season}' into {target_dest_dir}...")

    manifest = ingest_season(
        season=canonical_season,
        source_dir=target_raw_dir,
        dest_dir=target_dest_dir,
    )

    return manifest


def generate_mock_season(
    dest_dir: Path,
    season: str = "2023-24",
    num_gameweeks: int = 5,
    num_teams: int = 6,
    players_per_team: int = 5,
) -> SeasonManifest:
    """Generate a fully coherent mock season dataset for fast, hermetic unit tests."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    gws_dest = dest_dir / "gws"
    gws_dest.mkdir(parents=True, exist_ok=True)

    teams = []
    for t_id in range(1, num_teams + 1):
        teams.append({
            "team_id": t_id,
            "name": f"Mock FC {t_id}",
            "short_name": f"M{t_id:02d}",
            "strength": 3,
            "strength_overall_home": 1050,
            "strength_overall_away": 1020,
        })
    (dest_dir / "teams.json").write_text(json.dumps(teams, indent=2), encoding="utf-8")

    fixtures = []
    f_id = 1
    deadlines = {}
    for gw in range(1, num_gameweeks + 1):
        deadlines[gw] = f"2023-09-0{gw}T11:00:00Z"
        for i in range(0, num_teams, 2):
            h_team = i + 1
            a_team = i + 2
            fixtures.append({
                "fixture_id": f_id,
                "event": gw,
                "team_h": h_team,
                "team_a": a_team,
                "team_h_difficulty": 3,
                "team_a_difficulty": 3,
                "kickoff_time": f"2023-09-0{gw}T12:30:00Z",
                "finished": 1,
            })
            f_id += 1
    (dest_dir / "fixtures.json").write_text(json.dumps(fixtures, indent=2), encoding="utf-8")

    # Generate players: 1 GKP, 2 DEF, 1 MID, 1 FWD per team
    positions_cycle = [Position.GOALKEEPER, Position.DEFENDER, Position.DEFENDER, Position.MIDFIELDER, Position.FORWARD]
    all_player_ids = set()

    for gw in range(1, num_gameweeks + 1):
        gw_records = []
        p_id = 1
        for t_id in range(1, num_teams + 1):
            for p_idx in range(players_per_team):
                pos = positions_cycle[p_idx % len(positions_cycle)]
                all_player_ids.add(p_id)
                # Realistic synthetic scores
                mins = 90 if p_id % 7 != 0 else 0
                pts = (6 if pos == Position.FORWARD and mins > 0 else (4 if mins > 0 else 0)) + (gw % 3)
                gw_records.append({
                    "player_id": p_id,
                    "name": f"Player_{p_id}",
                    "position": int(pos),
                    "team_id": t_id,
                    "price_tenths": 40 + (p_id % 8) * 5,
                    "total_points": pts,
                    "minutes": mins,
                    "starts": 1 if mins >= 60 else 0,
                    "goals_scored": 1 if (pos in (Position.MIDFIELDER, Position.FORWARD) and mins > 0 and (p_id + gw) % 4 == 0) else 0,
                    "assists": 1 if mins > 0 and (p_id + gw) % 5 == 0 else 0,
                    "clean_sheets": 1 if pos in (Position.GOALKEEPER, Position.DEFENDER) and mins >= 60 and gw % 2 == 0 else 0,
                    "goals_conceded": 1 if mins > 0 and gw % 2 != 0 else 0,
                    "bonus": 2 if pts >= 6 else 0,
                    "bps": pts * 4,
                    "selected": 10.5,
                    "expected_goals": 0.35 if pos == Position.FORWARD else 0.05,
                    "expected_assists": 0.20 if pos == Position.MIDFIELDER else 0.05,
                    "expected_goal_involvements": 0.40,
                    "expected_goals_conceded": 1.20,
                    "ict_index": 4.5,
                    "was_home": (t_id % 2 != 0),
                    "opponent_team_id": t_id + 1 if t_id % 2 != 0 else t_id - 1,
                })
                p_id += 1
        (gws_dest / f"gw{gw}.json").write_text(json.dumps(gw_records, indent=2), encoding="utf-8")

    manifest = SeasonManifest(
        season=season,
        total_gameweeks=num_gameweeks,
        num_players=len(all_player_ids),
        num_teams=num_teams,
        num_fixtures=len(fixtures),
        deadlines=deadlines,
    )
    manifest_dict = {
        "season": manifest.season,
        "total_gameweeks": manifest.total_gameweeks,
        "num_players": manifest.num_players,
        "num_teams": manifest.num_teams,
        "num_fixtures": manifest.num_fixtures,
        "deadlines": manifest.deadlines,
    }
    (dest_dir / "season_manifest.json").write_text(json.dumps(manifest_dict, indent=2), encoding="utf-8")
    return manifest
