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
from ..planner import generate_multi_gameweek_plan
from ..scores import update_gameweek_scores
from ..squad_report import generate_squad_report
from ..storage import SnapshotStore
from ..suggest_transfers import suggest_transfers, suggest_wildcard
from ..transfers import execute_transfers
from ..teams import (
    create_team,
    delete_team,
    get_active_squad_path,
    get_active_team_id,
    get_team,
    get_team_squad_path,
    list_teams,
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

    def _send_error_json(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message, "success": False}, status=status)

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
                self._send_json({"status": "ok", "version": "0.5.0-dev"})
            elif path == "/api/teams":
                teams_data = list_teams(self.config_dir)
                active_id = get_active_team_id(self.config_dir)
                self._send_json({"teams": teams_data, "active_team_id": active_id})
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
                    try:
                        from ..squad_state import load_current_squad
                        state_obj = load_current_squad(squad_path)
                        gw = state_obj.gameweek or get_current_gameweek(SnapshotStore(self.database_path))
                    except Exception:
                        gw = get_current_gameweek(SnapshotStore(self.database_path))

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
                squad_path = get_team_squad_path(tid, self.config_dir)
                rep = suggest_transfers(
                    num_transfers=num_tx,
                    squad_path=squad_path,
                    database_path=self.database_path,
                    num_gameweeks=gws,
                    risk_profile=risk,
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
            elif path == "/api/transfers/execute":
                tid = body.get("team_id") or get_active_team_id(self.config_dir)
                tx_list = body.get("transfers", [])
                if not tx_list:
                    raise ValueError("Field 'transfers' is required.")
                squad_path = get_team_squad_path(tid, self.config_dir)
                gw_val = body.get("gameweek")
                result = execute_transfers(
                    squad_path=squad_path,
                    transfers=tx_list,
                    database_path=self.database_path,
                    gameweek=int(gw_val) if gw_val is not None else None,
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
            elif path == "/api/update-data":
                from ..cli import update
                res = update()
                self._send_json(res)
            elif path == "/api/update-scores":
                gw = body.get("gameweek")
                if gw is not None:
                    gw = int(gw)
                else:
                    from ..fixtures import get_current_gameweek
                    gw = get_current_gameweek(SnapshotStore(self.database_path))
                res = update_gameweek_scores(gameweek=gw, database_path=self.database_path)
                self._send_json(res)
            else:
                self._send_error_json("Unknown endpoint", status=404)
        except Exception as err:
            self._send_error_json(str(err), status=400)

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

    def _serve_static(self, req_path: str) -> None:
        clean = req_path.lstrip("/")
        target = self.static_dir / clean if clean else self.static_dir / "index.html"

        if not target.exists() or target.is_dir():
            target = self.static_dir / "index.html"

        if not target.exists():
            self._send_error_json("Static GUI files not found.", status=404)
            return

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
    print(f"  FPL Manager Interactive Dashboard (V0.5)")
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
