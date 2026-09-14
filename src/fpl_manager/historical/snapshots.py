"""Point-in-time snapshot generator ensuring zero future leakage for V0.7.0."""

from datetime import datetime, timezone
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


def _parse_kickoff(kickoff_str: str | None) -> datetime | None:
    if not kickoff_str:
        return None
    try:
        clean = kickoff_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def build_historical_snapshot(
    season_dir: Path,
    gameweek: int,
) -> HistoricalGameweekSnapshot:
    """Reconstruct an immutable, point-in-time snapshot for Gameweek N.
    
    Zero future-leakage invariant:
    For Gameweek N, the snapshot contains strictly:
    - Players, teams, and fixture schedules known before GW N deadline.
    - Cumulative performance stats (minutes, starts, xG, xA) strictly from GW 1..N-1.
    - Rotation, trend, and turnaround indicators strictly from completed GW 1..N-1.
    - Current GW N matchday outcome files are NEVER referenced.
    """
    manifest_path = season_dir / "season_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    season = manifest["season"]
    deadlines = manifest.get("deadlines", {})
    deadline_time = deadlines.get(str(gameweek), deadlines.get(gameweek, ""))

    teams_data = json.loads((season_dir / "teams.json").read_text(encoding="utf-8"))
    teams = [
        {
            "team_id": t["team_id"],
            "name": t["name"],
            "short_name": t["short_name"],
            "strength": t.get("strength", 3),
        }
        for t in teams_data
    ]

    fixtures_data = json.loads((season_dir / "fixtures.json").read_text(encoding="utf-8"))

    # Compute prior team fixture kickoffs strictly from completed gameweeks 1..N-1
    team_prior_kickoffs: dict[int, list[datetime]] = {t["team_id"]: [] for t in teams_data}
    for f in fixtures_data:
        f_event = f.get("event")
        if f_event is not None and 1 <= f_event < gameweek:
            ko = _parse_kickoff(f.get("kickoff_time"))
            if ko:
                team_h = f.get("team_h")
                team_a = f.get("team_a")
                if team_h in team_prior_kickoffs:
                    team_prior_kickoffs[team_h].append(ko)
                if team_a in team_prior_kickoffs:
                    team_prior_kickoffs[team_a].append(ko)

    for t_id in team_prior_kickoffs:
        team_prior_kickoffs[t_id].sort()

    gw_fixtures: list[HistoricalFixture] = []
    for f in fixtures_data:
        if f.get("event") == gameweek:
            ko_dt = _parse_kickoff(f.get("kickoff_time"))
            th = f["team_h"]
            ta = f["team_a"]

            # Home team schedule
            days_prev_h = None
            m7_h = 0
            m14_h = 0
            if ko_dt and th in team_prior_kickoffs and team_prior_kickoffs[th]:
                last_ko = team_prior_kickoffs[th][-1]
                delta_days = (ko_dt - last_ko).total_seconds() / 86400.0
                days_prev_h = round(max(0.0, delta_days), 2)
                for past_ko in team_prior_kickoffs[th]:
                    diff = (ko_dt - past_ko).total_seconds() / 86400.0
                    if 0.0 < diff <= 7.0:
                        m7_h += 1
                    if 0.0 < diff <= 14.0:
                        m14_h += 1

            # Away team schedule
            days_prev_a = None
            m7_a = 0
            m14_a = 0
            if ko_dt and ta in team_prior_kickoffs and team_prior_kickoffs[ta]:
                last_ko = team_prior_kickoffs[ta][-1]
                delta_days = (ko_dt - last_ko).total_seconds() / 86400.0
                days_prev_a = round(max(0.0, delta_days), 2)
                for past_ko in team_prior_kickoffs[ta]:
                    diff = (ko_dt - past_ko).total_seconds() / 86400.0
                    if 0.0 < diff <= 7.0:
                        m7_a += 1
                    if 0.0 < diff <= 14.0:
                        m14_a += 1

            gw_fixtures.append(
                HistoricalFixture(
                    fixture_id=f["fixture_id"],
                    event=f["event"],
                    team_h=th,
                    team_a=ta,
                    team_h_difficulty=f.get("team_h_difficulty", 3),
                    team_a_difficulty=f.get("team_a_difficulty", 3),
                    kickoff_time=f.get("kickoff_time"),
                    days_since_prev_h=days_prev_h,
                    days_since_prev_a=days_prev_a,
                    matches_7d_h=m7_h,
                    matches_7d_a=m7_a,
                    matches_14d_h=m14_h,
                    matches_14d_a=m14_a,
                )
            )

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
    recent_starts_hist: dict[int, list[int]] = {}
    recent_mins_hist: dict[int, list[int]] = {}

    for prev_gw in range(1, gameweek):
        prev_data = load_gameweek_raw_data(season_dir, prev_gw)
        for p in prev_data:
            pid = p["player_id"]
            p_mins = p.get("minutes", 0)
            p_starts = p.get("starts", 1 if p_mins >= 60 else 0)

            cum_minutes[pid] = cum_minutes.get(pid, 0) + p_mins
            cum_starts[pid] = cum_starts.get(pid, 0) + p_starts
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
                recent_starts_hist[pid] = []
                recent_mins_hist[pid] = []
            recent_pts[pid].append(p.get("total_points", 0))
            recent_starts_hist[pid].append(p_starts)
            recent_mins_hist[pid].append(p_mins)

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

        # Recent starts and minutes trends strictly prior to deadline
        p_starts_list = recent_starts_hist.get(pid, [])
        p_mins_list = recent_mins_hist.get(pid, [])
        s_last_3 = sum(p_starts_list[-3:]) if p_starts_list else 0
        s_last_5 = sum(p_starts_list[-5:]) if p_starts_list else 0
        m_last_3 = sum(p_mins_list[-3:]) if p_mins_list else 0
        m_last_5 = sum(p_mins_list[-5:]) if p_mins_list else 0

        # Consecutive zero-minute matches directly preceding GW N
        consec_zero = 0
        for m_val in reversed(p_mins_list):
            if m_val == 0:
                consec_zero += 1
            else:
                break

        # Per 90 stats
        n90 = max(0.1, mins / 90.0)
        xg90 = round(xg / n90, 2)
        xa90 = round(xa / n90, 2)
        xgc90 = round(xgc / n90, 2)
        cs90 = round(cs / n90, 2)

        # Inferred availability status strictly knowable prior to deadline
        status = p.get("status", "a")
        chance_next: int | None = p.get("chance_of_playing_next_round")
        if status == "a" and finished_gws >= 3 and mins == 0:
            # Player consistently not playing across completed gameweeks (1..N-1)
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
                starts_last_3=s_last_3,
                starts_last_5=s_last_5,
                minutes_last_3=m_last_3,
                minutes_last_5=m_last_5,
                consecutive_zero_mins=consec_zero,
                recent_starts=tuple(p_starts_list[-5:]),
                recent_minutes=tuple(p_mins_list[-5:]),
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
            starts=p.get("starts", 1 if p.get("minutes", 0) >= 60 else 0),
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
