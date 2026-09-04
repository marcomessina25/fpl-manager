"""Chip Strategy and Blank / Double Gameweek Planner for FPL Manager V0.4.

Analyzes the remaining Premier League fixture calendar for Blank Gameweeks (BGW)
and Double Gameweeks (DGW), evaluates squad readiness, models expected chip valuations,
and generates an optimal multi-gameweek chip execution roadmap.
"""

from contextlib import closing
import json
from pathlib import Path
from typing import Any

from .expected_points import ExpectedPointsProjection, project_gameweek
from .fixtures import get_current_gameweek
from .lineup import select_starting_lineup
from .models import Position
from .squad_state import CurrentSquadState, load_current_squad
from .storage import SnapshotStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"
CHIP_STRATEGY_REPORT_PATH = PROJECT_ROOT / "reports" / "chip_strategy.json"

AVAILABLE_CHIPS = ("wildcard", "freehit", "benchboost", "triplecaptain")
CHIP_ALIASES = {
    "wildcard": "wildcard",
    "wildcard_1": "wildcard",
    "wildcard_2": "wildcard",
    "freehit": "freehit",
    "free_hit": "freehit",
    "benchboost": "benchboost",
    "bench_boost": "benchboost",
    "triplecaptain": "triplecaptain",
    "triple_captain": "triplecaptain",
}


def resolve_segment_range(
    start_gw: int,
    end_gw: int | None = None,
) -> tuple[int, int, str]:
    """Determine active season segment and clamp planning range.

    Season segments:
    - Segment 1: Gameweeks 1 to 19 (First Half)
    - Segment 2: Gameweeks 20 to 38 (Second Half)

    Chips reset after the end of Gameweek 19.
    Returns (clamped_start_gw, clamped_end_gw, segment_name).
    """
    if start_gw <= 19:
        segment_name = "1-19"
        max_seg_gw = 19
        clamped_start = max(1, start_gw)
        if end_gw is None or end_gw > max_seg_gw:
            clamped_end = max_seg_gw
        else:
            clamped_end = max(clamped_start, min(end_gw, max_seg_gw))
    else:
        segment_name = "20-38"
        max_seg_gw = 38
        clamped_start = max(20, start_gw)
        if end_gw is None or end_gw > max_seg_gw:
            clamped_end = max_seg_gw
        elif end_gw < 20:
            clamped_end = max_seg_gw
        else:
            clamped_end = max(clamped_start, min(end_gw, max_seg_gw))

    return clamped_start, clamped_end, segment_name


def get_used_chips_for_segment(
    start_gw: int,
    team_id: str | None = None,
    database_path: Path = DATABASE_PATH,
) -> list[str]:
    """Query logged decisions to find chips already used in the active segment.

    Chips reset after the end of Gameweek 19:
    - When in Gameweeks 1-19, only chips logged in GW 1..19 (prior to start_gw) are used.
    - When in Gameweeks 20-38, chips logged in GW 1..19 are reset and ignored; only chips logged
      in GW 20..38 (prior to start_gw) are used.
    """
    store = SnapshotStore(database_path)
    store.initialize()

    if start_gw <= 19:
        seg_start = 1
        seg_end = 19
    else:
        seg_start = 20
        seg_end = 38

    with closing(store._connect()) as connection:
        if team_id:
            rows = connection.execute(
                """
                SELECT DISTINCT chip_played FROM decisions
                WHERE team_id = ? AND gameweek >= ? AND gameweek <= ? AND gameweek < ?
                  AND chip_played IS NOT NULL AND chip_played != ''
                """,
                (team_id, seg_start, seg_end, start_gw),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT DISTINCT chip_played FROM decisions
                WHERE gameweek >= ? AND gameweek <= ? AND gameweek < ?
                  AND chip_played IS NOT NULL AND chip_played != ''
                """,
                (seg_start, seg_end, start_gw),
            ).fetchall()

    used: list[str] = []
    for (cp,) in rows:
        norm = CHIP_ALIASES.get(cp.lower().strip(), cp.lower().strip())
        if norm in AVAILABLE_CHIPS and norm not in used:
            used.append(norm)
    return used


def analyze_fixture_calendar(
    start_gw: int | None = None,
    end_gw: int | None = None,
    squad_path: Path | None = None,
    database_path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    """Scan upcoming calendar events to identify Blank and Double Gameweeks within active segment."""
    store = SnapshotStore(database_path)
    store.initialize()

    if start_gw is None:
        start_gw = get_current_gameweek(store)

    start_gw, end_gw, segment_name = resolve_segment_range(start_gw, end_gw)

    squad_player_ids: set[int] = set()
    squad_team_counts: dict[int, int] = {}
    if squad_path and squad_path.exists():
        try:
            state = load_current_squad(squad_path)
            squad_player_ids = set(state.player_ids)
        except Exception:
            pass

    with closing(store._connect()) as connection:
        snapshot = connection.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        if snapshot is None:
            raise RuntimeError("No FPL data found in database. Run `fpl update` first.")
        snapshot_id = snapshot[0]

        team_rows = connection.execute("SELECT team_id, short_name, name FROM teams WHERE snapshot_id = ?", (snapshot_id,)).fetchall()
        teams = {row[0]: {"short_name": row[1], "name": row[2]} for row in team_rows}

        # Player teams
        if squad_player_ids:
            placeholders = ",".join("?" for _ in squad_player_ids)
            p_rows = connection.execute(
                f"SELECT player_id, team_id, web_name FROM players WHERE snapshot_id = ? AND player_id IN ({placeholders})",
                (snapshot_id, *squad_player_ids),
            ).fetchall()
            player_team_map = {r[0]: r[1] for r in p_rows}
            player_name_map = {r[0]: r[2] for r in p_rows}
        else:
            player_team_map = {}
            player_name_map = {}

        # Fixtures in range
        fixture_rows = connection.execute(
            """
            SELECT fixture_id, event, team_h, team_a, team_h_difficulty, team_a_difficulty
            FROM fixtures
            WHERE snapshot_id = ? AND event >= ? AND event <= ?
            ORDER BY event ASC
            """,
            (snapshot_id, start_gw, end_gw),
        ).fetchall()

    fixtures_by_event: dict[int, list[Any]] = {}
    for r in fixture_rows:
        event = r[1]
        if event is not None:
            fixtures_by_event.setdefault(event, []).append(r)

    calendar_gws = []
    has_bgw = False
    has_dgw = False

    all_team_ids = set(teams.keys())

    for gw in range(start_gw, end_gw + 1):
        gw_fixtures = fixtures_by_event.get(gw, [])
        team_match_counts: dict[int, int] = {t_id: 0 for t_id in all_team_ids}
        for f in gw_fixtures:
            h, a = f[2], f[3]
            team_match_counts[h] = team_match_counts.get(h, 0) + 1
            team_match_counts[a] = team_match_counts.get(a, 0) + 1

        blanking_teams = [
            {"team_id": tid, "short_name": teams[tid]["short_name"]}
            for tid, count in team_match_counts.items()
            if count == 0
        ]
        doubling_teams = [
            {"team_id": tid, "short_name": teams[tid]["short_name"], "matches": count}
            for tid, count in team_match_counts.items()
            if count >= 2
        ]

        if blanking_teams and doubling_teams:
            gw_type = "BLANK_AND_DOUBLE"
            has_bgw = True
            has_dgw = True
        elif doubling_teams:
            gw_type = "DOUBLE"
            has_dgw = True
        elif blanking_teams:
            gw_type = "BLANK"
            has_bgw = True
        else:
            gw_type = "STANDARD"

        # Squad impact
        squad_blanks = []
        squad_doubles = []
        if squad_player_ids:
            for pid in squad_player_ids:
                tid = player_team_map.get(pid)
                if tid is not None:
                    m_count = team_match_counts.get(tid, 1)
                    if m_count == 0:
                        squad_blanks.append({"id": pid, "name": player_name_map.get(pid, f"ID {pid}"), "team": teams[tid]["short_name"]})
                    elif m_count >= 2:
                        squad_doubles.append({"id": pid, "name": player_name_map.get(pid, f"ID {pid}"), "team": teams[tid]["short_name"], "matches": m_count})

        calendar_gws.append({
            "gameweek": gw,
            "gw_type": gw_type,
            "fixtures_count": len(gw_fixtures),
            "blanking_teams": blanking_teams,
            "doubling_teams": doubling_teams,
            "squad_blank_count": len(squad_blanks),
            "squad_blank_players": squad_blanks,
            "squad_double_count": len(squad_doubles),
            "squad_double_players": squad_doubles,
        })

    return {
        "segment": segment_name,
        "segment_start": 1 if start_gw <= 19 else 20,
        "segment_end": 19 if start_gw <= 19 else 38,
        "start_gw": start_gw,
        "end_gw": end_gw,
        "chips_reset_after_gw": 19,
        "has_confirmed_blank_gameweeks": has_bgw,
        "has_confirmed_double_gameweeks": has_dgw,
        "calendar": calendar_gws,
    }


def evaluate_chip_candidates(
    start_gw: int | None = None,
    end_gw: int | None = None,
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
) -> dict[str, list[dict[str, Any]]]:
    """Evaluate expected value and timing quality for each chip across upcoming gameweeks in active segment."""
    calendar_info = analyze_fixture_calendar(
        start_gw=start_gw,
        end_gw=end_gw,
        squad_path=squad_path,
        database_path=database_path,
    )
    start_gw = calendar_info["start_gw"]
    end_gw = calendar_info["end_gw"]
    calendar = calendar_info["calendar"]

    tc_candidates = []
    bb_candidates = []
    fh_candidates = []
    wc_candidates = []

    for gw_info in calendar:
        gw = gw_info["gameweek"]
        gw_type = gw_info["gw_type"]
        squad_blanks = gw_info["squad_blank_count"]
        squad_doubles = gw_info["squad_double_count"]

        # Run projection for target gameweek
        try:
            projections = project_gameweek(gameweek=gw, database_path=database_path)
        except Exception:
            projections = []

        if not projections:
            continue

        # 1. Triple Captain Candidate Evaluation
        top_cap = max(projections, key=lambda p: p.expected_points)
        tc_expected_boost = round(top_cap.expected_points, 1)
        tc_rating = round(tc_expected_boost * (1.3 if gw_type in ("DOUBLE", "BLANK_AND_DOUBLE") else 1.0), 1)

        tc_candidates.append({
            "gameweek": gw,
            "gw_type": gw_type,
            "recommended_target_id": top_cap.player_id,
            "recommended_target_name": top_cap.web_name,
            "recommended_target_team": top_cap.team_short,
            "expected_points": top_cap.expected_points,
            "expected_chip_boost": tc_expected_boost,
            "rating": tc_rating,
            "reasoning": (
                f"Double Gameweek captaincy on {top_cap.web_name} with {tc_expected_boost} xP"
                if gw_type in ("DOUBLE", "BLANK_AND_DOUBLE")
                else f"Favorable single fixture for {top_cap.web_name} with {tc_expected_boost} xP"
            ),
        })

        # 2. Free Hit Candidate Evaluation
        fh_urgency = (squad_blanks * 4.0) + (10.0 if gw_type == "BLANK" else 0.0) + (15.0 if gw_type == "DOUBLE" and squad_doubles == 0 else 0.0)
        fh_expected_gain = round(squad_blanks * 3.5 + (8.0 if gw_type in ("BLANK", "DOUBLE") else 0.0), 1)

        fh_candidates.append({
            "gameweek": gw,
            "gw_type": gw_type,
            "squad_blanks": squad_blanks,
            "expected_chip_boost": fh_expected_gain,
            "rating": round(fh_urgency, 1),
            "reasoning": (
                f"Critical BGW relief: {squad_blanks} squad players blanking"
                if squad_blanks >= 3
                else (f"Targeted {gw_type} squad deployment" if gw_type != "STANDARD" else "Standard SGW (low priority)")
            ),
        })

        # 3. Bench Boost Candidate Evaluation
        try:
            lineup_res = select_starting_lineup(squad_path=squad_path, database_path=database_path, gameweek=gw)
            bench_xp = round(sum(p.get("expected_points", 0.0) for p in lineup_res.get("bench", [])), 1)
        except Exception:
            bench_xp = 8.0

        bb_multiplier = 1.4 if (gw_type in ("DOUBLE", "BLANK_AND_DOUBLE") or squad_doubles >= 2) else 1.0
        bb_rating = round(bench_xp * bb_multiplier, 1)

        bb_candidates.append({
            "gameweek": gw,
            "gw_type": gw_type,
            "squad_doubles": squad_doubles,
            "expected_bench_xp": bench_xp,
            "rating": bb_rating,
            "reasoning": (
                f"Double Gameweek Bench Boost: {squad_doubles} squad doublers active, {bench_xp} bench xP"
                if gw_type in ("DOUBLE", "BLANK_AND_DOUBLE")
                else f"Standard gameweek bench deployment ({bench_xp} bench xP)"
            ),
        })

        # 4. Wildcard Candidate Evaluation
        wc_rating = 10.0
        wc_reason = "Mid-season squad overhaul"
        if gw_type in ("DOUBLE", "BLANK_AND_DOUBLE"):
            wc_rating = 18.0
            wc_reason = f"DGW setup / overhaul for upcoming fixture congestion in GW{gw}"
        elif squad_blanks >= 3:
            wc_rating = 15.0
            wc_reason = f"Restructure squad avoiding {squad_blanks} blanking players"

        wc_candidates.append({
            "gameweek": gw,
            "gw_type": gw_type,
            "rating": round(wc_rating, 1),
            "reasoning": wc_reason,
        })

    tc_candidates.sort(key=lambda x: x["rating"], reverse=True)
    fh_candidates.sort(key=lambda x: x["rating"], reverse=True)
    bb_candidates.sort(key=lambda x: x["rating"], reverse=True)
    wc_candidates.sort(key=lambda x: x["rating"], reverse=True)

    return {
        "triplecaptain": tc_candidates,
        "freehit": fh_candidates,
        "benchboost": bb_candidates,
        "wildcard": wc_candidates,
    }


def recommend_chip_strategy(
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    start_gw: int | None = None,
    end_gw: int | None = None,
    used_chips: list[str] | None = None,
    report_path: Path = CHIP_STRATEGY_REPORT_PATH,
    team_id: str | None = None,
) -> dict[str, Any]:
    """Generate an optimal conflict-free multi-gameweek chip deployment roadmap.

    Limits planning to Gameweeks 1-19 when in Segment 1, and Gameweeks 20-38 when in Segment 2.
    Chips reset after the end of Gameweek 19.
    """
    store = SnapshotStore(database_path)
    store.initialize()

    if start_gw is None:
        start_gw = get_current_gameweek(store)

    start_gw, end_gw, segment_name = resolve_segment_range(start_gw, end_gw)

    # Detect chips already used in this specific segment from persistent decision logs
    logged_used = get_used_chips_for_segment(start_gw, team_id=team_id, database_path=database_path)

    # Read chips used from squad state (chips not remaining in squad.json)
    squad_used: list[str] = []
    if squad_path and Path(squad_path).exists():
        try:
            raw_squad = json.loads(Path(squad_path).read_text(encoding="utf-8"))
            if "chips_remaining" in raw_squad and raw_squad["chips_remaining"] is not None:
                squad_gw = raw_squad.get("gameweek") or raw_squad.get("current_gameweek") or 1
                same_segment = (start_gw <= 19 and squad_gw <= 19) or (start_gw >= 20 and squad_gw >= 20)
                if same_segment:
                    raw_rem = [str(c).lower().strip() for c in raw_squad["chips_remaining"]]
                    s_rem = set()
                    for c in raw_rem:
                        if start_gw <= 19:
                            if c in ("wildcard_2", "wildcard2"):
                                continue
                        elif start_gw >= 20:
                            if c in ("wildcard_1", "wildcard1"):
                                continue
                        norm = CHIP_ALIASES.get(c, c)
                        s_rem.add(norm)

                    for c in AVAILABLE_CHIPS:
                        if c not in s_rem and c not in squad_used:
                            squad_used.append(c)
        except Exception:
            pass

    # Process explicit caller-supplied used chips
    explicit_used: list[str] = []
    if used_chips:
        for c in used_chips:
            raw_c = c.lower().strip()
            # Handle segment-specific wildcards
            if start_gw <= 19 and raw_c in ("wildcard_2", "wildcard2"):
                continue  # Wildcard 2 applies to segment 2
            if start_gw >= 20 and raw_c in ("wildcard_1", "wildcard1"):
                continue  # Wildcard 1 belongs to segment 1; reset!
            norm = CHIP_ALIASES.get(raw_c, raw_c)
            if norm in AVAILABLE_CHIPS and norm not in explicit_used:
                explicit_used.append(norm)

    used_set = set(logged_used) | set(squad_used) | set(explicit_used)
    available = [c for c in AVAILABLE_CHIPS if c not in used_set]

    calendar_info = analyze_fixture_calendar(
        start_gw=start_gw,
        end_gw=end_gw,
        squad_path=squad_path,
        database_path=database_path,
    )
    candidates = evaluate_chip_candidates(
        start_gw=start_gw,
        end_gw=end_gw,
        squad_path=squad_path,
        database_path=database_path,
    )

    assigned_gws: set[int] = set()
    recommendations: list[dict[str, Any]] = []

    chip_priority = ["freehit", "triplecaptain", "benchboost", "wildcard"]
    sorted_available = [c for c in chip_priority if c in available]

    for chip in sorted_available:
        chip_cand_list = candidates.get(chip, [])
        for cand in chip_cand_list:
            gw = cand["gameweek"]
            if gw not in assigned_gws:
                assigned_gws.add(gw)
                recommendations.append({
                    "chip": chip,
                    "gameweek": gw,
                    "gw_type": cand["gw_type"],
                    "rating": cand["rating"],
                    "reasoning": cand["reasoning"],
                    "details": cand,
                })
                break

    recommendations.sort(key=lambda x: x["gameweek"])

    result = {
        "segment": segment_name,
        "segment_start": 1 if start_gw <= 19 else 20,
        "segment_end": 19 if start_gw <= 19 else 38,
        "start_gw": start_gw,
        "end_gw": end_gw,
        "chips_reset_after_gw": 19,
        "available_chips": available,
        "used_chips": sorted(list(used_set)),
        "has_confirmed_blank_gameweeks": calendar_info["has_confirmed_blank_gameweeks"],
        "has_confirmed_double_gameweeks": calendar_info["has_confirmed_double_gameweeks"],
        "recommended_schedule": recommendations,
        "candidate_rankings": {
            chip: candidates.get(chip, [])[:3] for chip in AVAILABLE_CHIPS
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result
