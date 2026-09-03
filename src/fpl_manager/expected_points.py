"""Transparent, deterministic expected-points (xP) baseline model for FPL Manager V0.2.

Assumptions:
1. Base productivity is estimated from player price tier and blended with observed points-per-match.
2. Player availability is discounted based on official FPL injury/suspension status.
3. Fixture difficulty (FDR) applies position-specific adjustments (defenders/GKs are more sensitive
   to fixture difficulty due to clean sheet odds).
4. Home/away venue effects apply a historical home advantage multiplier (+6% home, -6% away).
5. Gameweek xP sums all fixtures in that gameweek (0 for Blanks, 2x for Double Gameweeks).

See `docs/expected_points.md` for comprehensive documentation of these assumptions.
"""

from dataclasses import dataclass
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
    """Calculate expected points for a single match fixture."""
    if avail_mult <= 0.0:
        return 0.0
    fdr_mult = fdr_multiplier(position, fdr)
    ven_mult = venue_multiplier(is_home)
    return round(base_xp * avail_mult * fdr_mult * ven_mult, 2)


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
) -> ExpectedPointsProjection:
    """Compute expected points projection for a single player in a specific gameweek."""
    base_xp = calculate_base_xp(price_tenths, total_points, finished_matches)
    avail = availability_multiplier(status)

    fixture_projections: list[PlayerFixtureProjection] = []
    total_xp = 0.0

    for fix in team_fixtures_in_gw:
        opp_id = fix["opponent_id"]
        opp_short = fix["opponent_short"]
        is_home = fix["is_home"]
        fdr = fix["fdr"]
        venue = "H" if is_home else "A"

        fix_xp = calculate_fixture_xp(base_xp, avail, position, fdr, is_home)
        total_xp += fix_xp

        fixture_projections.append(
            PlayerFixtureProjection(
                event=gameweek,
                opponent_id=opp_id,
                opponent_short=opp_short,
                is_home=is_home,
                venue=venue,
                fdr=fdr,
                fixture_xp=fix_xp,
            )
        )

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

        # Load players
        if player_ids:
            placeholders = ",".join("?" for _ in player_ids)
            players_rows = connection.execute(
                f"""
                SELECT player_id, web_name, position_id, team_id, price_tenths, status, total_points
                FROM players
                WHERE snapshot_id = ? AND player_id IN ({placeholders})
                """,
                (snapshot_id, *player_ids),
            ).fetchall()
        else:
            players_rows = connection.execute(
                """
                SELECT player_id, web_name, position_id, team_id, price_tenths, status, total_points
                FROM players
                WHERE snapshot_id = ?
                """,
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
    for p_id, web_name, pos_id, t_id, price, status, pts in players_rows:
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
        )
        projections.append(proj)

    return projections


def project_multi_gameweek(
    gameweeks: list[int],
    player_ids: list[int] | None = None,
    database_path: Path = DATABASE_PATH,
) -> dict[int, float]:
    """Generate total expected points projections aggregated across multiple gameweeks.

    Returns a mapping of player_id -> total projected xP across the specified gameweeks.
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

        if player_ids:
            placeholders_p = ",".join("?" for _ in player_ids)
            players_rows = connection.execute(
                f"""
                SELECT player_id, web_name, position_id, team_id, price_tenths, status, total_points
                FROM players
                WHERE snapshot_id = ? AND player_id IN ({placeholders_p})
                """,
                (snapshot_id, *player_ids),
            ).fetchall()
        else:
            players_rows = connection.execute(
                """
                SELECT player_id, web_name, position_id, team_id, price_tenths, status, total_points
                FROM players
                WHERE snapshot_id = ?
                """,
                (snapshot_id,),
            ).fetchall()

    team_fixtures: dict[int, list[dict[str, Any]]] = {t_id: [] for t_id in team_map}
    for _, _, team_h, team_a, h_diff, a_diff in fixtures_rows:
        h_fdr = int(h_diff) if h_diff is not None else 3
        a_fdr = int(a_diff) if a_diff is not None else 3
        if team_h in team_fixtures:
            team_fixtures[team_h].append({"is_home": True, "fdr": h_fdr})
        if team_a in team_fixtures:
            team_fixtures[team_a].append({"is_home": False, "fdr": a_fdr})

    result: dict[int, float] = {}
    for p_id, _, pos_id, t_id, price, status, pts in players_rows:
        base_xp = calculate_base_xp(price, pts, finished_matches)
        avail = availability_multiplier(status)
        pos = Position(pos_id)
        player_xp = sum(
            calculate_fixture_xp(base_xp, avail, pos, f["fdr"], f["is_home"])
            for f in team_fixtures.get(t_id, [])
        )
        result[p_id] = round(player_xp, 2)

    return result

