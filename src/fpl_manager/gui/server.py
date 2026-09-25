"""Lightweight, zero-external-dependency HTTP server and REST API for the FPL Manager GUI."""

import json
import mimetypes
import os
import socket
import sys
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .. import __version__
from ..briefing import generate_manager_briefing
from ..chip_strategy import recommend_chip_strategy
from ..decision_log import (
    apply_wildcard_or_freehit,
    get_gameweek_decision,
    list_decisions,
    log_decision_from_current_squad,
    record_actual_gameweek_score,
    undo_gameweek_changes,
)
from ..evaluation import evaluate_gameweek_decision, evaluate_season_decisions
from ..fixtures import get_current_gameweek
from ..lineup import build_logged_lineup, select_starting_lineup
from ..live_matchday import get_live_gameweek_matchday_summary
from ..llm_advisor import generate_llm_advisory
from ..models import Position
from ..planner import generate_multi_gameweek_plan
from ..scores import update_gameweek_scores
from ..squad_report import generate_squad_report
from ..storage import SnapshotStore
from ..strategic_squad import (
    STRATEGIC_MODES,
    STRATEGIC_PROFILES,
    StrategicCandidate,
    StrategicConstraints,
    analyze_constraint_impact,
    generate_strategic_candidates,
    reoptimize_strategic_squad,
    solve_strategic_squad,
)
from ..suggest_transfers import (
    load_all_players_meta,
    suggest_initial_squad,
    suggest_strategic_squad,
    suggest_transfers,
    suggest_wildcard,
)
from ..transfers import execute_transfers, selling_price
from ..teams import (
    create_team,
    delete_team,
    get_active_squad_path,
    get_active_team_id,
    get_team,
    get_team_squad_path,
    list_teams,
    rename_team,
    set_active_team,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "fpl.sqlite3"
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"
STATIC_DIR = Path(__file__).resolve().parent / "static"


class FPLRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler providing REST API endpoints and static file serving."""

    database_path: Path = DEFAULT_DB_PATH
    config_dir: Path = DEFAULT_CONFIG_DIR
    static_dir: Path = STATIC_DIR

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress standard HTTP server access logs unless debug mode is active."""
        if os.environ.get("FPL_DEBUG_HTTP"):
            super().log_message(format, *args)

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, indent=2, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, status: int = 400, error_type: str | None = None) -> None:
        payload = {"error": message, "success": False, "status": "error"}
        if error_type:
            payload["error_type"] = error_type
        self._send_json(payload, status=status)

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length).decode("utf-8")
        try:
            return json.loads(raw)
        except Exception as err:
            raise ValueError(f"Malformed JSON body: {err}") from err

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query)

        def get_arg(name: str, default: Any = None) -> Any:
            vals = query.get(name)
            return vals[0] if vals else default

        try:
            # API Endpoints
            if path == "/api/health":
                self._send_json({"status": "ok", "version": __version__})
            elif path in ("/api/gameweek", "/api/current-gameweek"):
                from contextlib import closing
                store = SnapshotStore(self.database_path)
                curr_gw = get_current_gameweek(store)
                with closing(store._connect()) as conn:
                    snap = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
                    snap_id = snap[0] if snap else 1
                    fin_row = conn.execute(
                        "SELECT MAX(event) FROM fixtures WHERE snapshot_id = ? AND finished = 1 AND event IS NOT NULL",
                        (snap_id,),
                    ).fetchone()
                    latest_fin = int(fin_row[0]) if fin_row and fin_row[0] is not None else 0
                self._send_json({
                    "current_gameweek": curr_gw,
                    "latest_finished_gameweek": latest_fin,
                })
            elif path == "/api/teams":
                teams_data = list_teams(self.config_dir, database_path=self.database_path)
                active_id = get_active_team_id(self.config_dir)
                curr_gw = get_current_gameweek(SnapshotStore(self.database_path))
                self._send_json({
                    "teams": teams_data,
                    "active_team_id": active_id,
                    "current_gameweek": curr_gw,
                    "version": __version__,
                })
            elif path.startswith("/api/teams/") and len(path.split("/")) == 4:
                tid = path.split("/")[3]
                team_info = get_team(tid, self.config_dir)
                payload = dict(team_info["metadata"])
                payload["state"] = {
                    "gameweek": team_info["state"].gameweek,
                    "bank_tenths": team_info["state"].bank_tenths,
                    "free_transfers": team_info["state"].free_transfers,
                    "player_ids": team_info["state"].player_ids,
                    "chips_remaining": team_info["state"].chips_remaining,
                    "purchase_prices_tenths": team_info["state"].purchase_prices_tenths,
                }
                self._send_json(payload)
            elif path == "/api/squad":
                tid = get_arg("team") or get_active_team_id(self.config_dir)
                gw_arg = get_arg("gameweek")
                gw = int(gw_arg) if gw_arg else None
                squad_path = get_team_squad_path(tid, self.config_dir)
                rep = generate_squad_report(
                    squad_path=squad_path,
                    database_path=self.database_path,
                    gameweek=gw,
                    team_id=tid,
                )
                rep["team_id"] = tid
                if rep.get("gameweek") is None:
                    rep["gameweek"] = get_current_gameweek(SnapshotStore(self.database_path))
                self._send_json(rep)
            elif path == "/api/lineup":
                tid = get_arg("team") or get_active_team_id(self.config_dir)
                gw_arg = get_arg("gameweek")
                gw = int(gw_arg) if gw_arg else None
                mode = get_arg("mode", "auto")
                season = get_arg("season", "2026/27")

                squad_path = get_team_squad_path(tid, self.config_dir)
                if gw is None:
                    curr_gw = get_current_gameweek(SnapshotStore(self.database_path))
                    try:
                        from ..squad_state import load_current_squad
                        state_obj = load_current_squad(squad_path)
                        gw = state_obj.gameweek if (state_obj.gameweek and state_obj.gameweek >= curr_gw) else curr_gw
                    except Exception:
                        gw = curr_gw

                decision = None
                if mode != "model":
                    decision = get_gameweek_decision(gw, season=season, team_id=tid, database_path=self.database_path)

                if decision is not None and mode != "model":
                    rep = build_logged_lineup(decision, database_path=self.database_path)
                else:
                    rep = select_starting_lineup(squad_path=squad_path, database_path=self.database_path, gameweek=gw)
                    rep["is_logged"] = False
                    existing_dec = get_gameweek_decision(gw, season=season, team_id=tid, database_path=self.database_path)
                    rep["has_logged_decision"] = existing_dec is not None

                rep["team_id"] = tid
                self._send_json(rep)
            elif path == "/api/transfers":
                tid = get_arg("team")
                num_tx = int(get_arg("transfers", 1))
                gws = int(get_arg("gameweeks", 5))
                risk = get_arg("risk", "neutral")
                gw_param = get_arg("gameweek") or get_arg("gw")
                gw_val = int(gw_param) if gw_param else None
                squad_path = get_team_squad_path(tid, self.config_dir)
                rep = suggest_transfers(
                    num_transfers=num_tx,
                    squad_path=squad_path,
                    database_path=self.database_path,
                    num_gameweeks=gws,
                    risk_profile=risk,
                    gameweek=gw_val,
                )
                rep["team_id"] = tid or get_active_team_id(self.config_dir)
                self._send_json(rep)
            elif path == "/api/wildcard":
                tid = get_arg("team")
                budget_arg = get_arg("budget")
                budget = float(budget_arg) if budget_arg else None
                gws = int(get_arg("gameweeks", 5))
                risk = get_arg("risk", "neutral")
                squad_path = get_team_squad_path(tid, self.config_dir)
                rep = suggest_wildcard(
                    budget_millions=budget,
                    squad_path=squad_path,
                    database_path=self.database_path,
                    num_gameweeks=gws,
                    risk_profile=risk,
                )
                rep["team_id"] = tid or get_active_team_id(self.config_dir)
                self._send_json(rep)
            elif path == "/api/strategic-squad/config":
                tid = get_arg("team") or get_active_team_id(self.config_dir)
                store = SnapshotStore(self.database_path)
                current_gw = get_current_gameweek(store)
                team_info = get_team(tid, self.config_dir)

                players_map, _ = load_all_players_meta(store)
                player_list = [
                    {
                        "id": p.id,
                        "name": p.name,
                        "position": p.position.name,
                        "pos_abbr": {
                            Position.GOALKEEPER: "GKP",
                            Position.DEFENDER: "DEF",
                            Position.MIDFIELDER: "MID",
                            Position.FORWARD: "FWD",
                        }.get(p.position, "MID"),
                        "team": p.team_short,
                        "team_id": p.team_id,
                        "price_fmt": f"£{p.price_tenths / 10:.1f}m",
                        "price_tenths": p.price_tenths,
                        "expected_points": getattr(p, "expected_points", 0.0),
                        "status": getattr(p, "status", "a"),
                    }
                    for p in sorted(players_map.values(), key=lambda x: (x.position.value, -x.total_points))
                ]

                self._send_json({
                    "modes": list(STRATEGIC_MODES),
                    "strategies": list(STRATEGIC_PROFILES),
                    "default_horizons": [1, 2, 3, 4, 5, 6, 7, 8],
                    "current_gameweek": current_gw,
                    "active_team": team_info,
                    "players": player_list,
                })
            elif path == "/api/strategic-squad":
                tid = get_arg("team")
                mode = get_arg("mode", "initial")
                horizon = int(get_arg("horizon", 5))
                strategy = get_arg("strategy", "balanced")
                budget_arg = get_arg("budget")
                budget = float(budget_arg) if budget_arg else None
                locks_raw = get_arg("lock") or get_arg("locks")
                locks = [int(i.strip()) for i in locks_raw.split(",") if i.strip()] if locks_raw else []
                excl_raw = get_arg("exclude") or get_arg("excludes")
                excl = [int(i.strip()) for i in excl_raw.split(",") if i.strip()] if excl_raw else []
                pref_raw = get_arg("prefer") or get_arg("prefers")
                pref = [int(i.strip()) for i in pref_raw.split(",") if i.strip()] if pref_raw else []
                squad_path = get_team_squad_path(tid, self.config_dir)

                rep = suggest_strategic_squad(
                    mode=mode,
                    budget_millions=budget,
                    squad_path=squad_path,
                    database_path=self.database_path,
                    num_gameweeks=horizon,
                    strategy=strategy,
                    locked_player_ids=locks,
                    excluded_player_ids=excl,
                    preferred_player_ids=pref,
                    generate_all_candidates=True,
                )
                rep["team_id"] = tid or get_active_team_id(self.config_dir)
                self._send_json(rep)
            elif path == "/api/plan":
                tid = get_arg("team")
                horizon = int(get_arg("horizon", 3))
                start_gw = int(get_arg("start_gw")) if get_arg("start_gw") else None
                risk = get_arg("risk", "neutral")
                no_hits = get_arg("no_hits", "false").lower() in ("true", "1", "yes")
                squad_path = get_team_squad_path(tid, self.config_dir)
                rep = generate_multi_gameweek_plan(
                    squad_path=squad_path,
                    database_path=self.database_path,
                    horizon=horizon,
                    start_gw=start_gw,
                    risk_profile=risk,
                    allow_hits=not no_hits,
                )
                rep["team_id"] = tid or get_active_team_id(self.config_dir)
                self._send_json(rep)
            elif path == "/api/chips":
                tid = get_arg("team")
                start_gw = int(get_arg("start_gw")) if get_arg("start_gw") else None
                end_gw = int(get_arg("end_gw")) if get_arg("end_gw") else None
                used_chips_raw = get_arg("used_chips")
                used_list = [c.strip() for c in used_chips_raw.split(",")] if used_chips_raw else None
                squad_path = get_team_squad_path(tid, self.config_dir)
                rep = recommend_chip_strategy(
                    squad_path=squad_path,
                    database_path=self.database_path,
                    start_gw=start_gw,
                    end_gw=end_gw,
                    used_chips=used_list,
                    team_id=tid,
                )
                rep["team_id"] = tid or get_active_team_id(self.config_dir)
                self._send_json(rep)
            elif path == "/api/decisions":
                tid = get_arg("team") or get_active_team_id(self.config_dir)
                season = get_arg("season", "2026/27")
                gw_arg = get_arg("gameweek")
                if gw_arg:
                    gw = int(gw_arg)
                    dec = get_gameweek_decision(gameweek=gw, team_id=tid, season=season, database_path=self.database_path)
                    self._send_json({"decision": dec, "team_id": tid})
                else:
                    decisions = list_decisions(team_id=tid, season=season, database_path=self.database_path)
                    self._send_json({"decisions": decisions, "team_id": tid})
            elif path == "/api/evaluate":
                tid = get_arg("team") or get_active_team_id(self.config_dir)
                season = get_arg("season", "2026/27")
                gw_arg = get_arg("gameweek")
                if gw_arg:
                    gw = int(gw_arg)
                    rep = evaluate_gameweek_decision(gameweek=gw, team_id=tid, season=season, database_path=self.database_path)
                else:
                    rep = evaluate_season_decisions(team_id=tid, season=season, database_path=self.database_path)
                self._send_json(rep)
            elif path == "/api/players":
                search = get_arg("search", "")
                all_flag = str(get_arg("all", "false")).lower() in ("true", "1", "yes")
                store = SnapshotStore(self.database_path)
                matches = store.search_latest_players("" if all_flag else search) if (search or all_flag) else []
                self._send_json({"players": matches})
            elif path == "/api/player":
                pid = int(get_arg("id") or get_arg("player_id", 0))
                gw_arg = get_arg("gameweek")
                gw = int(gw_arg) if gw_arg else None
                store = SnapshotStore(self.database_path)
                details = store.get_player_details(pid, gameweek=gw)
                self._send_json(details)
            elif path == "/api/briefing":
                tid = get_arg("team") or get_active_team_id(self.config_dir)
                gw_arg = get_arg("gameweek")
                gw = int(gw_arg) if gw_arg else None
                squad_path = get_team_squad_path(tid, self.config_dir)
                rep = generate_manager_briefing(
                    squad_path=squad_path,
                    gameweek=gw,
                    team_id=tid,
                    database_path=self.database_path,
                )
                self._send_json(rep)
            elif path == "/api/live":
                tid = get_arg("team") or get_active_team_id(self.config_dir)
                gw_arg = get_arg("gameweek")
                gw = int(gw_arg) if gw_arg else None
                force = str(get_arg("force", "false")).lower() in ("true", "1", "yes")
                squad_path = get_team_squad_path(tid, self.config_dir)
                rep = get_live_gameweek_matchday_summary(
                    gameweek=gw,
                    squad_path=squad_path,
                    team_id=tid,
                    database_path=self.database_path,
                    force_fetch=force,
                )
                self._send_json(rep)
            elif path == "/api/advise":
                tid = get_arg("team") or get_active_team_id(self.config_dir)
                gw_arg = get_arg("gameweek")
                gw = int(gw_arg) if gw_arg else None
                persona = get_arg("persona", "devil_advocate")
                provider = get_arg("provider", "auto")
                api_key = get_arg("api_key")
                model = get_arg("model")
                squad_path = get_team_squad_path(tid, self.config_dir)
                rep = generate_llm_advisory(
                    gameweek=gw,
                    squad_path=squad_path,
                    database_path=self.database_path,
                    persona=persona,
                    provider=provider,
                    api_key=api_key,
                    model=model,
                )
                self._send_json(rep)
            else:
                # Static file serving fallback
                self._serve_static(path)
        except Exception as err:
            self._send_error_json(str(err), status=500)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        try:
            body = self._read_json_body()

            if path == "/api/teams/switch":
                tid = body.get("team_id")
                if not tid:
                    raise ValueError("Field 'team_id' is required.")
                result = set_active_team(tid, self.config_dir)
                self._send_json(result)
            elif path == "/api/teams/create":
                name = body.get("name")
                if not name:
                    raise ValueError("Field 'name' is required.")
                tid = body.get("team_id")
                manager = body.get("manager", "")
                copy_from = body.get("copy_from")
                activate = body.get("activate", True)
                result = create_team(
                    name=name,
                    team_id=tid,
                    manager=manager,
                    copy_from_team_id=copy_from,
                    set_as_active=activate,
                    config_dir=self.config_dir,
                )
                self._send_json(result)
            elif path == "/api/teams/delete":
                tid = body.get("team_id")
                if not tid:
                    raise ValueError("Field 'team_id' is required.")
                result = delete_team(tid, self.config_dir)
                self._send_json(result)
            elif path == "/api/teams/rename" or (path.startswith("/api/teams/") and path.endswith("/rename")):
                if path.endswith("/rename") and path != "/api/teams/rename":
                    tid = path.split("/")[3]
                else:
                    tid = body.get("team_id") or get_active_team_id(self.config_dir)
                name = body.get("name")
                if not name or not str(name).strip():
                    raise ValueError("Field 'name' is required.")
                result = rename_team(tid, str(name).strip(), self.config_dir)
                self._send_json(result)
            elif path == "/api/transfers/execute":
                tid = body.get("team_id") or get_active_team_id(self.config_dir)
                tx_list = body.get("transfers", [])
                if not tx_list:
                    raise ValueError("Field 'transfers' is required.")
                squad_path = get_team_squad_path(tid, self.config_dir)
                gw_val = body.get("gameweek")
                chip_val = body.get("chip") or body.get("chip_played")
                result = execute_transfers(
                    squad_path=squad_path,
                    transfers=tx_list,
                    database_path=self.database_path,
                    gameweek=int(gw_val) if gw_val is not None else None,
                    chip_played=chip_val,
                )
                self._send_json(result)
            elif path == "/api/decisions":
                tid = body.get("team_id") or get_active_team_id(self.config_dir)
                gw = int(body["gameweek"])
                squad_path = get_team_squad_path(tid, self.config_dir)
                actual_points = body.get("actual_points")
                overwrite = body.get("overwrite", True)

                if actual_points is not None:
                    existing = get_gameweek_decision(gw, team_id=tid, database_path=self.database_path)
                    if existing is not None and not overwrite:
                        res = record_actual_gameweek_score(gw, actual_points, team_id=tid, database_path=self.database_path)
                    else:
                        log_decision_from_current_squad(
                            gameweek=gw,
                            squad_path=squad_path,
                            database_path=self.database_path,
                            team_id=tid,
                            squad_player_ids=body.get("squad_players"),
                            starting_player_ids=body.get("starters"),
                            bench_player_ids=body.get("bench"),
                            captain_id=body.get("captain"),
                            vice_captain_id=body.get("vice_captain"),
                            chip_played=body.get("chip"),
                            transfer_hits=body.get("hits"),
                            transfers=body.get("transfers"),
                            notes=body.get("notes", ""),
                            overwrite=overwrite,
                        )
                        res = record_actual_gameweek_score(gw, actual_points, team_id=tid, database_path=self.database_path)
                else:
                    res = log_decision_from_current_squad(
                        gameweek=gw,
                        squad_path=squad_path,
                        database_path=self.database_path,
                        team_id=tid,
                        squad_player_ids=body.get("squad_players"),
                        starting_player_ids=body.get("starters"),
                        bench_player_ids=body.get("bench"),
                        captain_id=body.get("captain"),
                        vice_captain_id=body.get("vice_captain"),
                        chip_played=body.get("chip"),
                        transfer_hits=body.get("hits"),
                        transfers=body.get("transfers"),
                        notes=body.get("notes", ""),
                        overwrite=overwrite,
                    )
                self._send_json(res)
            elif path == "/api/decisions/undo":
                tid = body.get("team_id") or get_active_team_id(self.config_dir)
                gw_val = body.get("gameweek")
                squad_path = get_team_squad_path(tid, self.config_dir)
                res = undo_gameweek_changes(
                    squad_path=squad_path,
                    gameweek=int(gw_val) if gw_val is not None else None,
                    team_id=tid,
                    season=body.get("season", "2026/27"),
                    database_path=self.database_path,
                )
                self._send_json(res)
            elif path == "/api/wildcard/apply":
                tid = body.get("team_id") or get_active_team_id(self.config_dir)
                gw_val = body.get("gameweek")
                gw = int(gw_val) if gw_val is not None else 1
                mode = body.get("mode", "wildcard")
                squad_ids = [int(i) for i in body.get("squad_ids", [])]
                starter_ids = [int(i) for i in body.get("starter_ids", [])]
                bench_ids = [int(i) for i in body.get("bench_ids", [])]
                cap_id = int(body.get("captain_id", starter_ids[0] if starter_ids else 0))
                vc_id = int(body.get("vice_captain_id", starter_ids[1] if len(starter_ids) > 1 else cap_id))
                bank_tenths = int(body.get("bank_tenths", 0))
                squad_path = get_team_squad_path(tid, self.config_dir)

                res = apply_wildcard_or_freehit(
                    squad_path=squad_path,
                    gameweek=gw,
                    mode=mode,
                    squad_ids=squad_ids,
                    starter_ids=starter_ids,
                    bench_ids=bench_ids,
                    captain_id=cap_id,
                    vice_captain_id=vc_id,
                    bank_tenths=bank_tenths,
                    team_id=tid,
                    season=body.get("season", "2026/27"),
                    database_path=self.database_path,
                )
                self._send_json(res)
            elif path == "/api/strategic-squad/optimize":
                tid = body.get("team_id") or get_active_team_id(self.config_dir)
                mode = body.get("mode", "initial")
                horizon = int(body.get("horizon", 5))
                strategy = body.get("strategy", "balanced")
                budget = float(body.get("budget")) if body.get("budget") is not None else None
                locked_ids = [int(i) for i in body.get("locked_player_ids", [])]
                excluded_ids = [int(i) for i in body.get("excluded_player_ids", [])]
                preferred_ids = [int(i) for i in body.get("preferred_player_ids", [])]
                squad_path = get_team_squad_path(tid, self.config_dir)

                try:
                    rep = suggest_strategic_squad(
                        mode=mode,
                        budget_millions=budget,
                        squad_path=squad_path,
                        database_path=self.database_path,
                        num_gameweeks=horizon,
                        strategy=strategy,
                        locked_player_ids=locked_ids,
                        excluded_player_ids=excluded_ids,
                        preferred_player_ids=preferred_ids,
                        generate_all_candidates=True,
                    )
                    rep["team_id"] = tid
                    self._send_json(rep)
                except ValueError as err:
                    self._send_json({"error": str(err), "error_type": "INFEASIBLE_CONSTRAINTS", "status": "error"}, status=400)
                except RuntimeError as err:
                    err_str = str(err)
                    err_type = "DATA_UNAVAILABLE" if "No FPL data" in err_str else "SOLVER_FAILURE"
                    self._send_json({"error": err_str, "error_type": err_type, "status": "error"}, status=400)
                except Exception as err:
                    self._send_json({"error": str(err), "error_type": "SOLVER_FAILURE", "status": "error"}, status=500)
            elif path == "/api/strategic-squad/reoptimize":
                tid = body.get("team_id") or get_active_team_id(self.config_dir)
                prev_cand_data = body.get("previous_candidate", {})
                mode = body.get("mode") or prev_cand_data.get("mode", "initial")
                horizon = int(body.get("horizon") or len(prev_cand_data.get("horizon_gws", [1, 2, 3, 4, 5])))
                strategy = body.get("strategy") or prev_cand_data.get("strategy", "balanced")
                budget = float(body.get("budget")) if body.get("budget") is not None else None
                locked_ids = [int(i) for i in body.get("locked_player_ids", [])]
                excluded_ids = [int(i) for i in body.get("excluded_player_ids", [])]
                preferred_ids = [int(i) for i in body.get("preferred_player_ids", [])]
                squad_path = get_team_squad_path(tid, self.config_dir)

                store = SnapshotStore(self.database_path)
                start_gw = get_current_gameweek(store)
                h_len = max(1, min(8, horizon))
                target_gws = list(range(start_gw, start_gw + h_len))
                from ..expected_points import project_multi_gameweek_profiles
                profiles_map = project_multi_gameweek_profiles(target_gws, database_path=self.database_path)
                players_map, _ = load_all_players_meta(store, profiles_map)

                if budget is not None:
                    budget_tenths = int(round(budget * 10))
                elif mode == "initial":
                    budget_tenths = 1000
                else:
                    try:
                        state = load_current_squad(squad_path)
                        squad_selling_value = sum(
                            selling_price(state.purchase_price(p_id), players_map[p_id].price_tenths)
                            for p_id in state.player_ids
                            if p_id in players_map
                        )
                        budget_tenths = state.bank_tenths + squad_selling_value
                    except Exception:
                        budget_tenths = 1000

                constraints = StrategicConstraints(
                    budget_tenths=budget_tenths,
                    locked_player_ids=set(locked_ids),
                    excluded_player_ids=set(excluded_ids),
                    preferred_player_ids=set(preferred_ids),
                    target_gameweeks=tuple(target_gws),
                )
                candidate_pool = list(players_map.values())
                new_cand = solve_strategic_squad(
                    candidate_pool=candidate_pool,
                    constraints=constraints,
                    strategy=strategy,
                    mode=mode,
                )

                if prev_cand_data and "player_ids" in prev_cand_data:
                    prev_cand = StrategicCandidate(
                        candidate_id=prev_cand_data.get("candidate_id", "prev"),
                        mode=prev_cand_data.get("mode", mode),
                        strategy=prev_cand_data.get("strategy", strategy),
                        total_objective_value=float(prev_cand_data.get("total_objective_value", 0.0)),
                        horizon_gws=prev_cand_data.get("horizon_gws", target_gws),
                        horizon_xp=float(prev_cand_data.get("horizon_xp", 0.0)),
                        horizon_breakdown=prev_cand_data.get("horizon_breakdown", {}),
                        start_gw_lineup_xp=float(prev_cand_data.get("start_gw_lineup_xp", 0.0)),
                        formation=prev_cand_data.get("formation", "3-4-3"),
                        total_cost_tenths=int(prev_cand_data.get("total_cost_tenths", 1000)),
                        bank_remaining_tenths=int(prev_cand_data.get("bank_remaining_tenths", 0)),
                        total_cost_fmt=prev_cand_data.get("total_cost_fmt", "£100.0m"),
                        bank_remaining_fmt=prev_cand_data.get("bank_remaining_fmt", "£0.0m"),
                        future_flexibility_score=float(prev_cand_data.get("future_flexibility_score", 50.0)),
                        fixture_ease_score=float(prev_cand_data.get("fixture_ease_score", 3.0)),
                        bench_value_score=float(prev_cand_data.get("bench_value_score", 0.0)),
                        captaincy_score=float(prev_cand_data.get("captaincy_score", 0.0)),
                        risk_score=float(prev_cand_data.get("risk_score", 0.0)),
                        starters=prev_cand_data.get("starters", []),
                        bench=prev_cand_data.get("bench", []),
                        captain=prev_cand_data.get("captain", {}),
                        vice_captain=prev_cand_data.get("vice_captain", {}),
                        squad=prev_cand_data.get("squad", []),
                        player_ids=prev_cand_data.get("player_ids", []),
                        locked_player_ids=prev_cand_data.get("locked_player_ids", []),
                        excluded_player_ids=prev_cand_data.get("excluded_player_ids", []),
                        preferred_player_ids=prev_cand_data.get("preferred_player_ids", []),
                        is_exact_global_optimum=prev_cand_data.get("is_exact_global_optimum", False),
                        algorithm=prev_cand_data.get("algorithm", ""),
                        search_metadata=prev_cand_data.get("search_metadata", {}),
                        provenance=prev_cand_data.get("provenance", {}),
                    )
                    impact = analyze_constraint_impact(prev_cand, new_cand)
                else:
                    impact = {"summary": "Re-optimization completed.", "opportunity_cost": 0.0, "objective_delta": 0.0}

                res = new_cand.to_dict()
                res["constraint_impact"] = impact
                self._send_json(res)
            elif path == "/api/strategic-squad/apply":
                tid = body.get("team_id") or get_active_team_id(self.config_dir)
                mode = body.get("mode", "initial")
                cand_data = body.get("candidate", {})
                squad_ids = [int(i) for i in cand_data.get("player_ids", body.get("squad_ids", []))]
                starter_ids = [int(p["id"]) for p in cand_data.get("starters", [])] or [int(i) for i in body.get("starter_ids", [])]
                bench_ids = [int(p["id"]) for p in cand_data.get("bench", [])] or [int(i) for i in body.get("bench_ids", [])]
                cap_id = int(cand_data.get("captain", {}).get("id") or (starter_ids[0] if starter_ids else 0))
                vc_id = int(cand_data.get("vice_captain", {}).get("id") or (starter_ids[1] if len(starter_ids) > 1 else cap_id))
                bank_tenths = int(cand_data.get("bank_remaining_tenths", body.get("bank_tenths", 0)))
                gw_val = body.get("gameweek")
                gw = int(gw_val) if gw_val is not None else 1
                squad_path = get_team_squad_path(tid, self.config_dir)

                res = apply_wildcard_or_freehit(
                    squad_path=squad_path,
                    gameweek=gw,
                    mode=mode,
                    squad_ids=squad_ids,
                    starter_ids=starter_ids,
                    bench_ids=bench_ids,
                    captain_id=cap_id,
                    vice_captain_id=vc_id,
                    bank_tenths=bank_tenths,
                    team_id=tid,
                    season=body.get("season", "2026/27"),
                    database_path=self.database_path,
                )
                self._send_json(res)
            elif path == "/api/update-data":
                from ..cli import update
                res = update()
                self._send_json(res)
            elif path == "/api/update-scores":
                gw = body.get("gameweek")
                if gw is not None:
                    gw = int(gw)
                else:
                    from contextlib import closing
                    store = SnapshotStore(self.database_path)
                    curr_gw = get_current_gameweek(store)
                    with closing(store._connect()) as conn:
                        snap = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
                        snap_id = snap[0] if snap else 1
                        started_row = conn.execute(
                            "SELECT COUNT(*) FROM fixtures WHERE snapshot_id = ? AND event = ? AND (finished = 1 OR kickoff_time <= datetime('now'))",
                            (snap_id, curr_gw),
                        ).fetchone()
                        started_count = started_row[0] if started_row else 0
                    if started_count > 0:
                        gw = curr_gw
                    else:
                        gw = max(1, curr_gw - 1)

                res = update_gameweek_scores(gameweek=gw, database_path=self.database_path)
                from ..scores import finalize_completed_gameweek_scores
                finalized = finalize_completed_gameweek_scores(database_path=self.database_path)
                res["finalized_decisions"] = finalized
                self._send_json(res)
            elif path == "/api/advise":
                tid = body.get("team_id") or get_active_team_id(self.config_dir)
                gw_val = body.get("gameweek")
                gw = int(gw_val) if gw_val is not None else None
                persona = body.get("persona", "devil_advocate")
                provider = body.get("provider", "auto")
                api_key = body.get("api_key")
                if isinstance(api_key, str):
                    api_key = api_key.strip() or None
                model = body.get("model")
                if isinstance(model, str):
                    model = model.strip() or None
                squad_path = get_team_squad_path(tid, self.config_dir)
                res = generate_llm_advisory(
                    gameweek=gw,
                    squad_path=squad_path,
                    database_path=self.database_path,
                    persona=persona,
                    provider=provider,
                    api_key=api_key,
                    model=model,
                )
                self._send_json(res)
            else:
                self._send_error_json("Unknown endpoint", status=404)
        except ValueError as err:
            err_str = str(err)
            err_type = "INFEASIBLE_CONSTRAINTS" if any(w in err_str.lower() for w in ("constraint", "budget", "quota", "locked", "exclude")) else "VALIDATION_ERROR"
            self._send_error_json(err_str, status=400, error_type=err_type)
        except RuntimeError as err:
            err_str = str(err)
            err_type = "DATA_UNAVAILABLE" if "No FPL data" in err_str else "SOLVER_FAILURE"
            self._send_error_json(err_str, status=400, error_type=err_type)
        except Exception as err:
            self._send_error_json(str(err), status=500, error_type="SOLVER_FAILURE")

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        try:
            if path.startswith("/api/teams/") and len(path.split("/")) == 4:
                tid = path.split("/")[3]
                result = delete_team(tid, self.config_dir)
                self._send_json(result)
            else:
                self._send_error_json("Endpoint not found", status=404)
        except Exception as err:
            self._send_error_json(str(err), status=400)

    def do_PATCH(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            body = {}

        try:
            if path.startswith("/api/teams/") and len(path.split("/")) == 4:
                tid = path.split("/")[3]
                name = body.get("name")
                if not name or not str(name).strip():
                    raise ValueError("Field 'name' is required.")
                result = rename_team(tid, str(name).strip(), self.config_dir)
                self._send_json(result)
            else:
                self._send_error_json("Endpoint not found", status=404)
        except Exception as err:
            self._send_error_json(str(err), status=400)

    def _serve_static(self, req_path: str) -> None:
        clean = req_path.lstrip("/")
        target = self.static_dir / clean if clean else self.static_dir / "index.html"

        if not target.exists() or target.is_dir():
            target = self.static_dir / "index.html"

        if not target.exists():
            self._send_error_json("Static GUI files not found.", status=404)
            return

        if target.name == "index.html":
            text = target.read_text(encoding="utf-8")
            import re
            text = re.sub(
                r'<span class="badge-version"[^>]*>.*?</span>',
                f'<span class="badge-version" id="app-version-badge">v{__version__}</span>',
                text,
            )
            content = text.encode("utf-8")
        else:
            content = target.read_bytes()

        mime_type, _ = mimetypes.guess_type(str(target))
        if mime_type is None:
            mime_type = "application/octet-stream"
        if mime_type.startswith("text/") or mime_type in ("application/javascript", "application/json"):
            mime_type += "; charset=utf-8"

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(content)


def find_available_port(host: str, starting_port: int, max_attempts: int = 10) -> int:
    """Find an available port starting from starting_port."""
    for port in range(starting_port, starting_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"Could not find an available port between {starting_port} and {starting_port + max_attempts - 1}.")


def create_gui_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    database_path: Path = DEFAULT_DB_PATH,
    config_dir: Path = DEFAULT_CONFIG_DIR,
    static_dir: Path = STATIC_DIR,
) -> tuple[ThreadingHTTPServer, int]:
    """Instantiate and configure the GUI ThreadingHTTPServer."""
    actual_port = find_available_port(host, port)

    # Automatically check gameweek and finalize completed decision scores at server startup
    try:
        from ..scores import finalize_completed_gameweek_scores
        finalize_completed_gameweek_scores(database_path=database_path)
    except Exception:
        pass

    try:
        from ..teams import sync_squad_with_current_gameweek, get_active_squad_path, get_active_team_id
        active_tid = get_active_team_id(config_dir)
        sq_path = get_active_squad_path(config_dir)
        if sq_path.exists():
            sync_squad_with_current_gameweek(sq_path, team_id=active_tid, config_dir=config_dir, database_path=database_path)
    except Exception:
        pass

    class CustomHandler(FPLRequestHandler):
        pass

    CustomHandler.database_path = database_path
    CustomHandler.config_dir = config_dir
    CustomHandler.static_dir = static_dir

    server = ThreadingHTTPServer((host, actual_port), CustomHandler)
    return server, actual_port


def start_gui_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
    database_path: Path = DEFAULT_DB_PATH,
    config_dir: Path = DEFAULT_CONFIG_DIR,
    static_dir: Path = STATIC_DIR,
) -> None:
    """Run the interactive FPL Manager GUI server until interrupted."""
    server, actual_port = create_gui_server(
        host=host,
        port=port,
        database_path=database_path,
        config_dir=config_dir,
        static_dir=static_dir,
    )
    url = f"http://{host}:{actual_port}"
    print(f"==================================================")
    print(f"  FPL Manager Interactive Dashboard (V{__version__})")
    print(f"  Local Server: {url}")
    print(f"  Press Ctrl+C to stop the server")
    print(f"==================================================")

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down FPL Manager GUI server...")
    finally:
        server.server_close()
