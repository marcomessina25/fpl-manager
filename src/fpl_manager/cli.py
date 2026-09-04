"""Command-line entry points for the V0.1 local data engine."""

import argparse
import json
from pathlib import Path
from typing import Any

from .api import fetch_current_data
from .fixtures import analyze_squad_fixtures, analyze_team_fixtures
from .import_squad import (
    DEFAULT_PLAYERS_PATH,
    import_squad_from_file,
    search_player_exact_or_single,
)
from .lineup import LINEUP_REPORT_PATH, select_starting_lineup
from .planner import PLAN_REPORT_PATH, generate_multi_gameweek_plan
from .squad_report import SQUAD_REPORT_PATH, generate_squad_report
from .squad_state import load_current_squad
from .storage import SnapshotStore, utc_timestamp, write_raw_snapshot
from .suggest_transfers import TRANSFERS_REPORT_PATH, WILDCARD_REPORT_PATH, suggest_transfers, suggest_wildcard
from .decision_log import (
    get_gameweek_decision,
    list_decisions,
    log_decision_from_current_squad,
    record_actual_gameweek_score,
)
from .transfers import Transfer, validate_transfers


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
RAW_DIRECTORY = DATA_DIRECTORY / "raw"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
REPORT_PATH = PROJECT_ROOT / "reports" / "current_state.json"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"


def update() -> dict[str, object]:
    fetched_at = utc_timestamp()
    bootstrap, fixtures = fetch_current_data()
    write_raw_snapshot(RAW_DIRECTORY, "bootstrap-static", bootstrap, fetched_at)
    write_raw_snapshot(RAW_DIRECTORY, "fixtures", fixtures, fetched_at)
    store = SnapshotStore(DATABASE_PATH)
    snapshot_id = store.save_snapshot(bootstrap, fixtures, fetched_at)
    return {"snapshot_id": snapshot_id, "fetched_at": fetched_at, "players": len(bootstrap["elements"]), "fixtures": len(fixtures)}


def report() -> dict[str, object]:
    summary = SnapshotStore(DATABASE_PATH).latest_summary()
    if summary is None:
        raise RuntimeError("No FPL data found. Run `fpl update` first.")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def validate_transfer_set(
    squad_path: Path,
    transfers: list[str],
    by_name: bool = False,
    database_path: Path = DATABASE_PATH,
) -> dict[str, object]:
    store = SnapshotStore(database_path)
    parsed_transfers: list[Transfer] = []

    for value in transfers:
        if ":" not in value:
            raise RuntimeError(f"Invalid transfer '{value}'. Use OUTGOING:INCOMING.")
        outgoing_str, incoming_str = value.split(":", maxsplit=1)
        outgoing_str = outgoing_str.strip()
        incoming_str = incoming_str.strip()

        if by_name:
            outgoing_match = search_player_exact_or_single(store, outgoing_str)
            if outgoing_match is None:
                raise RuntimeError(f"Could not resolve outgoing player '{outgoing_str}' to a unique player.")

            incoming_match = search_player_exact_or_single(store, incoming_str)
            if incoming_match is None:
                raise RuntimeError(f"Could not resolve incoming player '{incoming_str}' to a unique player.")

            parsed_transfers.append(Transfer(outgoing_match["id"], incoming_match["id"]))
        else:
            try:
                parsed_transfers.append(Transfer(int(outgoing_str), int(incoming_str)))
            except ValueError as error:
                raise RuntimeError(f"Invalid transfer '{value}'. Use OUTGOING_ID:INCOMING_ID.") from error

    state = load_current_squad(squad_path)
    result = validate_transfers(state, store.latest_players(), parsed_transfers)
    return {
        "is_valid": result.is_valid,
        "errors": list(result.errors),
        "bank_after_tenths": result.bank_after_tenths,
        "transfer_hits": result.transfer_hits,
    }


def format_lineup_concise(result: dict[str, Any]) -> str:
    gw = result.get("gameweek")
    formation = result.get("formation")
    pts = result.get("projected_points", {})
    cap = result.get("captain", {})
    vc = result.get("vice_captain", {})
    starters = result.get("starters", [])
    bench = result.get("bench", [])

    floor_val = pts.get("floor_xp")
    ceil_val = pts.get("ceiling_xp")
    range_str = f" [Floor: {floor_val:.1f}, Ceil: {ceil_val:.1f}]" if floor_val is not None and ceil_val is not None else ""
    cap_floor = cap.get("xp_floor")
    cap_ceil = cap.get("xp_ceiling")
    cap_range = f" [Floor: {cap_floor*2:.1f}, Ceil: {cap_ceil*2:.1f}]" if cap_floor is not None and cap_ceil is not None else ""

    lines = [
        f"Matchday Lineup (GW{gw}) | Formation: {formation} | Projected: {pts.get('total_xp', 0.0):.1f} xP{range_str}",
        f"Captain: {cap.get('name')} ({cap.get('team')}, {cap.get('fixtures_summary')}) - {cap.get('expected_points', 0.0):.1f} xP (armband: {cap.get('expected_points', 0.0)*2:.1f} xP){cap_range}",
        f"Vice-Captain: {vc.get('name')} ({vc.get('team')}, {vc.get('fixtures_summary')}) - {vc.get('expected_points', 0.0):.1f} xP",
        "",
        f"Starting XI ({pts.get('starters_xp', 0.0):.1f} xP):",
    ]

    by_pos: dict[str, list[str]] = {}
    for p in starters:
        badge = " [C]" if p.get("role") == "CAPTAIN" else (" [VC]" if p.get("role") == "VICE_CAPTAIN" else "")
        pos = p.get("pos_abbr", "MID")
        by_pos.setdefault(pos, []).append(f"{p.get('name')}{badge} ({p.get('team')}, {p.get('fixtures_summary')}) - {p.get('expected_points', 0.0):.1f} xP")

    for pos in ("GKP", "DEF", "MID", "FWD"):
        if pos in by_pos:
            lines.append(f"  {pos}: " + " | ".join(by_pos[pos]))

    lines.append("")
    lines.append("Bench:")
    for idx, p in enumerate(bench, 1):
        role_label = "GK Sub" if p.get("role") == "GK_SUB" else f"Sub {idx - 1}"
        lines.append(f"  {idx}. {p.get('name')} ({p.get('team')}, {p.get('fixtures_summary')}) - {p.get('expected_points', 0.0):.1f} xP [{role_label}]")

    return "\n".join(lines)


def format_suggest_transfers_concise(result: dict[str, Any]) -> str:
    num_tx = result.get("num_transfers", 1)
    risk = result.get("risk_profile", "neutral")
    suggestions = result.get("top_suggestions", [])
    if not suggestions:
        return "No valid transfer options found matching criteria."

    risk_label = f" [Risk: {risk}]" if risk != "neutral" else ""
    lines = [f"Top {num_tx}-Transfer Options ({result.get('total_options_evaluated', 0)} evaluated){risk_label}:"]
    for idx, opt in enumerate(suggestions, 1):
        out_names = ", ".join(f"{p['name']} ({p['team']})" for p in opt["outgoing"])
        in_names = ", ".join(f"{p['name']} ({p['team']})" for p in opt["incoming"])
        hit_str = f" | Hit: -{opt['transfer_hits']}pt" if opt.get("transfer_hits", 0) > 0 else ""
        if "xp_delta" in opt:
            floor_delta = opt.get("floor_delta", 0.0)
            ceil_delta = opt.get("ceiling_delta", 0.0)
            range_str = f" [Floor: {floor_delta:+.1f}, Ceil: {ceil_delta:+.1f}]"
            xp_str = f" | xP: {opt['xp_delta']:+.1f}{range_str} (Score: {opt['score']:+.1f})"
        else:
            xp_str = f" | Score: {opt['score']:+.1f}"
        lines.append(
            f"  {idx:2d}. Out: {out_names} -> In: {in_names} | Bank: {opt['bank_after_fmt']}{xp_str} | FDR: {opt['fdr_improvement']:+.1f}{hit_str}"
        )
    return "\n".join(lines)


def format_wildcard_concise(result: dict[str, Any]) -> str:
    formation = result.get("formation")
    risk = result.get("risk_profile", "neutral")
    cost_fmt = result.get("total_cost_fmt", "£0.0m")
    bank_fmt = result.get("bank_remaining_fmt", "£0.0m")
    cap = result.get("captain", {})
    vc = result.get("vice_captain", {})
    starters = result.get("starters", [])
    bench = result.get("bench", [])

    tot_xp = result.get("total_lineup_xp", 0.0)
    st_xp = result.get("lineup_starters_xp", 0.0)
    floor_val = result.get("lineup_floor", 0.0)
    ceil_val = result.get("lineup_ceiling", 0.0)
    squad_xp = result.get("squad_xp", 0.0)

    risk_str = f" [Risk: {risk}]" if risk != "neutral" else ""

    lines = [
        f"Optimized Wildcard Squad | Formation: {formation}{risk_str} | Cost: {cost_fmt} (Bank: {bank_fmt})",
        f"Projected Starting XI: {tot_xp:.1f} xP [Floor: {floor_val:.1f}, Ceil: {ceil_val:.1f}] | 15-Man Squad: {squad_xp:.1f} xP",
        f"Captain: {cap.get('name')} ({cap.get('team')}, {cap.get('price_fmt')}) - {cap.get('expected_points', 0.0):.1f} xP (armband: {cap.get('expected_points', 0.0)*2:.1f} xP)",
        f"Vice-Captain: {vc.get('name')} ({vc.get('team')}, {vc.get('price_fmt')}) - {vc.get('expected_points', 0.0):.1f} xP",
        "",
        f"Starting XI ({st_xp:.1f} xP):",
    ]

    by_pos: dict[str, list[str]] = {}
    for p in starters:
        badge = " [C]" if p.get("role") == "CAPTAIN" else (" [VC]" if p.get("role") == "VICE_CAPTAIN" else "")
        pos = p.get("pos_abbr", "MID")
        by_pos.setdefault(pos, []).append(
            f"{p.get('name')}{badge} ({p.get('team')}, {p.get('price_fmt')}) - {p.get('expected_points', 0.0):.1f} xP"
        )

    for pos in ("GKP", "DEF", "MID", "FWD"):
        if pos in by_pos:
            lines.append(f"  {pos}: " + " | ".join(by_pos[pos]))

    lines.append("")
    lines.append("Bench:")
    for idx, p in enumerate(bench, 1):
        role_label = "GK Sub" if p.get("role") == "GK_SUB" else f"Sub {idx - 1}"
        lines.append(
            f"  {idx}. {p.get('name')} ({p.get('team')}, {p.get('price_fmt')}) - {p.get('expected_points', 0.0):.1f} xP [{role_label}]"
        )

    return "\n".join(lines)


def format_plan_concise(result: dict[str, Any]) -> str:
    horizon = result.get("planning_horizon", 3)
    target_gws = result.get("target_gameweeks", [])
    gw_range = f"GW{target_gws[0]} - GW{target_gws[-1]}" if target_gws else f"{horizon} GWs"
    risk = result.get("risk_profile", "neutral")
    risk_label = f" [Risk: {risk}]" if risk != "neutral" else ""
    bank_init = result.get("bank_initial_fmt", "£0.0m")
    ft_init = result.get("free_transfers_initial", 1)

    best_plan = result.get("best_plan")
    if not best_plan:
        return "No viable transfer plan found."

    tot_net = best_plan.get("total_net_xp", 0.0)
    tot_floor = best_plan.get("total_floor_xp", 0.0)
    tot_ceil = best_plan.get("total_ceiling_xp", 0.0)
    tot_hits = best_plan.get("total_hits", 0)

    lines = [
        f"Multi-Gameweek Transfer Roadmap ({gw_range}){risk_label} | Bank: {bank_init} | FT: {ft_init}",
        f"Optimal Plan (#1): {tot_net:.1f} Net xP [Floor: {tot_floor:.1f}, Ceil: {tot_ceil:.1f}] | Total Hits: -{tot_hits}pt",
        "",
        "Gameweek Schedule:",
    ]

    for step in best_plan.get("gameweek_steps", []):
        gw = step.get("gameweek")
        hits = step.get("transfer_hits", 0)
        net_xp = step.get("net_xp", 0.0)
        l_xp = step.get("lineup_xp", 0.0)
        floor_xp = step.get("lineup_floor", 0.0)
        ceil_xp = step.get("lineup_ceiling", 0.0)
        cap = step.get("captain", {})
        bank_after = step.get("bank_after_fmt", "")
        ft_after = step.get("free_transfers_after", 1)
        form = step.get("formation", "3-5-2")

        tx_list = step.get("transfers", [])
        if not tx_list:
            tx_desc = "None (Roll free transfer)"
            action_desc = "ROLL TRANSFER"
        else:
            tx_desc = ", ".join(f"{t['out']['name']} -> {t['in']['name']}" for t in tx_list)
            hit_suffix = f" (-{hits}pt hit)" if hits > 0 else " (Free)"
            action_desc = f"{len(tx_list)} TRANSFER{'S' if len(tx_list) > 1 else ''}{hit_suffix}"

        lines.append(f"  GW{gw}: {action_desc}")
        lines.append(f"       Move: {tx_desc}")
        lines.append(
            f"       Lineup: {l_xp:.1f} xP [Floor: {floor_xp:.1f}, Ceil: {ceil_xp:.1f}] | Net: {net_xp:.1f} xP | Form: {form} | Cap: {cap.get('name', 'N/A')} ({cap.get('xp', 0.0):.1f} xP)"
        )
        lines.append(f"       Bank Remaining: {bank_after} | Free Transfers Banked for next GW: {ft_after}")
        lines.append("")

    alt_plans = result.get("alternative_plans", [])
    if alt_plans:
        lines.append("Alternative Strategic Trajectories:")
        for p in alt_plans[:3]:
            rank = p.get("rank")
            alt_net = p.get("total_net_xp", 0.0)
            alt_hits = p.get("total_hits", 0)
            summary_parts = []
            for s in p.get("gameweek_steps", []):
                s_gw = s.get("gameweek")
                n_tx = len(s.get("transfers", []))
                s_hits = s.get("transfer_hits", 0)
                hit_note = f" (-{s_hits}pt)" if s_hits > 0 else ""
                summary_parts.append(f"GW{s_gw}: {n_tx} FT{hit_note}" if n_tx > 0 else f"GW{s_gw}: Roll")
            traj_str = " -> ".join(summary_parts)
            lines.append(f"  Plan #{rank}: {alt_net:.1f} Net xP (Hits: -{alt_hits}pt) | {traj_str}")

    return "\n".join(lines)


def format_squad_concise(result: dict[str, Any]) -> str:
    fin = result.get("financials", {})
    state = result.get("state", {})
    players = result.get("players", [])

    header = (
        f"Current Squad ({result.get('season')}) | Bank: {fin.get('bank_fmt', '£0.0m')} | "
        f"Selling Value: {fin.get('squad_selling_value_fmt', '£0.0m')} | "
        f"Total Value: {fin.get('total_team_value_fmt', '£0.0m')} | FT: {state.get('free_transfers', 1)}"
    )

    by_pos: dict[str, list[str]] = {}
    for p in players:
        pos = p.get("position", "MIDFIELDER")
        by_pos.setdefault(pos, []).append(f"{p['name']} ({p['team']}, {p['selling_price_fmt']})")

    pos_lines = [f"  {pos}: " + ", ".join(by_pos[pos]) for pos in ("GOALKEEPER", "DEFENDER", "MIDFIELDER", "FORWARD") if pos in by_pos]
    return header + "\n" + "\n".join(pos_lines)


def format_validate_transfers_concise(result: dict[str, Any]) -> str:
    is_valid = result.get("is_valid", False)
    if is_valid:
        bank_tenths = result.get("bank_after_tenths", 0)
        bank_fmt = f"£{bank_tenths / 10:.1f}m" if bank_tenths is not None else "N/A"
        return f"Valid: True | Bank after: {bank_fmt} | Transfer hits: {result.get('transfer_hits', 0)}"
    else:
        errors = "; ".join(result.get("errors", []))
        return f"Valid: False | Errors: {errors}"


def format_fixtures_concise(result: dict[str, Any]) -> str:
    start_gw = result.get("start_gw")
    end_gw = result.get("end_gw")
    lines = [f"Upcoming Fixtures (GW{start_gw} - GW{end_gw}):"]

    if "team_rankings" in result:
        for t in result["team_rankings"]:
            lines.append(f"  {t['short_name']:3s}: {t['ticker']} | Avg FDR: {t['avg_difficulty']:.2f}")
    elif "squad_players" in result:
        for p in result["squad_players"]:
            lines.append(f"  {p['name']} ({p['team']}): {p['ticker']} | Avg FDR: {p['avg_difficulty']:.2f}")

    return "\n".join(lines)


def format_players_concise(result: dict[str, Any]) -> str:
    players = result.get("players", [])
    if not players:
        return "No players found matching query."
    lines = []
    for p in players:
        price_fmt = f"£{p['price_tenths'] / 10:.1f}m"
        lines.append(f"  ID: {p['id']:3d} | {p['name']} ({p['team']}) | Price: {price_fmt}")
    return "\n".join(lines)


def format_update_concise(result: dict[str, Any]) -> str:
    return (
        f"Updated snapshot #{result.get('snapshot_id')} ({result.get('fetched_at')}): "
        f"{result.get('players')} players, {result.get('fixtures')} fixtures."
    )


def format_report_concise(result: dict[str, Any]) -> str:
    return (
        f"Snapshot #{result.get('snapshot_id')} ({result.get('fetched_at')}): "
        f"{result.get('players')} players, {result.get('teams')} teams, {result.get('fixtures')} fixtures."
    )



def format_decision_concise(result: dict[str, Any]) -> str:
    gw = result.get("gameweek")
    season = result.get("season", "2026/27")
    cap = result.get("captain_name", "Unknown")
    vc = result.get("vice_captain_name", "Unknown")
    xp = result.get("predicted_lineup_xp", 0.0)
    floor = result.get("predicted_floor_xp", 0.0)
    ceil = result.get("predicted_ceiling_xp", 0.0)
    chip = result.get("chip_played") or "None"
    hits = result.get("transfer_hits", 0)
    actual = result.get("actual_points")
    actual_str = str(actual) if actual is not None else "Pending"
    notes = result.get("notes") or "None"

    return (
        f"Gameweek {gw} ({season}) Decision Log (ID #{result.get('decision_id')}):\n"
        f"  Captain: {cap} (C), Vice: {vc} (VC)\n"
        f"  Projected xP: {xp:.1f} (Floor: {floor:.1f}, Ceiling: {ceil:.1f})\n"
        f"  Chip: {chip} | Hits: {hits} (-{hits * 4} pts)\n"
        f"  Actual Score: {actual_str}\n"
        f"  Notes: {notes}"
    )


def format_decisions_list_concise(results: list[dict[str, Any]]) -> str:
    if not results:
        return "No decisions logged yet."
    lines = [
        f"{'GW':<5} | {'Chip':<10} | {'Hits':<5} | {'Captain':<15} | {'Pred xP':<8} | {'Actual':<8} | {'Date':<10}",
        "-" * 72,
    ]
    for r in results:
        gw_str = f"GW{r.get('gameweek')}"
        chip_str = r.get("chip_played") or "-"
        hits_str = str(r.get("transfer_hits", 0))
        cap_str = (r.get("captain_name") or f"ID {r.get('captain_id')}")[:15]
        xp_str = f"{r.get('predicted_lineup_xp', 0.0):.1f}"
        actual = r.get("actual_points")
        act_str = str(actual) if actual is not None else "-"
        date_str = (r.get("timestamp") or "")[:10]
        lines.append(f"{gw_str:<5} | {chip_str:<10} | {hits_str:<5} | {cap_str:<15} | {xp_str:<8} | {act_str:<8} | {date_str:<10}")
    return "\n".join(lines)



import sys


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(prog="fpl", description="Local-first FPL decision engine")
    parser.add_argument("-v", "--verbose", action="store_true", help="Output full detailed JSON payload")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("update", help="Download and persist the latest official FPL data")
    subcommands.add_parser("report", help="Write a machine-readable summary of the latest snapshot")
    subcommands.add_parser("squad", help="Generate a detailed analysis report of your current squad")
    subcommands.add_parser("squad-report", help="Alias for `fpl squad` command")

    fixtures_parser = subcommands.add_parser("fixtures", help="Analyze upcoming team fixtures and difficulty ratings (FDR)")
    fixtures_parser.add_argument("--gameweeks", type=int, default=5, help="Number of gameweeks to analyze (default: 5)")
    fixtures_parser.add_argument("--start-gw", type=int, default=None, help="Starting gameweek (default: next upcoming GW)")
    fixtures_parser.add_argument("--squad-only", action="store_true", help="Analyze fixtures only for players in your current squad")
    fixtures_parser.add_argument("--squad", type=Path, default=DEFAULT_SQUAD_PATH, help="Path to current_squad.json")

    suggest_parser = subcommands.add_parser("suggest-transfers", help="Generate legal 1- to 5-transfer move recommendations")
    suggest_parser.add_argument("--transfers", type=int, choices=[1, 2, 3, 4, 5], default=1, help="Number of transfers to evaluate (1 to 5, default: 1; optimized with branch-and-bound)")
    suggest_parser.add_argument("--squad", type=Path, default=DEFAULT_SQUAD_PATH, help="Path to current_squad.json")
    suggest_parser.add_argument("--max-results", type=int, default=15, help="Maximum number of suggestions to return (default: 15)")
    suggest_parser.add_argument("--gameweeks", type=int, default=5, help="Number of upcoming gameweeks for FDR evaluation (default: 5)")
    suggest_parser.add_argument("--risk", choices=["neutral", "floor", "ceiling"], default="neutral", help="Optimization risk profile: neutral (expected xP), floor (safe rank preservation), or ceiling (upside differential chasing)")

    options_parser = subcommands.add_parser("options", help="Alias for `fpl suggest-transfers`")
    options_parser.add_argument("--transfers", type=int, choices=[1, 2, 3, 4, 5], default=1, help="Number of transfers to evaluate (1 to 5, default: 1; optimized with branch-and-bound)")
    options_parser.add_argument("--squad", type=Path, default=DEFAULT_SQUAD_PATH, help="Path to current_squad.json")
    options_parser.add_argument("--max-results", type=int, default=15, help="Maximum number of suggestions to return (default: 15)")
    options_parser.add_argument("--gameweeks", type=int, default=5, help="Number of upcoming gameweeks for FDR evaluation (default: 5)")
    options_parser.add_argument("--risk", choices=["neutral", "floor", "ceiling"], default="neutral", help="Optimization risk profile: neutral (expected xP), floor (safe rank preservation), or ceiling (upside differential chasing)")

    for wc_cmd, wc_help in (
        ("wildcard", "Generate optimal 15-player squad (Wildcard) under budget and team limits"),
        ("free-hit", "Generate optimal 15-player squad (Free-Hit) under budget and team limits"),
    ):
        wc_p = subcommands.add_parser(wc_cmd, help=wc_help)
        wc_p.add_argument("--budget", type=float, default=None, help="Squad budget limit in millions (default: current squad value + bank)")
        wc_p.add_argument("--squad", type=Path, default=DEFAULT_SQUAD_PATH, help="Path to current_squad.json")
        wc_p.add_argument("--gameweeks", type=int, default=5, help="Number of upcoming gameweeks to evaluate (default: 5)")
        wc_p.add_argument("--risk", choices=["neutral", "floor", "ceiling"], default="neutral", help="Optimization risk profile: neutral, floor, or ceiling")
        wc_p.add_argument("--output", type=Path, default=WILDCARD_REPORT_PATH, help="Output path for JSON report")

    plan_parser = subcommands.add_parser("plan", help="Generate multi-gameweek transfer planning roadmap (3-5 gameweeks)")
    plan_parser.add_argument("--horizon", type=int, default=3, help="Planning horizon in gameweeks (default: 3, up to 6)")
    plan_parser.add_argument("--squad", type=Path, default=DEFAULT_SQUAD_PATH, help="Path to current_squad.json")
    plan_parser.add_argument("--start-gw", type=int, default=None, help="Starting gameweek (default: next upcoming GW)")
    plan_parser.add_argument("--risk", choices=["neutral", "floor", "ceiling"], default="neutral", help="Optimization risk profile: neutral, floor, or ceiling")
    plan_parser.add_argument("--no-hits", action="store_true", help="Disallow transfer hits (only execute zero-hit moves and rolled transfers)")
    plan_parser.add_argument("--output", type=Path, default=PLAN_REPORT_PATH, help="Output path for JSON plan artifact")

    for cmd_name, cmd_help in (
        ("lineup", "Optimize legal starting 11, captaincy, and bench ordering based on xP"),
        ("starting-xi", "Alias for `fpl lineup` command"),
        ("captain", "Alias for `fpl lineup` command"),
    ):
        cmd_p = subcommands.add_parser(cmd_name, help=cmd_help)
        cmd_p.add_argument("--squad", type=Path, default=DEFAULT_SQUAD_PATH, help="Path to current_squad.json")
        cmd_p.add_argument("--gameweek", type=int, default=None, help="Target gameweek (default: next upcoming GW)")

    players_parser = subcommands.add_parser("players", help="Find player IDs in the latest FPL snapshot")
    players_parser.add_argument("--search", required=True, help="Part of a player's displayed name")
    import_parser = subcommands.add_parser("import-squad", help="Automatically populate current_squad.json from a players.txt file")
    import_parser.add_argument("--players", type=Path, default=DEFAULT_PLAYERS_PATH, help="Path to players text file")
    import_parser.add_argument("--squad", type=Path, default=DEFAULT_SQUAD_PATH, help="Path to current_squad.json")
    validate_parser = subcommands.add_parser("validate-transfers", help="Validate proposed transfers against the local squad state")
    validate_parser.add_argument("--squad", type=Path, default=DEFAULT_SQUAD_PATH, help="Private current-squad JSON path")
    validate_parser.add_argument("-n", "--by-name", action="store_true", help="Resolve transfers by player name queries instead of integer IDs")
    validate_parser.add_argument("--transfer", action="append", required=True, help="Transfer as OUTGOING:INCOMING; repeat for multiple moves")
    log_dec_parser = subcommands.add_parser("log-decision", help="Record and freeze gameweek lineup and transfer decisions in audit trail")
    log_dec_parser.add_argument("--squad", type=Path, default=DEFAULT_SQUAD_PATH, help="Path to current_squad.json")
    log_dec_parser.add_argument("--gameweek", type=int, default=None, help="Target gameweek (default: current gameweek)")
    log_dec_parser.add_argument("--chip", choices=["wildcard", "freehit", "benchboost", "triplecaptain"], default=None, help="Chip played this gameweek")
    log_dec_parser.add_argument("--hits", type=int, default=0, help="Number of transfer hits taken (4 pts each)")
    log_dec_parser.add_argument("--notes", type=str, default="", help="Optional manager reasoning/decision notes")
    log_dec_parser.add_argument("--actual-points", type=int, default=None, help="Actual points scored (for post-matchday finalization)")
    log_dec_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing decision log for this gameweek")

    decisions_parser = subcommands.add_parser("decisions", help="Review past gameweek decisions and audit trail")
    decisions_parser.add_argument("--gameweek", type=int, default=None, help="View specific gameweek decision")
    decisions_parser.add_argument("--season", type=str, default="2026/27", help="Filter by season (default: 2026/27)")

    arguments = parser.parse_args()

    try:
        if arguments.command == "update":
            result = update()
            print(json.dumps(result, indent=2, ensure_ascii=False) if arguments.verbose else format_update_concise(result))
        elif arguments.command == "report":
            result = report()
            print(json.dumps(result, indent=2, ensure_ascii=False) if arguments.verbose else format_report_concise(result))
        elif arguments.command in ("squad", "squad-report"):
            squad_path = getattr(arguments, "squad", DEFAULT_SQUAD_PATH)
            result = generate_squad_report(squad_path=squad_path, database_path=DATABASE_PATH, report_path=SQUAD_REPORT_PATH)
            print(json.dumps(result, indent=2, ensure_ascii=False) if arguments.verbose else format_squad_concise(result))
        elif arguments.command == "fixtures":
            if arguments.squad_only:
                result = analyze_squad_fixtures(
                    squad_path=arguments.squad,
                    database_path=DATABASE_PATH,
                    num_gameweeks=arguments.gameweeks,
                    start_gw=arguments.start_gw,
                )
            else:
                result = analyze_team_fixtures(
                    database_path=DATABASE_PATH,
                    num_gameweeks=arguments.gameweeks,
                    start_gw=arguments.start_gw,
                )
            print(json.dumps(result, indent=2, ensure_ascii=False) if arguments.verbose else format_fixtures_concise(result))
        elif arguments.command in ("suggest-transfers", "options"):
            squad_path = getattr(arguments, "squad", DEFAULT_SQUAD_PATH)
            result = suggest_transfers(
                num_transfers=arguments.transfers,
                squad_path=squad_path,
                database_path=DATABASE_PATH,
                max_results=arguments.max_results,
                num_gameweeks=arguments.gameweeks,
                risk_profile=getattr(arguments, "risk", "neutral"),
                report_path=TRANSFERS_REPORT_PATH,
            )
            print(json.dumps(result, indent=2, ensure_ascii=False) if arguments.verbose else format_suggest_transfers_concise(result))
        elif arguments.command in ("wildcard", "free-hit"):
            squad_path = getattr(arguments, "squad", DEFAULT_SQUAD_PATH)
            result = suggest_wildcard(
                budget_millions=getattr(arguments, "budget", None),
                squad_path=squad_path,
                database_path=DATABASE_PATH,
                num_gameweeks=arguments.gameweeks,
                risk_profile=getattr(arguments, "risk", "neutral"),
                report_path=getattr(arguments, "output", WILDCARD_REPORT_PATH),
            )
            print(json.dumps(result, indent=2, ensure_ascii=False) if arguments.verbose else format_wildcard_concise(result))
        elif arguments.command == "plan":
            squad_path = getattr(arguments, "squad", DEFAULT_SQUAD_PATH)
            result = generate_multi_gameweek_plan(
                squad_path=squad_path,
                database_path=DATABASE_PATH,
                horizon=arguments.horizon,
                start_gw=arguments.start_gw,
                risk_profile=getattr(arguments, "risk", "neutral"),
                allow_hits=not arguments.no_hits,
                report_path=getattr(arguments, "output", PLAN_REPORT_PATH),
            )
            print(json.dumps(result, indent=2, ensure_ascii=False) if arguments.verbose else format_plan_concise(result))
        elif arguments.command in ("lineup", "starting-xi", "captain"):
            squad_path = getattr(arguments, "squad", DEFAULT_SQUAD_PATH)
            gameweek = getattr(arguments, "gameweek", None)
            result = select_starting_lineup(
                squad_path=squad_path,
                database_path=DATABASE_PATH,
                gameweek=gameweek,
                report_path=LINEUP_REPORT_PATH,
            )
            print(json.dumps(result, indent=2, ensure_ascii=False) if arguments.verbose else format_lineup_concise(result))
        elif arguments.command == "players":
            result = {"players": SnapshotStore(DATABASE_PATH).search_latest_players(arguments.search)}
            print(json.dumps(result, indent=2, ensure_ascii=False) if arguments.verbose else format_players_concise(result))
        elif arguments.command == "import-squad":
            import_squad_from_file(players_path=arguments.players, squad_path=arguments.squad)
        elif arguments.command == "log-decision":
            squad_path = getattr(arguments, "squad", DEFAULT_SQUAD_PATH)
            if arguments.actual_points is not None:
                gw = arguments.gameweek
                if gw is None:
                    from .fixtures import get_current_gameweek
                    gw = get_current_gameweek(SnapshotStore(DATABASE_PATH))
                existing = get_gameweek_decision(gw, database_path=DATABASE_PATH)
                if existing is not None:
                    result = record_actual_gameweek_score(gw, arguments.actual_points, database_path=DATABASE_PATH)
                else:
                    log_decision_from_current_squad(
                        gameweek=gw,
                        squad_path=squad_path,
                        database_path=DATABASE_PATH,
                        chip_played=arguments.chip,
                        transfer_hits=arguments.hits,
                        notes=arguments.notes,
                        overwrite=arguments.overwrite,
                    )
                    result = record_actual_gameweek_score(gw, arguments.actual_points, database_path=DATABASE_PATH)
            else:
                result = log_decision_from_current_squad(
                    gameweek=arguments.gameweek,
                    squad_path=squad_path,
                    database_path=DATABASE_PATH,
                    chip_played=arguments.chip,
                    transfer_hits=arguments.hits,
                    notes=arguments.notes,
                    overwrite=arguments.overwrite,
                )
            print(json.dumps(result, indent=2, ensure_ascii=False) if arguments.verbose else format_decision_concise(result))
        elif arguments.command == "decisions":
            if arguments.gameweek is not None:
                result = get_gameweek_decision(arguments.gameweek, season=arguments.season, database_path=DATABASE_PATH)
                if result is None:
                    print(f"No decision logged for {arguments.season} GW{arguments.gameweek}.")
                else:
                    print(json.dumps(result, indent=2, ensure_ascii=False) if arguments.verbose else format_decision_concise(result))
            else:
                decisions_list = list_decisions(season=arguments.season, database_path=DATABASE_PATH)
                print(json.dumps({"decisions": decisions_list}, indent=2, ensure_ascii=False) if arguments.verbose else format_decisions_list_concise(decisions_list))
        elif arguments.command == "validate-transfers":
            result = validate_transfer_set(arguments.squad, arguments.transfer, by_name=arguments.by_name)
            print(json.dumps(result, indent=2, ensure_ascii=False) if arguments.verbose else format_validate_transfers_concise(result))
        else:
            parser.print_help()
    except (RuntimeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()

