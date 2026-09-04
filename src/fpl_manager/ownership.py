"""Effective Ownership (EO) and Strategic Risk Index engine for FPL Manager V0.4.

Analyzes player effective ownership, models captaincy distribution, and categorizes
assets into Shield (template preservation) vs Sword (differential attack).
Calculates manager net rank exposure and non-owned rank threats.
"""

from contextlib import closing
import json
from pathlib import Path
from typing import Any

from .expected_points import ExpectedPointsProjection, project_gameweek
from .fixtures import get_current_gameweek
from .models import Position
from .squad_state import CurrentSquadState, load_current_squad
from .storage import SnapshotStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"
OWNERSHIP_REPORT_PATH = PROJECT_ROOT / "reports" / "ownership_risk_report.json"


def get_player_ownership_map(database_path: Path = DATABASE_PATH) -> dict[int, float]:
    """Retrieve the latest selected_by_percent ownership mapping from database."""
    store = SnapshotStore(database_path)
    store.initialize()

    with closing(store._connect()) as connection:
        snapshot = connection.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        if snapshot is None:
            return {}
        snapshot_id = snapshot[0]

        rows = connection.execute(
            "SELECT player_id, selected_by_percent FROM players WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchall()

    return {row[0]: float(row[1]) for row in rows}


def estimate_captaincy_shares(
    projections: list[ExpectedPointsProjection],
    ownership_map: dict[int, float],
) -> dict[int, float]:
    """Estimate percentage of managers captaining each player in the target gameweek.

    Top captaincy picks in competitive FPL correlate strongly with high expected points
    and high ownership. Model weights attractiveness:
        Attractiveness = max(0, xP - 3.5)^2 * (ownership_pct / 100.0)
    Normalized across the player pool to sum to 100%.
    """
    scores: dict[int, float] = {}
    for p in projections:
        own = ownership_map.get(p.player_id, 0.0)
        # Only players with realistic xP above baseline and ownership have captaincy appeal
        if p.expected_points > 3.5 and own > 0.0:
            attractiveness = ((p.expected_points - 3.5) ** 2) * (own / 100.0)
            scores[p.player_id] = attractiveness
        else:
            scores[p.player_id] = 0.0

    total_attractiveness = sum(scores.values())
    if total_attractiveness <= 0.0:
        # Fallback: distribute evenly among top 5 xP players
        top_players = sorted(projections, key=lambda x: x.expected_points, reverse=True)[:5]
        if not top_players:
            return {}
        share = 100.0 / len(top_players)
        return {p.player_id: round(share, 1) for p in top_players}

    cap_shares: dict[int, float] = {}
    for pid, score in scores.items():
        if score > 0.0:
            pct = round((score / total_attractiveness) * 100.0, 1)
            cap_shares[pid] = pct
        else:
            cap_shares[pid] = 0.0

    return cap_shares


def compute_effective_ownership(ownership_pct: float, captaincy_pct: float) -> float:
    """Calculate Effective Ownership (EO = Ownership % + Captaincy %)."""
    return round(ownership_pct + captaincy_pct, 1)


def categorize_strategic_asset(
    effective_ownership: float,
    ownership_pct: float,
    expected_points: float,
    xp_ceiling: float,
) -> str:
    """Classify player into strategic role: SHIELD, SWORD, or CORE.

    - SHIELD: High EO (>= 40%) or high ownership (>= 35%). Protects rank against template hauls.
    - SWORD: Low EO (< 15% or ownership < 10%) with high output potential (xP >= 4.0 or ceiling >= 7.0).
             Gains massive rank over the field when hauling.
    - CORE: Moderate ownership (15% <= EO < 40%) forming balanced squad foundation.
    """
    if effective_ownership >= 40.0 or ownership_pct >= 35.0:
        return "SHIELD"
    if (effective_ownership < 15.0 or ownership_pct < 10.0) and (expected_points >= 4.0 or xp_ceiling >= 7.0):
        return "SWORD"
    return "CORE"


def compute_player_strategic_metrics(
    projection: ExpectedPointsProjection,
    ownership_pct: float,
    captaincy_pct: float,
) -> dict[str, Any]:
    """Compute comprehensive strategic metrics for an individual player."""
    eo = compute_effective_ownership(ownership_pct, captaincy_pct)
    category = categorize_strategic_asset(
        effective_ownership=eo,
        ownership_pct=ownership_pct,
        expected_points=projection.expected_points,
        xp_ceiling=projection.xp_ceiling,
    )

    # Shield Score: Expected points protected by matching template
    shield_score = round((eo / 100.0) * projection.expected_points, 2)

    # Sword Score: Differential points gained against the field
    field_unowned_frac = max(0.0, 1.0 - (eo / 100.0))
    sword_score = round(projection.expected_points * field_unowned_frac, 2)
    differential_upside = round(projection.xp_ceiling * field_unowned_frac, 2)

    pos_abbr = {
        Position.GOALKEEPER: "GKP",
        Position.DEFENDER: "DEF",
        Position.MIDFIELDER: "MID",
        Position.FORWARD: "FWD",
    }.get(projection.position, "MID")

    return {
        "player_id": projection.player_id,
        "name": projection.web_name,
        "team": projection.team_short,
        "position": pos_abbr,
        "price_fmt": f"£{projection.price_tenths / 10:.1f}m",
        "expected_points": projection.expected_points,
        "xp_floor": projection.xp_floor,
        "xp_ceiling": projection.xp_ceiling,
        "ownership_pct": round(ownership_pct, 1),
        "captaincy_pct": round(captaincy_pct, 1),
        "effective_ownership_pct": eo,
        "strategic_category": category,
        "shield_score": shield_score,
        "sword_score": sword_score,
        "differential_upside": differential_upside,
    }


def analyze_gameweek_ownership(
    gameweek: int,
    database_path: Path = DATABASE_PATH,
    top_n: int = 10,
) -> dict[str, Any]:
    """Analyze effective ownership and strategic asset categories across the league."""
    ownership_map = get_player_ownership_map(database_path)
    projections = project_gameweek(gameweek=gameweek, database_path=database_path)
    captaincy_map = estimate_captaincy_shares(projections, ownership_map)

    all_metrics = [
        compute_player_strategic_metrics(
            p,
            ownership_map.get(p.player_id, 0.0),
            captaincy_map.get(p.player_id, 0.0),
        )
        for p in projections
    ]

    top_eo = sorted(all_metrics, key=lambda x: x["effective_ownership_pct"], reverse=True)[:top_n]
    top_shields = sorted(
        [m for m in all_metrics if m["strategic_category"] == "SHIELD"],
        key=lambda x: x["shield_score"],
        reverse=True,
    )[:top_n]
    top_swords = sorted(
        [m for m in all_metrics if m["strategic_category"] == "SWORD"],
        key=lambda x: x["sword_score"],
        reverse=True,
    )[:top_n]

    return {
        "gameweek": gameweek,
        "total_players_evaluated": len(all_metrics),
        "top_effective_ownership": top_eo,
        "top_shields": top_shields,
        "top_swords": top_swords,
    }


def analyze_squad_risk_profile(
    squad_path: Path = DEFAULT_SQUAD_PATH,
    gameweek: int | None = None,
    database_path: Path = DATABASE_PATH,
    report_path: Path = OWNERSHIP_REPORT_PATH,
) -> dict[str, Any]:
    """Evaluate user's squad risk profile, net exposure, and non-owned rank threats."""
    state: CurrentSquadState = load_current_squad(squad_path)
    store = SnapshotStore(database_path)
    if gameweek is None:
        gameweek = get_current_gameweek(store)

    from .lineup import select_starting_lineup
    lineup_res = select_starting_lineup(squad_path=squad_path, database_path=database_path, gameweek=gameweek)

    ownership_map = get_player_ownership_map(database_path)
    projections = project_gameweek(gameweek=gameweek, database_path=database_path)
    captaincy_map = estimate_captaincy_shares(projections, ownership_map)

    proj_by_id = {p.player_id: p for p in projections}

    starter_ids = set(p["id"] for p in lineup_res["starters"])
    bench_ids = set(p["id"] for p in lineup_res["bench"])
    cap_id = lineup_res["captain"]["id"]
    vc_id = lineup_res["vice_captain"]["id"]

    squad_metrics = []
    for pid in state.player_ids:
        if pid not in proj_by_id:
            continue
        p = proj_by_id[pid]
        own = ownership_map.get(pid, 0.0)
        cap_share = captaincy_map.get(pid, 0.0)
        m = compute_player_strategic_metrics(p, own, cap_share)

        # Personal effective weight:
        # Captain: 200%
        # Starter: 100%
        # Bench: 0%
        if pid == cap_id:
            personal_weight = 200.0
            lineup_role = "CAPTAIN"
        elif pid == vc_id:
            personal_weight = 100.0
            lineup_role = "VICE_CAPTAIN"
        elif pid in starter_ids:
            personal_weight = 100.0
            lineup_role = "STARTER"
        else:
            personal_weight = 0.0
            lineup_role = "BENCH"

        net_exposure = round(personal_weight - m["effective_ownership_pct"], 1)
        rank_delta_per_point = round(net_exposure / 100.0, 2)

        m.update({
            "lineup_role": lineup_role,
            "personal_weight_pct": personal_weight,
            "net_exposure_pct": net_exposure,
            "rank_delta_per_point": rank_delta_per_point,
            "rank_leverage_verdict": (
                "Gain rank when player scores"
                if net_exposure > 0
                else ("Lose rank when player scores" if net_exposure < 0 else "Neutral")
            ),
        })
        squad_metrics.append(m)

    starters_m = [m for m in squad_metrics if m["lineup_role"] in ("STARTER", "CAPTAIN", "VICE_CAPTAIN")]
    bench_m = [m for m in squad_metrics if m["lineup_role"] == "BENCH"]

    template_alignment = round(sum(m["effective_ownership_pct"] for m in starters_m) / len(starters_m), 1) if starters_m else 0.0
    swords_in_xi = [m for m in starters_m if m["strategic_category"] == "SWORD"]
    shields_in_xi = [m for m in starters_m if m["strategic_category"] == "SHIELD"]

    # Identify top non-owned rank threats across the entire league
    squad_pids = set(state.player_ids)
    all_league_metrics = [
        compute_player_strategic_metrics(p, ownership_map.get(p.player_id, 0.0), captaincy_map.get(p.player_id, 0.0))
        for p in projections
        if p.player_id not in squad_pids
    ]
    all_league_metrics.sort(key=lambda x: x["effective_ownership_pct"], reverse=True)
    top_threats = []
    for t in all_league_metrics[:5]:
        top_threats.append({
            "player_id": t["player_id"],
            "name": t["name"],
            "team": t["team"],
            "effective_ownership_pct": t["effective_ownership_pct"],
            "expected_points": t["expected_points"],
            "net_exposure_pct": -t["effective_ownership_pct"],
            "rank_threat_drag": round((t["effective_ownership_pct"] / 100.0) * t["expected_points"], 2),
        })

    # Overall strategic verdict
    if template_alignment >= 50.0:
        verdict = "Template Shield (High Safety, Rank Preservation)"
    elif template_alignment < 30.0 or len(swords_in_xi) >= 3:
        verdict = "Differential Sword (High Upside, Aggressive Rank Climb)"
    else:
        verdict = "Balanced Hybrid (Balanced Template Core & Differential Attack)"

    result = {
        "gameweek": gameweek,
        "template_alignment_score": template_alignment,
        "strategic_verdict": verdict,
        "shield_count_in_xi": len(shields_in_xi),
        "sword_count_in_xi": len(swords_in_xi),
        "starters": starters_m,
        "bench": bench_m,
        "top_non_owned_rank_threats": top_threats,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result
