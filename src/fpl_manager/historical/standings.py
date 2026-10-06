"""Historical league standings and point-in-time fixture service.

Ensures strict zero-leakage / no spoilers for historical simulation (V1.4):
- Standings and past results strictly reflect matches finished before gameweek N deadline.
- Upcoming fixtures expose only scheduling/difficulty metadata (FDR, venue, kickoff),
  guaranteeing scores and future outcomes are completely masked.
"""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_HISTORICAL_DIR = PROJECT_ROOT / "data" / "historical"


@dataclass(frozen=True, slots=True)
class TeamStanding:
    """League table row for a team at a specific historical point in time."""
    position: int
    team_id: int
    name: str
    short_name: str
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_difference: int
    points: int
    form: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        res = asdict(self)
        res["form"] = list(self.form)
        return res


@dataclass(frozen=True, slots=True)
class HistoricalFixtureResult:
    """Historical fixture with completed match score strictly from previous gameweeks."""
    fixture_id: int
    event: int
    kickoff_time: str | None
    team_h: int
    team_h_name: str
    team_h_short: str
    team_a: int
    team_a_name: str
    team_a_short: str
    team_h_score: int
    team_a_score: int
    team_h_difficulty: int
    team_a_difficulty: int
    finished: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HistoricalUpcomingFixture:
    """Upcoming fixture for the current or future gameweek with ZERO score leakage."""
    fixture_id: int
    event: int
    kickoff_time: str | None
    team_h: int
    team_h_name: str
    team_h_short: str
    team_a: int
    team_a_name: str
    team_a_short: str
    team_h_difficulty: int
    team_a_difficulty: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _get_season_dir(season: str, data_dir: Path | None = None) -> Path:
    base = data_dir or DEFAULT_HISTORICAL_DIR
    season_dir = base / season
    if not season_dir.exists():
        raise FileNotFoundError(f"Historical season directory not found: {season_dir}")
    return season_dir


def _load_teams_map(season_dir: Path) -> dict[int, dict[str, Any]]:
    teams_path = season_dir / "teams.json"
    if not teams_path.exists():
        raise FileNotFoundError(f"teams.json not found in {season_dir}")
    teams = json.loads(teams_path.read_text(encoding="utf-8"))
    return {t["team_id"]: t for t in teams}


def _load_fixtures_data(season_dir: Path) -> list[dict[str, Any]]:
    fixtures_path = season_dir / "fixtures.json"
    if not fixtures_path.exists():
        raise FileNotFoundError(f"fixtures.json not found in {season_dir}")
    return json.loads(fixtures_path.read_text(encoding="utf-8"))


def compute_standings_from_data(
    fixtures_data: list[dict[str, Any]],
    teams_map: dict[int, dict[str, Any]],
    up_to_gw: int,
) -> list[TeamStanding]:
    """Compute league standings using fixtures and teams map strictly for event < up_to_gw."""
    # Initialize stats per team
    stats: dict[int, dict[str, Any]] = {
        tid: {
            "team_id": tid,
            "name": t["name"],
            "short_name": t["short_name"],
            "played": 0,
            "won": 0,
            "drawn": 0,
            "lost": 0,
            "goals_for": 0,
            "goals_against": 0,
            "points": 0,
            "results": [],  # list of (kickoff_time or event, result_char)
        }
        for tid, t in teams_map.items()
    }

    # Process completed fixtures strictly from event < up_to_gw
    for f in fixtures_data:
        event = f.get("event")
        if event is None or event >= up_to_gw:
            continue
        if not f.get("finished"):
            continue
        h_score = f.get("team_h_score")
        a_score = f.get("team_a_score")
        if h_score is None or a_score is None:
            continue

        th = f.get("team_h")
        ta = f.get("team_a")
        if th not in stats or ta not in stats:
            continue

        th_stat = stats[th]
        ta_stat = stats[ta]

        th_stat["played"] += 1
        ta_stat["played"] += 1
        th_stat["goals_for"] += int(h_score)
        th_stat["goals_against"] += int(a_score)
        ta_stat["goals_for"] += int(a_score)
        ta_stat["goals_against"] += int(h_score)

        ko = f.get("kickoff_time") or f"GW{event:02d}_{f.get('fixture_id', f.get('id', 0))}"

        if int(h_score) > int(a_score):
            th_stat["won"] += 1
            th_stat["points"] += 3
            ta_stat["lost"] += 1
            th_stat["results"].append((ko, "W"))
            ta_stat["results"].append((ko, "L"))
        elif int(h_score) < int(a_score):
            ta_stat["won"] += 1
            ta_stat["points"] += 3
            th_stat["lost"] += 1
            th_stat["results"].append((ko, "L"))
            ta_stat["results"].append((ko, "W"))
        else:
            th_stat["drawn"] += 1
            th_stat["points"] += 1
            ta_stat["drawn"] += 1
            ta_stat["points"] += 1
            th_stat["results"].append((ko, "D"))
            ta_stat["results"].append((ko, "D"))

    # Convert to list and calculate goal difference
    standings_raw = []
    for s in stats.values():
        gd = s["goals_for"] - s["goals_against"]
        # Sort results chronologically and take last 5 for form
        s["results"].sort(key=lambda r: str(r[0]))
        form_recent = tuple(r[1] for r in s["results"][-5:])
        standings_raw.append({
            "team_id": s["team_id"],
            "name": s["name"],
            "short_name": s["short_name"],
            "played": s["played"],
            "won": s["won"],
            "drawn": s["drawn"],
            "lost": s["lost"],
            "goals_for": s["goals_for"],
            "goals_against": s["goals_against"],
            "goal_difference": gd,
            "points": s["points"],
            "form": form_recent,
        })

    # Sort standard PL rules: Points desc, GD desc, GF desc, Name asc
    standings_raw.sort(
        key=lambda item: (-item["points"], -item["goal_difference"], -item["goals_for"], item["name"])
    )

    return [
        TeamStanding(
            position=idx + 1,
            team_id=item["team_id"],
            name=item["name"],
            short_name=item["short_name"],
            played=item["played"],
            won=item["won"],
            drawn=item["drawn"],
            lost=item["lost"],
            goals_for=item["goals_for"],
            goals_against=item["goals_against"],
            goal_difference=item["goal_difference"],
            points=item["points"],
            form=item["form"],
        )
        for idx, item in enumerate(standings_raw)
    ]


def compute_historical_standings(
    season: str,
    up_to_gw: int,
    data_dir: Path | None = None,
) -> list[TeamStanding]:
    """Compute Premier League standings strictly using finished matches before up_to_gw."""
    season_dir = _get_season_dir(season, data_dir)
    teams_map = _load_teams_map(season_dir)
    fixtures_data = _load_fixtures_data(season_dir)
    return compute_standings_from_data(fixtures_data, teams_map, up_to_gw=up_to_gw)


def get_past_results_from_data(
    fixtures_data: list[dict[str, Any]],
    teams_map: dict[int, dict[str, Any]],
    up_to_gw: int,
    gameweek: int | None = None,
) -> list[HistoricalFixtureResult]:
    """Get completed match results strictly prior to up_to_gw."""
    results: list[HistoricalFixtureResult] = []
    for f in fixtures_data:
        event = f.get("event")
        if event is None or event >= up_to_gw:
            continue
        if gameweek is not None and event != gameweek:
            continue
        if not f.get("finished"):
            continue
        h_score = f.get("team_h_score")
        a_score = f.get("team_a_score")
        if h_score is None or a_score is None:
            continue

        th = f.get("team_h")
        ta = f.get("team_a")
        t_h_info = teams_map.get(th, {})
        t_a_info = teams_map.get(ta, {})

        results.append(
            HistoricalFixtureResult(
                fixture_id=f.get("fixture_id", f.get("id", 0)),
                event=event,
                kickoff_time=f.get("kickoff_time"),
                team_h=th,
                team_h_name=t_h_info.get("name", f"Team {th}"),
                team_h_short=t_h_info.get("short_name", f"T{th}"),
                team_a=ta,
                team_a_name=t_a_info.get("name", f"Team {ta}"),
                team_a_short=t_a_info.get("short_name", f"T{ta}"),
                team_h_score=int(h_score),
                team_a_score=int(a_score),
                team_h_difficulty=f.get("team_h_difficulty", 3),
                team_a_difficulty=f.get("team_a_difficulty", 3),
                finished=True,
            )
        )

    # Sort descending by gameweek, then kickoff
    results.sort(key=lambda r: (-r.event, r.kickoff_time or ""))
    return results


def get_historical_past_results(
    season: str,
    up_to_gw: int,
    gameweek: int | None = None,
    data_dir: Path | None = None,
) -> list[HistoricalFixtureResult]:
    """Get completed match results strictly prior to up_to_gw."""
    season_dir = _get_season_dir(season, data_dir)
    teams_map = _load_teams_map(season_dir)
    fixtures_data = _load_fixtures_data(season_dir)
    return get_past_results_from_data(fixtures_data, teams_map, up_to_gw=up_to_gw, gameweek=gameweek)


def get_upcoming_fixtures_from_data(
    fixtures_data: list[dict[str, Any]],
    teams_map: dict[int, dict[str, Any]],
    target_gw: int,
    horizon: int = 1,
) -> list[HistoricalUpcomingFixture]:
    """Get upcoming fixtures starting at target_gw with STRICT zero-leakage of future scores."""
    upcoming: list[HistoricalUpcomingFixture] = []
    end_gw = target_gw + horizon

    for f in fixtures_data:
        event = f.get("event")
        if event is None:
            continue
        if target_gw <= event < end_gw:
            th = f.get("team_h")
            ta = f.get("team_a")
            t_h_info = teams_map.get(th, {})
            t_a_info = teams_map.get(ta, {})

            # Guarantee that NO outcome data (scores, finished status) is forwarded
            upcoming.append(
                HistoricalUpcomingFixture(
                    fixture_id=f.get("fixture_id", f.get("id", 0)),
                    event=event,
                    kickoff_time=f.get("kickoff_time"),
                    team_h=th,
                    team_h_name=t_h_info.get("name", f"Team {th}"),
                    team_h_short=t_h_info.get("short_name", f"T{th}"),
                    team_a=ta,
                    team_a_name=t_a_info.get("name", f"Team {ta}"),
                    team_a_short=t_a_info.get("short_name", f"T{ta}"),
                    team_h_difficulty=f.get("team_h_difficulty", 3),
                    team_a_difficulty=f.get("team_a_difficulty", 3),
                )
            )

    upcoming.sort(key=lambda u: (u.event, u.kickoff_time or ""))
    return upcoming


def get_historical_upcoming_fixtures(
    season: str,
    target_gw: int,
    horizon: int = 1,
    data_dir: Path | None = None,
) -> list[HistoricalUpcomingFixture]:
    """Get upcoming fixtures starting at target_gw with STRICT zero-leakage of future scores."""
    season_dir = _get_season_dir(season, data_dir)
    teams_map = _load_teams_map(season_dir)
    fixtures_data = _load_fixtures_data(season_dir)
    return get_upcoming_fixtures_from_data(fixtures_data, teams_map, target_gw=target_gw, horizon=horizon)


def get_historical_matchday_overview(
    season: str,
    gameweek: int,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """Full point-in-time matchday overview for historical gameweek."""
    standings = compute_historical_standings(season, up_to_gw=gameweek, data_dir=data_dir)
    past_results = get_historical_past_results(season, up_to_gw=gameweek, data_dir=data_dir)
    upcoming_fixtures = get_historical_upcoming_fixtures(season, target_gw=gameweek, horizon=1, data_dir=data_dir)

    return {
        "season": season,
        "gameweek": gameweek,
        "standings": [s.to_dict() for s in standings],
        "past_results": [r.to_dict() for r in past_results],
        "upcoming_fixtures": [u.to_dict() for u in upcoming_fixtures],
    }


def get_live_matchday_overview(
    database_path: Path | None = None,
    target_gw: int | None = None,
) -> dict[str, Any]:
    """Point-in-time Premier League matchday overview for the live season."""
    import glob
    import sqlite3

    db_path = database_path or (PROJECT_ROOT / "data" / "fpl.sqlite3")
    teams_map: dict[int, dict[str, Any]] = {}

    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                snap = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
                if snap:
                    snap_id = snap[0]
                    rows = conn.execute(
                        "SELECT team_id, name, short_name FROM teams WHERE snapshot_id = ?",
                        (snap_id,),
                    ).fetchall()
                    teams_map = {
                        r[0]: {"team_id": r[0], "name": r[1], "short_name": r[2]}
                        for r in rows
                    }
        except Exception:
            teams_map = {}

    # Load raw fixtures (contains team_h_score and team_a_score for finished games)
    raw_dir = PROJECT_ROOT / "data" / "raw"
    fixtures_data: list[dict[str, Any]] = []
    if raw_dir.exists():
        raw_fix_files = sorted(raw_dir.glob("*fixtures.json"))
        if raw_fix_files:
            try:
                fixtures_data = json.loads(raw_fix_files[-1].read_text(encoding="utf-8"))
            except Exception:
                fixtures_data = []

        if not teams_map:
            raw_boot_files = sorted(raw_dir.glob("*bootstrap-static.json"))
            if raw_boot_files:
                try:
                    boot = json.loads(raw_boot_files[-1].read_text(encoding="utf-8"))
                    for t in boot.get("teams", []):
                        teams_map[t["id"]] = {
                            "team_id": t["id"],
                            "name": t["name"],
                            "short_name": t["short_name"],
                        }
                except Exception:
                    pass

    # Determine current gameweek
    current_gw = target_gw
    if current_gw is None:
        finished_events = [f.get("event") for f in fixtures_data if f.get("finished") and f.get("event")]
        if finished_events:
            current_gw = max(finished_events) + 1
        else:
            current_gw = 1
    current_gw = min(38, max(1, current_gw))

    standings = compute_standings_from_data(fixtures_data, teams_map, up_to_gw=current_gw)
    past_results = get_past_results_from_data(fixtures_data, teams_map, up_to_gw=current_gw)
    upcoming_fixtures = get_upcoming_fixtures_from_data(fixtures_data, teams_map, target_gw=current_gw, horizon=2)

    return {
        "season": "2026-27",
        "gameweek": current_gw,
        "standings": [s.to_dict() for s in standings],
        "past_results": [r.to_dict() for r in past_results],
        "upcoming_fixtures": [u.to_dict() for u in upcoming_fixtures],
    }

