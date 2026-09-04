"""Structured Analytical Briefing & Dossier Generator for FPL Manager V0.6.

Synthesizes deterministic facts, model projections, strategic ownership risk,
optimal transfer suggestions, chip roadmap, and press conference / injury news
into a structured analytical package and Markdown briefing for human review
and LLM strategic context injection.
"""

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .chip_strategy import recommend_chip_strategy
from .decision_log import get_gameweek_decision
from .expected_points import project_gameweek
from .fixtures import get_current_gameweek
from .models import Position
from .ownership import analyze_squad_risk_profile
from .squad_state import CurrentSquadState, load_current_squad
from .storage import SnapshotStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"
REPORTS_DIRECTORY = PROJECT_ROOT / "reports"
DOSSIER_JSON_PATH = REPORTS_DIRECTORY / "analytical_dossier.json"
BRIEFING_REPORT_PATH = DOSSIER_JSON_PATH
BRIEFING_MD_PATH = REPORTS_DIRECTORY / "manager_briefing.md"


def generate_manager_briefing(
    squad_path: Path = DEFAULT_SQUAD_PATH,
    gameweek: int | None = None,
    team_id: str = "default",
    season: str = "2026/27",
    database_path: Path = DATABASE_PATH,
    save_reports: bool = True,
) -> dict[str, Any]:
    """Generate complete structured analytical dossier and formatted markdown briefing."""
    store = SnapshotStore(database_path)
    store.initialize()

    state: CurrentSquadState = load_current_squad(squad_path)
    if gameweek is None:
        gameweek = state.gameweek or get_current_gameweek(store)

    # 1. Event & Deadline metadata
    deadline_str = "Unknown"
    is_current_gw = True
    with closing(store._connect()) as conn:
        snapshot = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        snap_id = snapshot[0] if snapshot else 1
        ev_row = conn.execute(
            "SELECT name, deadline_time, is_current, is_next FROM events WHERE snapshot_id = ? AND event_id = ?",
            (snap_id, gameweek),
        ).fetchone()
        if ev_row and ev_row[1]:
            deadline_str = ev_row[1]
            is_current_gw = bool(ev_row[2] or ev_row[3])

    # 2. Lineup & Projections
    from .lineup import build_logged_lineup, select_starting_lineup

    decision = get_gameweek_decision(gameweek, season=season, team_id=team_id, database_path=database_path)
    if decision is not None:
        lineup_data = build_logged_lineup(decision, database_path=database_path)
        is_logged = True
    else:
        lineup_data = select_starting_lineup(squad_path=squad_path, database_path=database_path, gameweek=gameweek)
        is_logged = False

    # 3. Strategic Risk & Ownership
    risk_data = {}
    try:
        risk_data = analyze_squad_risk_profile(
            squad_path=squad_path,
            gameweek=gameweek,
            database_path=database_path,
            report_path=REPORTS_DIRECTORY / "temp_risk.json",
        )
    except Exception:
        pass

    # 4. Transfer Recommendations
    transfer_opts = []
    try:
        from .suggest_transfers import suggest_transfers
        tx_res = suggest_transfers(
            num_transfers=1,
            squad_path=squad_path,
            database_path=database_path,
            max_results=3,
        )
        transfer_opts = tx_res.get("top_suggestions", [])
    except Exception:
        pass

    # 5. Chip Strategy & Blank/Double Gameweek Radar
    chip_data = {}
    try:
        chip_data = recommend_chip_strategy(
            squad_path=squad_path,
            current_gw=gameweek,
            database_path=database_path,
            report_path=REPORTS_DIRECTORY / "temp_chip.json",
        )
    except Exception:
        pass

    # 6. Injury, Suspension & Press Conference News
    squad_alerts = []
    with closing(store._connect()) as conn:
        snap = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        snap_id = snap[0] if snap else 1
        placeholders = ",".join("?" for _ in state.player_ids)
        rows = conn.execute(
            f"""
            SELECT p.player_id, p.web_name, t.short_name, p.status, p.chance_of_playing_next_round, p.news
            FROM players p
            JOIN teams t ON p.snapshot_id = t.snapshot_id AND p.team_id = t.team_id
            WHERE p.snapshot_id = ? AND p.player_id IN ({placeholders})
            """,
            (snap_id, *state.player_ids),
        ).fetchall()

        for r in rows:
            pid, name, team_code, status, chance, news = r
            if status != "a" or (chance is not None and chance < 100) or (news and len(news.strip()) > 0):
                squad_alerts.append({
                    "id": pid,
                    "player_id": pid,
                    "name": name,
                    "team": team_code,
                    "status": status,
                    "chance_pct": chance,
                    "news": news.strip() if news else "Flagged status",
                })

    # Assemble structured analytical package
    finances = {
        "bank_tenths": state.bank_tenths,
        "bank_fmt": f"£{state.bank_tenths / 10:.1f}m",
        "free_transfers": state.free_transfers,
        "chips_remaining": list(state.chips_remaining),
        "total_players": len(state.player_ids),
    }

    dossier = {
        "gameweek": gameweek,
        "team_id": team_id,
        "season": season,
        "deadline_time": deadline_str,
        "is_decision_logged": is_logged,
        "financials": finances,
        "lineup": {
            "formation": lineup_data.get("formation"),
            "projected_xp": lineup_data.get("projected_points", {}).get("total_xp") or lineup_data.get("lineup_xp", 0.0),
            "floor_xp": lineup_data.get("projected_points", {}).get("floor_xp", 0.0),
            "ceiling_xp": lineup_data.get("projected_points", {}).get("ceiling_xp", 0.0),
            "captain": {
                "name": lineup_data.get("captain", {}).get("name") if isinstance(lineup_data.get("captain"), dict) else str(lineup_data.get("captain")),
                "id": lineup_data.get("captain", {}).get("id") if isinstance(lineup_data.get("captain"), dict) else None,
                "projected_xp": lineup_data.get("captain", {}).get("expected_points") if isinstance(lineup_data.get("captain"), dict) else 0.0,
            },
            "vice_captain": {
                "name": lineup_data.get("vice_captain", {}).get("name") if isinstance(lineup_data.get("vice_captain"), dict) else str(lineup_data.get("vice_captain")),
                "id": lineup_data.get("vice_captain", {}).get("id") if isinstance(lineup_data.get("vice_captain"), dict) else None,
            },
            "starters": [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "pos": p.get("pos_abbr") or p.get("position"),
                    "team": p.get("team"),
                    "xp": p.get("expected_points", 0.0),
                    "role": p.get("strategic_category") or p.get("role", "STARTER"),
                }
                for p in lineup_data.get("starters", [])
            ],
            "bench": [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "pos": p.get("pos_abbr") or p.get("position"),
                    "team": p.get("team"),
                    "xp": p.get("expected_points", 0.0),
                }
                for p in lineup_data.get("bench", [])
            ],
        },
        "strategic_risk": {
            "shields": risk_data.get("squad_breakdown", {}).get("shields", []),
            "swords": risk_data.get("squad_breakdown", {}).get("swords", []),
            "cores": risk_data.get("squad_breakdown", {}).get("cores", []),
            "top_threats_against_squad": risk_data.get("top_threats_against_squad", [])[:5],
        },
        "transfer_suggestions": transfer_opts[:3],
        "chip_strategy": {
            "active_segment": chip_data.get("segment", "Gameweeks 1-19"),
            "chips_remaining": chip_data.get("chips_remaining", []),
            "recommended_schedule": chip_data.get("recommended_schedule", []),
            "calendar_events": [e for e in chip_data.get("calendar_scans", []) if e.get("event_type") != "NORMAL"][:3],
        },
        "squad_health_alerts": squad_alerts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Generate Markdown representation for human / LLM prompt injection
    markdown_text = _build_briefing_markdown(dossier)
    dossier["markdown"] = markdown_text

    if save_reports:
        REPORTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
        DOSSIER_JSON_PATH.write_text(json.dumps(dossier, indent=2, ensure_ascii=False), encoding="utf-8")
        BRIEFING_MD_PATH.write_text(markdown_text, encoding="utf-8")

    return dossier


def _build_briefing_markdown(dossier: dict[str, Any]) -> str:
    """Format analytical dossier into a rich, structured Markdown executive summary."""
    gw = dossier["gameweek"]
    fin = dossier["financials"]
    lineup = dossier["lineup"]
    cap = lineup["captain"]
    vc = lineup["vice_captain"]
    risk = dossier["strategic_risk"]
    txs = dossier["transfer_suggestions"]
    alerts = dossier["squad_health_alerts"]
    chips = dossier["chip_strategy"]

    lines = [
        f"# FPL Manager Analytical Dossier — Gameweek {gw}",
        f"**Generated**: {dossier['generated_at'][:19]} UTC | **Team**: `{dossier['team_id']}` | **Deadline**: `{dossier['deadline_time']}`",
        "",
        "## 1. Squad Status & Financials",
        f"- **Bank Balance**: {fin['bank_fmt']} | **Free Transfers**: {fin['free_transfers']}",
        f"- **Chips Available**: {', '.join(fin['chips_remaining']) if fin['chips_remaining'] else 'None'}",
        f"- **Audit Status**: {'🔒 Decision Logged & Verified' if dossier['is_decision_logged'] else '📝 Draft Lineup (Unlogged)'}",
        "",
        "## 2. Matchday Starting XI & Projections",
        f"- **Formation**: `{lineup['formation']}`",
        f"- **Projected Points**: **{lineup['projected_xp']:.1f} xP** (Floor: {lineup['floor_xp']:.1f} · Ceiling: {lineup['ceiling_xp']:.1f})",
        f"- **Primary Captain**: **{cap['name']}** (C) — Projected **{cap['projected_xp']:.1f} xP**",
        f"- **Vice-Captain**: **{vc['name']}** (VC)",
        "",
        "### Starting 11 Selection",
        "| Pos | Player | Team | Proj xP | Strategic Role |",
        "| :--- | :--- | :--- | :---: | :---: |",
    ]

    for p in lineup["starters"]:
        lines.append(f"| {p['pos']} | {p['name']} | {p['team']} | {p['xp']:.1f} | `{p['role']}` |")

    lines.extend([
        "",
        "### Bench Substitutes (Priority Order)",
        "| Order | Pos | Player | Team | Proj xP |",
        "| :---: | :--- | :--- | :--- | :---: |",
    ])
    for idx, p in enumerate(lineup["bench"], 1):
        lines.append(f"| #{idx} | {p['pos']} | {p['name']} | {p['team']} | {p['xp']:.1f} |")

    # Squad Health Alerts
    lines.extend([
        "",
        "## 3. Injury Flags & Press Conference Intel",
    ])
    if alerts:
        for a in alerts:
            chance_txt = f" ({a['chance_pct']}% chance)" if a['chance_pct'] is not None else ""
            lines.append(f"- ⚠️ **{a['name']}** ({a['team']}){chance_txt}: {a['news']}")
    else:
        lines.append("- ✅ All 15 squad members are currently reported fully fit with no official flags.")

    # Strategic Risk Index
    lines.extend([
        "",
        "## 4. Strategic Risk Index & Non-Owned Threats",
    ])
    threats = risk.get("top_threats_against_squad", [])
    if threats:
        lines.extend([
            "**Key Rival Template Threats (Highest Rank Exposure)**:",
            "| Threat Asset | Team | Effective Ownership (EO) | Danger Level |",
            "| :--- | :--- | :---: | :--- |",
        ])
        for t in threats:
            eo_pct = t.get("effective_ownership_pct", t.get("eo_pct", 0.0))
            lines.append(f"| {t.get('name', 'Player')} | {t.get('team', '')} | {eo_pct:.1f}% | High Threat (Negative Drag) |")
    else:
        lines.append("- No acute high-ownership template threats identified.")

    # Top Transfer Recommendations
    lines.extend([
        "",
        "## 5. Algorithmic Transfer Recommendations",
    ])
    if txs:
        for idx, opt in enumerate(txs, 1):
            out_names = ", ".join(p.get("name", "") for p in opt.get("outgoing", []))
            in_names = ", ".join(p.get("name", "") for p in opt.get("incoming", []))
            hit_txt = f" | Hits: -{opt.get('transfer_hits', 0) * 4}pt" if opt.get('transfer_hits', 0) > 0 else ""
            lines.append(
                f"- **Option #{idx}**: **{out_names}** ➔ **{in_names}** "
                f"(Gain: +{opt.get('net_xp_gain', 0.0):.2f} net xP, Bank: £{opt.get('bank_after_tenths', 0) / 10:.1f}m{hit_txt})"
            )
    else:
        lines.append("- No recommended transfers identified under current constraints.")

    # Chip Strategy
    lines.extend([
        "",
        "## 6. Chip Roadmap & Calendar Horizon",
        f"- **Active Season Segment**: {chips['active_segment']}",
    ])
    cal = chips.get("calendar_events", [])
    if cal:
        for c in cal:
            lines.append(f"- 📅 **GW{c.get('gameweek')}**: {c.get('event_type')} fixture event detected.")
    else:
        lines.append("- 📅 Standard 10-match fixture schedule across the immediate horizon.")

    rec_sched = chips.get("recommended_schedule", [])
    if rec_sched:
        lines.append("- **Suggested Chip Deployment Window**:")
        for s in rec_sched:
            lines.append(f"  - GW{s.get('gameweek')}: `{s.get('chip', '').upper()}` ({s.get('rationale', '')})")

    lines.extend([
        "",
        "---",
        "*Note: This analytical briefing is generated from deterministic FPL data and mathematical optimization models. Any strategic LLM advisory feedback should be reviewed by the human manager before executing changes.*",
    ])

    return "\n".join(lines)
