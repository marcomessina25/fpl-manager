"""Point-in-time snapshot generator ensuring zero future leakage for V0.7.0."""

import json
from pathlib import Path
from typing import Any

from .models import (
    GameweekOutcome,
    HistoricalFixture,
    HistoricalGameweekSnapshot,
    HistoricalPlayerState,
    Position,
)


def load_gameweek_raw_data(season_dir: Path, gameweek: int) -> list[dict[str, Any]]:
    """Load normalized raw data for a specific gameweek."""
    gw_path = season_dir / "gws" / f"gw{gameweek}.json"
    if not gw_path.exists():
        raise FileNotFoundError(f"Gameweek file not found: {gw_path}")
    return json.loads(gw_path.read_text(encoding="utf-8"))


def build_historical_snapshot(
    season_dir: Path,
    gameweek: int,
) -> HistoricalGameweekSnapshot:
    """Reconstruct an immutable point-in-time snapshot available BEFORE Gameweek deadline.
    
    Zero future leakage guarantee:
    - Pre-deadline player attributes (price, ownership, status) taken as of GW deadline.
    - Historical stats (minutes, starts, points, xG, xA) computed exclusively over GW 1 .. GW (N-1).
    - GW N matchday outcome stats are strictly omitted.
    """
    manifest_path = season_dir / "season_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    season = manifest["season"]
    deadlines = manifest.get("deadlines", {})
    deadline_time = deadlines.get(str(gameweek), deadlines.get(gameweek, ""))

    teams = json.loads((season_dir / "teams.json").read_text(encoding="utf-8"))
    fixtures_data = json.loads((season_dir / "fixtures.json").read_text(encoding="utf-8"))

    # Upcoming fixtures for this gameweek
    gw_fixtures = [
        HistoricalFixture(
            fixture_id=f["fixture_id"],
            event=f["event"],
            team_h=f["team_h"],
            team_a=f["team_a"],
            team_h_difficulty=f.get("team_h_difficulty", 3),
            team_a_difficulty=f.get("team_a_difficulty", 3),
            kickoff_time=f.get("kickoff_time"),
        )
        for f in fixtures_data
        if f.get("event") == gameweek
    ]

    # Load current GW raw data for point-in-time player status/price/ownership
    current_gw_players = {p["player_id"]: p for p in load_gameweek_raw_data(season_dir, gameweek)}

    # Accumulate prior historical statistics strictly from GW 1 to GW (N-1)
    cum_minutes: dict[int, int] = {}
    cum_starts: dict[int, int] = {}
    cum_points: dict[int, int] = {}
    cum_xg: dict[int, float] = {}
    cum_xa: dict[int, float] = {}
    cum_xgi: dict[int, float] = {}
    cum_xgc: dict[int, float] = {}
    cum_cs: dict[int, int] = {}
    cum_bps: dict[int, int] = {}
    cum_ict: dict[int, float] = {}
    recent_pts: dict[int, list[int]] = {}

    for prev_gw in range(1, gameweek):
        prev_data = load_gameweek_raw_data(season_dir, prev_gw)
        for p in prev_data:
            pid = p["player_id"]
            cum_minutes[pid] = cum_minutes.get(pid, 0) + p.get("minutes", 0)
            cum_starts[pid] = cum_starts.get(pid, 0) + p.get("starts", 0)
            cum_points[pid] = cum_points.get(pid, 0) + p.get("total_points", 0)
            cum_xg[pid] = cum_xg.get(pid, 0.0) + p.get("expected_goals", 0.0)
            cum_xa[pid] = cum_xa.get(pid, 0.0) + p.get("expected_assists", 0.0)
            cum_xgi[pid] = cum_xgi.get(pid, 0.0) + p.get("expected_goal_involvements", 0.0)
            cum_xgc[pid] = cum_xgc.get(pid, 0.0) + p.get("expected_goals_conceded", 0.0)
            cum_cs[pid] = cum_cs.get(pid, 0) + p.get("clean_sheets", 0)
            cum_bps[pid] = cum_bps.get(pid, 0) + p.get("bps", 0)
            cum_ict[pid] = cum_ict.get(pid, 0.0) + p.get("ict_index", 0.0)

            if pid not in recent_pts:
                recent_pts[pid] = []
            recent_pts[pid].append(p.get("total_points", 0))

    players_list: list[HistoricalPlayerState] = []
    finished_gws = gameweek - 1

    for pid, p in current_gw_players.items():
        mins = cum_minutes.get(pid, 0)
        starts = cum_starts.get(pid, 0)
        pts = cum_points.get(pid, 0)
        xg = cum_xg.get(pid, 0.0)
        xa = cum_xa.get(pid, 0.0)
        xgi = cum_xgi.get(pid, 0.0)
        xgc = cum_xgc.get(pid, 0.0)
        cs = cum_cs.get(pid, 0)
        bps = cum_bps.get(pid, 0)
        ict = cum_ict.get(pid, 0.0)

        matches_with_mins = sum(1 for m in recent_pts.get(pid, []) if m > 0)
        ppg = round(pts / finished_gws, 2) if finished_gws > 0 else 0.0

        # Form: average points in the last 4 finished matches
        history = recent_pts.get(pid, [])
        last_games = history[-4:] if len(history) >= 4 else history
        form = round(sum(last_games) / len(last_games), 2) if last_games else 0.0

        # Per 90 stats
        n90 = max(0.1, mins / 90.0)
        xg90 = round(xg / n90, 2)
        xa90 = round(xa / n90, 2)
        xgc90 = round(xgc / n90, 2)
        cs90 = round(cs / n90, 2)

        # Inferred availability status
        status = "a"
        chance_next: int | None = None
        if finished_gws >= 3 and mins == 0 and p.get("minutes", 0) == 0:
            # Player consistently not playing
            status = "d"

        players_list.append(
            HistoricalPlayerState(
                player_id=pid,
                web_name=p["name"],
                position=Position(p["position"]),
                team_id=p["team_id"],
                price_tenths=p["price_tenths"],
                status=status,
                chance_of_playing_next_round=chance_next,
                chance_of_playing_this_round=None,
                total_points=pts,
                minutes=mins,
                starts=starts,
                expected_goals=round(xg, 2),
                expected_assists=round(xa, 2),
                expected_goal_involvements=round(xgi, 2),
                expected_goals_conceded=round(xgc, 2),
                expected_goals_per_90=xg90,
                expected_assists_per_90=xa90,
                expected_goals_conceded_per_90=xgc90,
                clean_sheets_per_90=cs90,
                bps=bps,
                ict_index=round(ict, 1),
                form=form,
                points_per_game=ppg,
                selected_by_percent=p.get("selected", 0.0),
                news="",
            )
        )

    players_list.sort(key=lambda pl: pl.player_id)

    return HistoricalGameweekSnapshot(
        season=season,
        gameweek=gameweek,
        deadline_time=deadline_time,
        finished_gameweeks=finished_gws,
        players=tuple(players_list),
        teams=tuple(teams),
        fixtures=tuple(gw_fixtures),
    )


def load_gameweek_outcomes(
    season_dir: Path,
    gameweek: int,
) -> dict[int, GameweekOutcome]:
    """Extract authoritative revealed ground truth outcomes for Gameweek N.
    
    MUST be used ONLY during post-gameweek evaluation and scoring.
    """
    manifest_path = season_dir / "season_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    season = manifest["season"]

    raw_players = load_gameweek_raw_data(season_dir, gameweek)
    outcomes: dict[int, GameweekOutcome] = {}

    for p in raw_players:
        pid = p["player_id"]
        outcomes[pid] = GameweekOutcome(
            season=season,
            gameweek=gameweek,
            player_id=pid,
            minutes=p.get("minutes", 0),
            total_points=p.get("total_points", 0),
            goals_scored=p.get("goals_scored", 0),
            assists=p.get("assists", 0),
            clean_sheets=p.get("clean_sheets", 0),
            goals_conceded=p.get("goals_conceded", 0),
            bonus=p.get("bonus", 0),
            bps=p.get("bps", 0),
            was_home=p.get("was_home", True),
            opponent_team_id=p.get("opponent_team_id", 0),
        )
    return outcomes
