"""Transparent, deterministic expected-points (xP) and minutes (xM) model for FPL Manager V0.3.

V0.3 Model Pillars:
1. Expected Minutes (xM) & Squad Role:
   - Evaluates availability probability from official FPL status and chance_of_playing_next_round.
   - Evaluates starting probability (P(start)) and sub appearance probability based on observed
     starts/minutes with Bayesian shrinkage toward price/position priors.
2. Component-Based Projections (xP):
   - Appearance points: 2 pts for >=60 mins, 1 pt for 1-59 mins.
   - Attacking threat: official xG and xA per 90 (Opta) blended with position priors, scaled by
     expected minutes and position-specific goal scoring points (DEF/GKP: 6, MID: 5, FWD: 4) and assists (3).
   - Defensive resilience: Clean sheet probability from opponent attack difficulty and team venue,
     plus expected goals conceded penalties (-1 per 2 goals conceded for DEF/GKP).
   - Bonus point expectation: scaled from expected attacking involvements and clean sheets.
   - Disciplinary deduction: expected cards deduction (-0.15 pts per 90).
3. Uncertainty & Variance:
   - Floor (10th percentile safe floor) and Ceiling (90th percentile haul potential).
   - Standard deviation (sigma) distinguishing steady floor assets from high-upside differentials.

See `docs/expected_points.md` for full mathematical documentation.
"""

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

from .models import Position
from .storage import SnapshotStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"


@dataclass(frozen=True, slots=True)
class PlayerFixtureProjection:
    event: int
    opponent_id: int
    opponent_short: str
    is_home: bool
    venue: str
    fdr: int
    fixture_xp: float
    expected_minutes: float = 0.0
    start_probability: float = 0.0
    xp_appearance: float = 0.0
    xp_attack: float = 0.0
    xp_defense: float = 0.0
    xp_bonus: float = 0.0
    xp_floor: float = 0.0
    xp_ceiling: float = 0.0
    variance: float = 0.0


@dataclass(frozen=True, slots=True)
class ExpectedPointsProjection:
    player_id: int
    web_name: str
    position: Position
    team_id: int
    team_short: str
    price_tenths: int
    status: str
    availability_pct: float
    base_xp_per_match: float
    gameweek: int
    fixtures: tuple[PlayerFixtureProjection, ...]
    expected_points: float
    expected_minutes: float = 0.0
    start_probability: float = 0.0
    xp_floor: float = 0.0
    xp_ceiling: float = 0.0
    standard_deviation: float = 0.0


@dataclass(frozen=True, slots=True)
class MultiGameweekProfile:
    player_id: int
    web_name: str
    position: Position
    team_id: int
    team_short: str
    price_tenths: int
    status: str
    expected_points: float
    expected_minutes: float
    xp_floor: float
    xp_ceiling: float
    standard_deviation: float
    fixtures_count: int


def calculate_base_xp(price_tenths: int, total_points: int = 0, finished_matches: int = 0) -> float:
    """Calculate base expected points per match from price tier and observed form.

    Price tier prior:
      £4.0m baseline is ~1.5 pts/game.
      Each £1.0m above £4.0m adds ~0.65 pts/game.

    When matches have been played, blend observed PPG with price prior using
    sample-size weighting (Bayesian shrinkage).
    """
    price_millions = price_tenths / 10.0
    price_prior = 1.5 + max(0.0, price_millions - 4.0) * 0.65

    if finished_matches > 0 and total_points > 0:
        observed_ppg = total_points / finished_matches
        weight = min(0.80, finished_matches / 10.0)
        base = weight * observed_ppg + (1.0 - weight) * price_prior
    else:
        base = price_prior

    return round(base, 2)


def availability_multiplier(status: str) -> float:
    """Return availability probability from official FPL player status code."""
    status_lower = status.lower()
    if status_lower == "a":
        return 1.0
    elif status_lower == "d":
        return 0.75
    elif status_lower in ("i", "s", "u"):
        return 0.0
    return 0.0


def calculate_availability(status: str, chance_of_playing_next_round: int | None = None) -> float:
    """Return availability probability combining status code and official percentage chance."""
    if chance_of_playing_next_round is not None:
        try:
            return round(max(0.0, min(100.0, float(chance_of_playing_next_round))) / 100.0, 2)
        except (ValueError, TypeError):
            pass
    return availability_multiplier(status)


def fdr_multiplier(position: Position, fdr: int) -> float:
    """Return difficulty multiplier based on FDR rating (1 to 5) and position.

    Goalkeepers and Defenders are more fixture-sensitive (clean sheet reliance).
    Midfielders and Forwards have more consistent attacking threat across difficulties.
    """
    fdr_clamped = max(1, min(5, fdr))
    if position in (Position.GOALKEEPER, Position.DEFENDER):
        return round(1.0 + (3 - fdr_clamped) * 0.15, 3)
    else:
        return round(1.0 + (3 - fdr_clamped) * 0.10, 3)


def venue_multiplier(is_home: bool) -> float:
    """Return home/away venue adjustment multiplier (+6% home, -6% away)."""
    return 1.06 if is_home else 0.94


def calculate_fixture_xp(
    base_xp: float,
    avail_mult: float,
    position: Position,
    fdr: int,
    is_home: bool,
) -> float:
    """Calculate baseline expected points for a single match fixture."""
    if avail_mult <= 0.0:
        return 0.0
    fdr_mult = fdr_multiplier(position, fdr)
    ven_mult = venue_multiplier(is_home)
    return round(base_xp * avail_mult * fdr_mult * ven_mult, 2)


def calculate_expected_minutes(
    status: str,
    chance_of_playing_next_round: int | None = None,
    starts: int = 0,
    minutes: int = 0,
    finished_matches: int = 0,
    price_tenths: int = 50,
    position: Position = Position.MIDFIELDER,
) -> tuple[float, float, float, float]:
    """Calculate expected minutes, start probability, 60+ min probability, and sub appearance probability.

    Returns:
        (expected_minutes, start_probability, prob_60_plus, prob_sub)
    """
    avail = calculate_availability(status, chance_of_playing_next_round)
    if avail <= 0.0:
        return 0.0, 0.0, 0.0, 0.0

    price_millions = price_tenths / 10.0
    if position == Position.GOALKEEPER:
        if price_millions >= 4.5:
            prior_p_start = 0.95
            prior_mins_start = 90.0
        else:
            prior_p_start = 0.05
            prior_mins_start = 10.0
    else:
        if price_millions >= 8.0:
            prior_p_start = 0.92
            prior_mins_start = 85.0
        elif price_millions >= 6.0:
            prior_p_start = 0.82
            prior_mins_start = 78.0
        elif price_millions >= 5.0:
            prior_p_start = 0.65
            prior_mins_start = 68.0
        elif price_millions >= 4.5:
            prior_p_start = 0.50
            prior_mins_start = 55.0
        else:
            prior_p_start = 0.15
            prior_mins_start = 25.0

    if finished_matches > 0:
        obs_p_start = min(1.0, max(0.0, starts / finished_matches))
        obs_mins_start = (minutes / starts) if starts > 0 else 0.0
        w = min(0.85, finished_matches / 6.0)
        p_start_fit = w * obs_p_start + (1.0 - w) * prior_p_start
        mins_start_fit = (w * obs_mins_start + (1.0 - w) * prior_mins_start) if starts > 0 else prior_mins_start
        mins_start_fit = max(30.0, min(90.0, mins_start_fit))

        sub_appearances = max(0, min(finished_matches, int(round((minutes - starts * mins_start_fit) / 20.0)))) if minutes > starts * mins_start_fit else 0
        obs_p_sub = min(0.60, sub_appearances / finished_matches) if finished_matches > 0 else 0.10
        p_sub_fit = max(0.0, min(0.50, (1.0 - p_start_fit) * (0.30 if obs_p_sub > 0 else 0.10)))
    else:
        p_start_fit = prior_p_start
        mins_start_fit = prior_mins_start
        p_sub_fit = 0.15 if p_start_fit < 0.80 else 0.05

    p_start = round(p_start_fit * avail, 3)
    p_sub = round(p_sub_fit * avail, 3)
    mins_sub = 20.0
    expected_mins = round(min(90.0, p_start * mins_start_fit + p_sub * mins_sub), 1)

    prob_60 = round(min(1.0, p_start * (0.95 if mins_start_fit >= 60.0 else 0.35)), 3)
    prob_sub = round(max(0.0, min(1.0, (p_start + p_sub) - prob_60)), 3)

    return expected_mins, p_start, prob_60, prob_sub


def calculate_component_xp(
    position: Position,
    price_tenths: int,
    fdr: int,
    is_home: bool,
    expected_minutes: float,
    prob_60_plus: float,
    prob_sub: float,
    expected_goals_per_90: float = 0.0,
    expected_assists_per_90: float = 0.0,
    expected_goals_conceded_per_90: float = 0.0,
    clean_sheets_per_90: float = 0.0,
    finished_matches: int = 0,
) -> dict[str, float]:
    """Calculate component-based expected points, floor, ceiling, and variance."""
    if expected_minutes <= 0.0:
        return {
            "total": 0.0,
            "floor": 0.0,
            "ceil": 0.0,
            "sigma": 0.0,
            "app": 0.0,
            "att": 0.0,
            "def": 0.0,
            "bon": 0.0,
            "deduct": 0.0,
        }

    mins_ratio = expected_minutes / 90.0
    fdr_clamped = max(1, min(5, fdr))
    fdr_att = 1.0 + (3 - fdr_clamped) * 0.10
    fdr_def = 1.0 + (3 - fdr_clamped) * 0.15
    ven_mult = 1.06 if is_home else 0.94

    # 1. Appearance
    xp_app = 2.0 * prob_60_plus + 1.0 * prob_sub

    # 2. Attacking
    price_m = price_tenths / 10.0
    if position == Position.FORWARD:
        prior_xg90 = 0.15 + max(0.0, price_m - 5.0) * 0.05
        prior_xa90 = 0.05 + max(0.0, price_m - 5.0) * 0.01
        goal_pts = 4.0
    elif position == Position.MIDFIELDER:
        prior_xg90 = 0.05 + max(0.0, price_m - 5.0) * 0.04
        prior_xa90 = 0.08 + max(0.0, price_m - 5.0) * 0.03
        goal_pts = 5.0
    elif position == Position.DEFENDER:
        prior_xg90 = 0.02 + max(0.0, price_m - 4.5) * 0.015
        prior_xa90 = 0.04 + max(0.0, price_m - 4.5) * 0.025
        goal_pts = 6.0
    else:
        prior_xg90 = 0.0
        prior_xa90 = 0.005
        goal_pts = 6.0

    w = min(0.85, finished_matches / 5.0) if finished_matches > 0 and (expected_goals_per_90 > 0 or expected_assists_per_90 > 0) else 0.0
    eff_xg90 = w * expected_goals_per_90 + (1.0 - w) * prior_xg90
    eff_xa90 = w * expected_assists_per_90 + (1.0 - w) * prior_xa90

    fix_xg = eff_xg90 * mins_ratio * fdr_att * ven_mult
    fix_xa = eff_xa90 * mins_ratio * fdr_att * ven_mult
    xp_att = fix_xg * goal_pts + fix_xa * 3.0

    # 3. Defensive
    base_cs_prob = 0.32
    cs_prob = max(0.05, min(0.65, base_cs_prob * fdr_def * (1.15 if is_home else 0.85)))
    if position in (Position.GOALKEEPER, Position.DEFENDER):
        xp_cs = 4.0 * cs_prob * prob_60_plus
        xgc = max(0.5, 1.35 * (1.0 + (fdr_clamped - 3) * 0.15) * (0.85 if is_home else 1.15)) * mins_ratio
        xp_gc = -0.5 * max(0.0, xgc - 0.5) * prob_60_plus
        xp_def = xp_cs + xp_gc
    elif position == Position.MIDFIELDER:
        xp_def = 1.0 * cs_prob * prob_60_plus
    else:
        xp_def = 0.0

    # 4. Bonus
    xp_bonus = min(1.8, 0.35 * xp_att + (0.25 if cs_prob > 0.35 and position <= Position.DEFENDER else 0.0))

    # 5. Deduction
    xp_deduct = 0.15 * mins_ratio

    total = max(0.0, xp_app + xp_att + xp_def + xp_bonus - xp_deduct)

    # Uncertainty
    floor = round(max(0.0, xp_app - xp_deduct) if prob_60_plus >= 0.5 else 0.0, 2)
    sig_att = 1.3 * xp_att + 0.8
    sig_def = math.sqrt(cs_prob * (1 - cs_prob) * 16.0) * prob_60_plus if position in (Position.GOALKEEPER, Position.DEFENDER) else 0.0
    sigma = round(math.sqrt(sig_att**2 + sig_def**2) * mins_ratio, 2)
    ceil = round(total + 1.645 * sigma, 2)

    return {
        "total": round(total, 2),
        "floor": floor,
        "ceil": ceil,
        "sigma": sigma,
        "app": round(xp_app, 2),
        "att": round(xp_att, 2),
        "def": round(xp_def, 2),
        "bon": round(xp_bonus, 2),
        "deduct": round(xp_deduct, 2),
    }


def project_player_gameweek(
    player_id: int,
    web_name: str,
    position: Position,
    team_id: int,
    team_short: str,
    price_tenths: int,
    status: str,
    total_points: int,
    finished_matches: int,
    gameweek: int,
    team_fixtures_in_gw: list[dict[str, Any]],
    minutes: int = 0,
    starts: int = 0,
    chance_of_playing_next_round: int | None = None,
    chance_of_playing_this_round: int | None = None,
    expected_goals: float = 0.0,
    expected_assists: float = 0.0,
    expected_goal_involvements: float = 0.0,
    expected_goals_conceded: float = 0.0,
    expected_goals_per_90: float = 0.0,
    expected_assists_per_90: float = 0.0,
    expected_goals_conceded_per_90: float = 0.0,
    clean_sheets_per_90: float = 0.0,
    bps: int = 0,
    ict_index: float = 0.0,
    form: float = 0.0,
    points_per_game: float = 0.0,
    selected_by_percent: float = 0.0,
    news: str = "",
) -> ExpectedPointsProjection:
    """Compute expected points projection for a single player in a specific gameweek."""
    base_xp = calculate_base_xp(price_tenths, total_points, finished_matches)
    avail = calculate_availability(status, chance_of_playing_next_round)

    exp_mins, p_start, prob_60, prob_sub = calculate_expected_minutes(
        status=status,
        chance_of_playing_next_round=chance_of_playing_next_round,
        starts=starts,
        minutes=minutes,
        finished_matches=finished_matches,
        price_tenths=price_tenths,
        position=position,
    )

    fixture_projections: list[PlayerFixtureProjection] = []
    total_xp = 0.0
    total_floor = 0.0
    total_ceiling = 0.0
    sum_variance = 0.0

    for fix in team_fixtures_in_gw:
        opp_id = fix["opponent_id"]
        opp_short = fix["opponent_short"]
        is_home = fix["is_home"]
        fdr = fix["fdr"]
        venue = "H" if is_home else "A"

        baseline_xp = calculate_fixture_xp(base_xp, avail, position, fdr, is_home)
        comp = calculate_component_xp(
            position=position,
            price_tenths=price_tenths,
            fdr=fdr,
            is_home=is_home,
            expected_minutes=exp_mins,
            prob_60_plus=prob_60,
            prob_sub=prob_sub,
            expected_goals_per_90=expected_goals_per_90,
            expected_assists_per_90=expected_assists_per_90,
            expected_goals_conceded_per_90=expected_goals_conceded_per_90,
            clean_sheets_per_90=clean_sheets_per_90,
            finished_matches=finished_matches,
        )

        if avail <= 0.0:
            final_xp = 0.0
            fix_floor = 0.0
            fix_ceil = 0.0
            fix_var = 0.0
        else:
            final_xp = round(0.70 * comp["total"] + 0.30 * baseline_xp, 2)
            fix_floor = comp["floor"]
            fix_ceil = comp["ceil"]
            fix_var = comp["sigma"] ** 2

        total_xp += final_xp
        total_floor += fix_floor
        total_ceiling += fix_ceil
        sum_variance += fix_var

        fixture_projections.append(
            PlayerFixtureProjection(
                event=gameweek,
                opponent_id=opp_id,
                opponent_short=opp_short,
                is_home=is_home,
                venue=venue,
                fdr=fdr,
                fixture_xp=final_xp,
                expected_minutes=exp_mins,
                start_probability=p_start,
                xp_appearance=comp["app"],
                xp_attack=comp["att"],
                xp_defense=comp["def"],
                xp_bonus=comp["bon"],
                xp_floor=fix_floor,
                xp_ceiling=fix_ceil,
                variance=round(fix_var, 3),
            )
        )

    std_dev = round(math.sqrt(sum_variance), 2)

    return ExpectedPointsProjection(
        player_id=player_id,
        web_name=web_name,
        position=position,
        team_id=team_id,
        team_short=team_short,
        price_tenths=price_tenths,
        status=status,
        availability_pct=round(avail * 100, 1),
        base_xp_per_match=base_xp,
        gameweek=gameweek,
        fixtures=tuple(fixture_projections),
        expected_points=round(total_xp, 2),
        expected_minutes=exp_mins,
        start_probability=p_start,
        xp_floor=round(total_floor, 2),
        xp_ceiling=round(total_ceiling, 2),
        standard_deviation=std_dev,
    )


def project_gameweek(
    gameweek: int,
    player_ids: list[int] | None = None,
    database_path: Path = DATABASE_PATH,
) -> list[ExpectedPointsProjection]:
    """Generate expected points projections for players for a given gameweek."""
    store = SnapshotStore(database_path)
    store.initialize()

    with store._connect() as connection:
        snapshot = connection.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        if snapshot is None:
            raise RuntimeError("No FPL data found. Run `fpl update` first.")
        snapshot_id = snapshot[0]

        # Calculate finished matches count in this snapshot
        fin_row = connection.execute(
            "SELECT MAX(event) FROM fixtures WHERE snapshot_id = ? AND finished = 1 AND event IS NOT NULL",
            (snapshot_id,),
        ).fetchone()
        finished_matches = int(fin_row[0]) if fin_row and fin_row[0] is not None else 0

        # Load teams
        teams_rows = connection.execute(
            "SELECT team_id, short_name FROM teams WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchall()
        team_map = {row[0]: row[1] for row in teams_rows}

        # Load fixtures for the target gameweek
        fixtures_rows = connection.execute(
            """
            SELECT fixture_id, event, team_h, team_a, team_h_difficulty, team_a_difficulty
            FROM fixtures
            WHERE snapshot_id = ? AND event = ?
            """,
            (snapshot_id, gameweek),
        ).fetchall()

        # Load players with all underlying metrics
        cols = (
            "player_id, web_name, position_id, team_id, price_tenths, status, total_points, "
            "minutes, starts, chance_of_playing_next_round, chance_of_playing_this_round, "
            "expected_goals, expected_assists, expected_goal_involvements, expected_goals_conceded, "
            "expected_goals_per_90, expected_assists_per_90, expected_goals_conceded_per_90, clean_sheets_per_90, "
            "bps, ict_index, form, points_per_game, selected_by_percent, news"
        )
        if player_ids:
            placeholders = ",".join("?" for _ in player_ids)
            players_rows = connection.execute(
                f"SELECT {cols} FROM players WHERE snapshot_id = ? AND player_id IN ({placeholders})",
                (snapshot_id, *player_ids),
            ).fetchall()
        else:
            players_rows = connection.execute(
                f"SELECT {cols} FROM players WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchall()

    # Map fixtures by team_id
    team_fixtures: dict[int, list[dict[str, Any]]] = {t_id: [] for t_id in team_map}
    for _, _, team_h, team_a, h_diff, a_diff in fixtures_rows:
        h_fdr = int(h_diff) if h_diff is not None else 3
        a_fdr = int(a_diff) if a_diff is not None else 3

        if team_h in team_fixtures:
            team_fixtures[team_h].append({
                "opponent_id": team_a,
                "opponent_short": team_map.get(team_a, f"T{team_a}"),
                "is_home": True,
                "fdr": h_fdr,
            })
        if team_a in team_fixtures:
            team_fixtures[team_a].append({
                "opponent_id": team_h,
                "opponent_short": team_map.get(team_h, f"T{team_h}"),
                "is_home": False,
                "fdr": a_fdr,
            })

    projections: list[ExpectedPointsProjection] = []
    for row in players_rows:
        (
            p_id, web_name, pos_id, t_id, price, status, pts,
            mins, starts, chance_next, chance_this,
            xg, xa, xgi, xgc,
            xg90, xa90, xgc90, cs90,
            bps, ict, form, ppg, selected, news
        ) = row

        t_short = team_map.get(t_id, f"T{t_id}")
        t_fixs = team_fixtures.get(t_id, [])

        proj = project_player_gameweek(
            player_id=p_id,
            web_name=web_name,
            position=Position(pos_id),
            team_id=t_id,
            team_short=t_short,
            price_tenths=price,
            status=status,
            total_points=pts,
            finished_matches=finished_matches,
            gameweek=gameweek,
            team_fixtures_in_gw=t_fixs,
            minutes=mins or 0,
            starts=starts or 0,
            chance_of_playing_next_round=chance_next,
            chance_of_playing_this_round=chance_this,
            expected_goals=xg or 0.0,
            expected_assists=xa or 0.0,
            expected_goal_involvements=xgi or 0.0,
            expected_goals_conceded=xgc or 0.0,
            expected_goals_per_90=xg90 or 0.0,
            expected_assists_per_90=xa90 or 0.0,
            expected_goals_conceded_per_90=xgc90 or 0.0,
            clean_sheets_per_90=cs90 or 0.0,
            bps=bps or 0,
            ict_index=ict or 0.0,
            form=form or 0.0,
            points_per_game=ppg or 0.0,
            selected_by_percent=selected or 0.0,
            news=news or "",
        )
        projections.append(proj)

    return projections


def project_multi_gameweek_profiles(
    gameweeks: list[int],
    player_ids: list[int] | None = None,
    database_path: Path = DATABASE_PATH,
) -> dict[int, MultiGameweekProfile]:
    """Generate multi-gameweek projections with minutes, floor, ceiling, and uncertainty.

    Returns a mapping of player_id -> MultiGameweekProfile.
    """
    store = SnapshotStore(database_path)
    store.initialize()

    with store._connect() as connection:
        snapshot = connection.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        if snapshot is None:
            raise RuntimeError("No FPL data found. Run `fpl update` first.")
        snapshot_id = snapshot[0]

        fin_row = connection.execute(
            "SELECT MAX(event) FROM fixtures WHERE snapshot_id = ? AND finished = 1 AND event IS NOT NULL",
            (snapshot_id,),
        ).fetchone()
        finished_matches = int(fin_row[0]) if fin_row and fin_row[0] is not None else 0

        teams_rows = connection.execute(
            "SELECT team_id, short_name FROM teams WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchall()
        team_map = {row[0]: row[1] for row in teams_rows}

        placeholders_gw = ",".join("?" for _ in gameweeks)
        fixtures_rows = connection.execute(
            f"""
            SELECT fixture_id, event, team_h, team_a, team_h_difficulty, team_a_difficulty
            FROM fixtures
            WHERE snapshot_id = ? AND event IN ({placeholders_gw})
            """,
            (snapshot_id, *gameweeks),
        ).fetchall()

        cols = (
            "player_id, web_name, position_id, team_id, price_tenths, status, total_points, "
            "minutes, starts, chance_of_playing_next_round, chance_of_playing_this_round, "
            "expected_goals, expected_assists, expected_goal_involvements, expected_goals_conceded, "
            "expected_goals_per_90, expected_assists_per_90, expected_goals_conceded_per_90, clean_sheets_per_90, "
            "bps, ict_index, form, points_per_game, selected_by_percent, news"
        )
        if player_ids:
            placeholders_p = ",".join("?" for _ in player_ids)
            players_rows = connection.execute(
                f"SELECT {cols} FROM players WHERE snapshot_id = ? AND player_id IN ({placeholders_p})",
                (snapshot_id, *player_ids),
            ).fetchall()
        else:
            players_rows = connection.execute(
                f"SELECT {cols} FROM players WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchall()

    team_fixtures: dict[int, list[dict[str, Any]]] = {t_id: [] for t_id in team_map}
    for _, event, team_h, team_a, h_diff, a_diff in fixtures_rows:
        h_fdr = int(h_diff) if h_diff is not None else 3
        a_fdr = int(a_diff) if a_diff is not None else 3
        if team_h in team_fixtures:
            team_fixtures[team_h].append({
                "event": event,
                "opponent_id": team_a,
                "opponent_short": team_map.get(team_a, f"T{team_a}"),
                "is_home": True,
                "fdr": h_fdr,
            })
        if team_a in team_fixtures:
            team_fixtures[team_a].append({
                "event": event,
                "opponent_id": team_h,
                "opponent_short": team_map.get(team_h, f"T{team_h}"),
                "is_home": False,
                "fdr": a_fdr,
            })

    profiles: dict[int, MultiGameweekProfile] = {}
    for row in players_rows:
        (
            p_id, web_name, pos_id, t_id, price, status, pts,
            mins, starts, chance_next, chance_this,
            xg, xa, xgi, xgc,
            xg90, xa90, xgc90, cs90,
            bps, ict, form, ppg, selected, news
        ) = row

        pos = Position(pos_id)
        t_short = team_map.get(t_id, f"T{t_id}")
        base_xp = calculate_base_xp(price, pts, finished_matches)
        avail = calculate_availability(status, chance_next)

        exp_mins, p_start, prob_60, prob_sub = calculate_expected_minutes(
            status=status,
            chance_of_playing_next_round=chance_next,
            starts=starts or 0,
            minutes=mins or 0,
            finished_matches=finished_matches,
            price_tenths=price,
            position=pos,
        )

        p_fixtures = team_fixtures.get(t_id, [])
        total_xp = 0.0
        total_floor = 0.0
        total_ceil = 0.0
        sum_var = 0.0

        for f in p_fixtures:
            fdr = f["fdr"]
            is_home = f["is_home"]
            baseline_xp = calculate_fixture_xp(base_xp, avail, pos, fdr, is_home)
            comp = calculate_component_xp(
                position=pos,
                price_tenths=price,
                fdr=fdr,
                is_home=is_home,
                expected_minutes=exp_mins,
                prob_60_plus=prob_60,
                prob_sub=prob_sub,
                expected_goals_per_90=xg90 or 0.0,
                expected_assists_per_90=xa90 or 0.0,
                expected_goals_conceded_per_90=xgc90 or 0.0,
                clean_sheets_per_90=cs90 or 0.0,
                finished_matches=finished_matches,
            )

            if avail <= 0.0:
                final_xp = 0.0
                f_floor = 0.0
                f_ceil = 0.0
                f_var = 0.0
            else:
                final_xp = round(0.70 * comp["total"] + 0.30 * baseline_xp, 2)
                f_floor = comp["floor"]
                f_ceil = comp["ceil"]
                f_var = comp["sigma"] ** 2

            total_xp += final_xp
            total_floor += f_floor
            total_ceil += f_ceil
            sum_var += f_var

        profiles[p_id] = MultiGameweekProfile(
            player_id=p_id,
            web_name=web_name,
            position=pos,
            team_id=t_id,
            team_short=t_short,
            price_tenths=price,
            status=status,
            expected_points=round(total_xp, 2),
            expected_minutes=round(exp_mins * len(p_fixtures), 1),
            xp_floor=round(total_floor, 2),
            xp_ceiling=round(total_ceil, 2),
            standard_deviation=round(math.sqrt(sum_var), 2),
            fixtures_count=len(p_fixtures),
        )

    return profiles


def project_multi_gameweek(
    gameweeks: list[int],
    player_ids: list[int] | None = None,
    database_path: Path = DATABASE_PATH,
) -> dict[int, float]:
    """Generate total expected points projections aggregated across multiple gameweeks.

    Returns a mapping of player_id -> total projected xP across the specified gameweeks.
    """
    profiles = project_multi_gameweek_profiles(gameweeks, player_ids, database_path)
    return {p_id: prof.expected_points for p_id, prof in profiles.items()}
