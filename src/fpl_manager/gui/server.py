"""Lightweight, zero-external-dependency HTTP server and REST API for the FPL Manager GUI."""

from datetime import datetime, timezone
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
from ..historical.reconstruction import reconstruct_features_and_project
from ..historical.snapshots import (
    analyze_historical_fixtures,
    build_historical_snapshot,
    load_historical_players_meta,
)
from ..historical.standings import (
    compute_historical_standings,
    get_historical_matchday_overview,
    get_historical_past_results,
    get_historical_upcoming_fixtures,
    get_live_matchday_overview,
)
from ..lineup import build_logged_lineup, select_starting_lineup
from ..live_matchday import get_live_gameweek_matchday_summary
from ..llm_advisor import generate_llm_advisory
from ..models import Position
from ..planner import generate_multi_gameweek_plan
from ..scores import update_gameweek_scores
from ..simulation import HistoricalSimulationSession
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
    rescore_transfer_candidates,
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
                session_id = get_arg("session_id")
                tid = get_arg("team")
                num_tx = int(get_arg("transfers", 1))
                gws = int(get_arg("gameweeks", 5))
                risk = get_arg("risk", "neutral")
                if risk in ("balanced", "default"):
                    risk = "neutral"
                engine = get_arg("engine", "v1.3.5")
                gamma_val = float(get_arg("gamma", 0.75))
                horizon_val = int(get_arg("horizon", 3))
                gw_param = get_arg("gameweek") or get_arg("gw")
                gw_val = int(gw_param) if gw_param else None
                limit_arg = get_arg("limit") or get_arg("max_results")
                max_results_val = int(limit_arg) if limit_arg else 30

                if session_id:
                    sim_dir = self.config_dir / "simulations"
                    sim = HistoricalSimulationSession.load(session_id, config_dir=sim_dir)
                    if sim.is_completed:
                        rep = {
                            "session_id": session_id,
                            "season_ended": True,
                            "message": "The season is ended. All 38 gameweeks have been completed.",
                            "top_suggestions": [],
                            "num_transfers": num_tx,
                            "free_transfers_available": 0,
                            "bank_tenths_available": sim.bank_tenths,
                            "transfers_staged": [],
                            "total_options_evaluated": 0,
                        }
                        self._send_json(rep)
                        return
                    snap = sim.get_current_snapshot()
                    season_dir = sim.historical_dir / sim.season
                    h_len = max(1, min(10, gws))
                    players_map, _ = load_historical_players_meta(snap, season_dir, horizon=h_len)
                    fdr_map, ticker_map = analyze_historical_fixtures(season_dir, num_gameweeks=h_len, start_gw=sim.current_gw)

                    # Effective squad reflects staged transfers for the upcoming gameweek
                    effective_squad_ids = list(sim.squad_ids)
                    effective_bank_tenths = sim.bank_tenths
                    for st in sim.transfers_staged:
                        o_id = st["out_id"]
                        i_id = st["in_id"]
                        if o_id in effective_squad_ids:
                            idx = effective_squad_ids.index(o_id)
                            effective_squad_ids[idx] = i_id
                        elif i_id not in effective_squad_ids:
                            effective_squad_ids.append(i_id)
                        effective_bank_tenths -= st.get("cost_tenths", 0)

                    effective_fts = max(0, sim.free_transfers - len(sim.transfers_staged))

                    squad_set = set(effective_squad_ids)
                    squad_players = [players_map[pid] for pid in effective_squad_ids if pid in players_map]
                    purch_prices = {}
                    for pid in effective_squad_ids:
                        st = next((s for s in sim.transfers_staged if s["in_id"] == pid), None)
                        if st:
                            purch_prices[pid] = st.get("in_price_tenths", players_map[pid].price_tenths if pid in players_map else 50)
                        else:
                            purch_prices[pid] = sim.purchase_prices_tenths.get(str(pid), players_map[pid].price_tenths if pid in players_map else 50)

                    selling_prices = {
                        pid: selling_price(purch_prices.get(pid, 50), players_map[pid].price_tenths if pid in players_map else 50)
                        for pid in effective_squad_ids
                    }
                    candidate_pool = [
                        p for p in players_map.values()
                        if p.id not in squad_set and p.status in ("a", "d") and not getattr(p, "is_long_term_unavailable", False)
                    ]

                    clean_engine = str(engine).lower().strip()
                    is_legacy = clean_engine in ("legacy", "v1.0", "v1.0.1", "v10", "v101")
                    is_v12 = clean_engine in ("v1.2", "v12")
                    is_v125 = clean_engine in ("v1.2.5", "v125")
                    is_v135 = clean_engine in ("v1.3.5", "v1.4", "v135", "v14", "default") or (not is_legacy and not is_v12 and not is_v125)
                    engine_name = "v1.3.5" if is_v135 else ("v1.2.5" if is_v125 else ("v1.2" if is_v12 else "legacy"))

                    if is_v135:
                        cand_search_max = max(max_results_val, 30)
                    elif not is_legacy:
                        cand_search_max = max(max_results_val * 2, 50)
                    else:
                        cand_search_max = max_results_val

                    from ..optimizer import solve_transfers
                    raw_results, total_evaluated = solve_transfers(
                        num_transfers=num_tx,
                        squad_players=squad_players,
                        candidate_pool=candidate_pool,
                        bank_tenths=effective_bank_tenths,
                        free_transfers=effective_fts,
                        selling_prices=selling_prices,
                        fdr_map=fdr_map,
                        ticker_map=ticker_map,
                        risk_profile=risk,
                        max_results=cand_search_max,
                    )
                    target_gws = list(range(sim.current_gw, sim.current_gw + h_len))

                    if is_legacy:
                        top_results = raw_results[:max_results_val]
                        reason_breakdown = None
                    else:
                        eff_horizon = 1 if is_v12 else min(h_len, horizon_val)
                        eff_gamma = 1.0 if is_v12 else gamma_val

                        projections_by_gw = {
                            gw: {
                                p.id: (
                                    p.gw_breakdown_xp.get(gw, 0.0)
                                    if getattr(p, "gw_breakdown_xp", None)
                                    else p.expected_points
                                )
                                for p in players_map.values()
                            }
                            for gw in target_gws[:eff_horizon]
                        }

                        top_results = rescore_transfer_candidates(
                            raw_results=raw_results,
                            squad_players=squad_players,
                            players_map=players_map,
                            projections_by_gw=projections_by_gw,
                            eff_horizon=eff_horizon,
                            eff_gamma=eff_gamma,
                            max_results=max_results_val,
                        )
                        reason_breakdown = {
                            "engine": engine_name,
                            "pool_expansion_candidates": sum(
                                1 for r in top_results if r.get("reason_breakdown", {}).get("pool_expansion_surfaced")
                            ),
                            "gk_suppression_active": any(
                                r.get("reason_breakdown", {}).get("gk_suppression") not in ("n/a", "approved_hurdle_met")
                                for r in top_results
                            ),
                        }

                    rep = {
                        "num_transfers": num_tx,
                        "free_transfers_available": effective_fts,
                        "bank_tenths_available": effective_bank_tenths,
                        "transfers_staged": sim.transfers_staged,
                        "risk_profile": risk,
                        "engine": engine_name,
                        "target_gameweeks": target_gws,
                        "evaluation_horizon_gws": h_len,
                        "total_options_evaluated": total_evaluated,
                        "top_suggestions": top_results,
                        "session_id": session_id,
                    }
                    if reason_breakdown:
                        rep["transfer_reason_breakdown"] = reason_breakdown

                    from collections import Counter
                    team_counts = Counter(getattr(p, "team_short", getattr(p, "team_id", "")) for p in squad_players)
                    excess_teams = {t: c for t, c in team_counts.items() if c > 3}
                    if excess_teams:
                        max_excess = max(excess_teams.values())
                        min_tx_needed = max_excess - 3
                        rep["team_quota_warning"] = {
                            "excess_teams": excess_teams,
                            "min_transfers_needed": min_tx_needed,
                            "message": (
                                f"Squad currently has {', '.join(f'{c} players from {t}' for t, c in excess_teams.items())} "
                                f"due to mid-season real-life transfers. Official FPL rules require that any transfer move "
                                f"must restore your squad to at most 3 players per club. A minimum of {min_tx_needed} transfer(s) "
                                f"selling players from these club(s) is required to produce a legal squad."
                            ),
                        }
                else:
                    squad_path = get_team_squad_path(tid, self.config_dir)
                    curr_gw = get_current_gameweek(SnapshotStore(self.database_path))
                    effective_gw = gw_val or curr_gw
                    rep = suggest_transfers(
                        num_transfers=num_tx,
                        squad_path=squad_path,
                        database_path=self.database_path,
                        max_results=max_results_val,
                        num_gameweeks=gws,
                        risk_profile=risk,
                        gameweek=effective_gw,
                        engine=engine,
                        gamma=gamma_val,
                        horizon=horizon_val,
                        team_id=tid,
                        config_dir=self.config_dir,
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
                season = get_arg("season")
                gw_arg = get_arg("gameweek")
                gw = int(gw_arg) if gw_arg else 1
                session_id = get_arg("session_id")

                if season:
                    hist_dir = PROJECT_ROOT / "data" / "historical"
                    season_dir = hist_dir / season
                    if not season_dir.exists():
                        raise FileNotFoundError(f"Historical season directory not found: {season_dir}")
                    snap = build_historical_snapshot(season_dir, gw)
                    players_map, _ = load_historical_players_meta(snap, season_dir, horizon=5)
                    team_info = None
                    if session_id:
                        sim_dir = self.config_dir / "simulations"
                        if (sim_dir / f"{session_id}.json").exists():
                            sim = HistoricalSimulationSession.load(session_id, config_dir=sim_dir)
                            team_info = {
                                "id": sim.session_id,
                                "name": sim.experiment_metadata.get("manager_name", f"Simulation ({sim.season})"),
                                "season": sim.season,
                                "current_gw": sim.current_gw,
                                "bank_tenths": sim.bank_tenths,
                            }
                    current_gw = gw
                else:
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
                    "season": season,
                    "players": player_list,
                })
            elif path == "/api/strategic-squad":
                season = get_arg("season")
                gw_arg = get_arg("gameweek")
                gw = int(gw_arg) if gw_arg else 1
                session_id = get_arg("session_id")
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

                if season:
                    hist_dir = PROJECT_ROOT / "data" / "historical"
                    season_dir = hist_dir / season
                    if not season_dir.exists():
                        raise FileNotFoundError(f"Historical season directory not found: {season_dir}")
                    snap = build_historical_snapshot(season_dir, gw)
                    h_len = 1 if mode == "free_hit" else max(1, min(8, horizon))
                    players_map, _ = load_historical_players_meta(snap, season_dir, horizon=h_len)

                    if budget is not None:
                        budget_tenths = int(round(budget * 10))
                    elif mode == "initial":
                        budget_tenths = 1000
                    elif session_id:
                        sim_dir = self.config_dir / "simulations"
                        sim = HistoricalSimulationSession.load(session_id, config_dir=sim_dir)
                        squad_selling_value = sum(
                            selling_price(sim.purchase_prices_tenths.get(str(p_id), players_map[p_id].price_tenths if p_id in players_map else 50), players_map[p_id].price_tenths)
                            for p_id in sim.squad_ids
                            if p_id in players_map
                        )
                        budget_tenths = sim.bank_tenths + squad_selling_value
                    else:
                        budget_tenths = 1000

                    target_gws = list(range(gw, min(39, gw + h_len)))
                    effective_constraints = StrategicConstraints(
                        budget_tenths=budget_tenths,
                        locked_player_ids=set(locks),
                        excluded_player_ids=set(excl),
                        preferred_player_ids=set(pref),
                        target_gameweeks=tuple(target_gws),
                    )
                    candidate_pool = [
                        p for p in players_map.values()
                        if p.status in ("a", "d") and not getattr(p, "is_long_term_unavailable", False)
                    ]
                    primary_candidate = solve_strategic_squad(
                        candidate_pool=candidate_pool,
                        constraints=effective_constraints,
                        strategy=strategy,
                        mode=mode,
                        horizon=h_len,
                    )
                    rep = primary_candidate.to_dict()
                    rep["selected_candidate"] = primary_candidate.to_dict()
                    rep["mode"] = mode
                    rep["strategy"] = strategy
                    rep["horizon"] = h_len
                    rep["budget_millions"] = budget_tenths / 10.0
                    rep["bank_remaining_tenths"] = primary_candidate.bank_remaining_tenths

                    failed_profiles_map: dict[str, str] = {}
                    all_cands = generate_strategic_candidates(
                        candidate_pool=candidate_pool,
                        constraints=effective_constraints,
                        mode=mode,
                        horizon=h_len,
                        failed_profiles=failed_profiles_map,
                    )
                    rep["requested_profiles"] = getattr(all_cands, "requested_profiles", list(all_cands.keys()))
                    rep["successful_profiles"] = getattr(all_cands, "successful_profiles", list(all_cands.keys()))
                    rep["failed_profiles"] = failed_profiles_map
                    rep["strategic_candidates"] = {
                        s: cand.to_dict() for s, cand in all_cands.items()
                    }
                    rep["candidates"] = [cand.to_dict() for cand in all_cands.values()]
                    rep["season"] = season
                    rep["session_id"] = session_id
                else:
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
                session_id = get_arg("session_id")
                tid = get_arg("team")
                horizon = int(get_arg("horizon", 3))
                start_gw = int(get_arg("start_gw")) if get_arg("start_gw") else None
                risk = get_arg("risk", "neutral")
                no_hits = get_arg("no_hits", "false").lower() in ("true", "1", "yes")

                if session_id:
                    sim_dir = self.config_dir / "simulations"
                    sim = HistoricalSimulationSession.load(session_id, config_dir=sim_dir)
                    if sim.is_completed:
                        self._send_json({
                            "session_id": session_id,
                            "best_plan": None,
                            "season_ended": True,
                            "message": "The season is ended. All 38 gameweeks have been completed.",
                        })
                        return
                    recs = sim.get_recommendations()
                    target_gw = sim.current_gw
                    step0_transfers = [
                        {
                            "out": {"id": t["out_id"], "name": t["out_name"]},
                            "in": {"id": t["in_id"], "name": t["in_name"]},
                        }
                        for t in recs.get("recommended_transfers", [])
                    ]
                    squad_details = sim.get_squad_player_details()
                    cap_id = recs.get("recommended_captain")
                    vc_id = recs.get("recommended_vice_captain")
                    cap_name = next((p["name"] for p in squad_details if p.get("player_id", p.get("id")) == cap_id), "Captain")
                    vc_name = next((p["name"] for p in squad_details if p.get("player_id", p.get("id")) == vc_id), "Vice Captain")

                    step0_hits = max(0, len(step0_transfers) - sim.free_transfers)
                    step0_net_xp = recs.get("predicted_lineup_xp", 0.0) - (step0_hits * 4)
                    ft_after = 1 if len(step0_transfers) > 0 else min(5, sim.free_transfers + 1)

                    steps = [
                        {
                            "gameweek": target_gw,
                            "action": f"{len(step0_transfers)}_TRANSFER" if step0_transfers else "ROLL",
                            "transfers": step0_transfers,
                            "formation": "3-4-3",
                            "captain": {"id": cap_id, "name": cap_name},
                            "vice_captain": {"id": vc_id, "name": vc_name},
                            "lineup_xp": recs.get("predicted_lineup_xp", 0.0),
                            "transfer_hits": step0_hits,
                            "net_xp": step0_net_xp,
                            "bank_after_tenths": sim.bank_tenths,
                            "bank_after_fmt": f"£{sim.bank_tenths / 10:.1f}m",
                            "free_transfers_after": ft_after,
                        }
                    ]

                    # Roll forward subsequent steps up to horizon (max GW 38)
                    curr_ft = ft_after
                    for step_idx in range(1, min(horizon, 38 - target_gw + 1)):
                        fut_gw = target_gw + step_idx
                        # Projections for fut_gw if available
                        fut_snap = None
                        fut_cap_name = cap_name
                        fut_cap_id = cap_id
                        fut_lineup_xp = recs.get("predicted_lineup_xp", 0.0)
                        try:
                            season_dir = sim.historical_dir / sim.season
                            fut_snap = build_historical_snapshot(season_dir, fut_gw)
                            fut_projs = reconstruct_features_and_project(fut_snap)
                            p_map = {p.player_id: p for p in fut_projs}
                            # Best captain
                            squad_projs = [(pid, p_map[pid].expected_points) for pid in sim.squad_ids if pid in p_map]
                            if squad_projs:
                                squad_projs.sort(key=lambda x: x[1], reverse=True)
                                fut_cap_id = squad_projs[0][0]
                                snap_players = {p.player_id: p.web_name for p in fut_snap.players}
                                fut_cap_name = snap_players.get(fut_cap_id, "Captain")
                                fut_lineup_xp = round(sum(xp for _, xp in squad_projs[:11]) + squad_projs[0][1], 1)
                        except Exception:
                            pass

                        curr_ft = min(5, curr_ft + 1)
                        steps.append({
                            "gameweek": fut_gw,
                            "action": "ROLL",
                            "transfers": [],
                            "formation": "3-4-3",
                            "captain": {"id": fut_cap_id, "name": fut_cap_name},
                            "vice_captain": {"id": vc_id, "name": vc_name},
                            "lineup_xp": fut_lineup_xp,
                            "transfer_hits": 0,
                            "net_xp": fut_lineup_xp,
                            "bank_after_tenths": sim.bank_tenths,
                            "bank_after_fmt": f"£{sim.bank_tenths / 10:.1f}m",
                            "free_transfers_after": curr_ft,
                        })

                    rep = {
                        "session_id": session_id,
                        "best_plan": {
                            "gameweek_steps": steps,
                            "total_net_xp": round(sum(s["net_xp"] for s in steps), 1),
                            "total_hits": sum(s["transfer_hits"] for s in steps),
                        }
                    }
                else:
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
                session_id = get_arg("session_id")
                if session_id:
                    sim_dir = self.config_dir / "simulations"
                    sim = HistoricalSimulationSession.load(session_id, config_dir=sim_dir)
                    snap = sim.get_current_snapshot()
                    player_names = {p.player_id: p.web_name for p in snap.players}

                    dec_list = []
                    history_gws = {h.get("gameweek") for h in sim.history if h.get("gameweek")}
                    if getattr(sim, "initial_decision", None) and sim.initial_decision.get("gameweek") not in history_gws:
                        init_d = dict(sim.initial_decision)
                        cap_id = init_d.get("captain_id")
                        vc_id = init_d.get("vice_captain_id")
                        init_d.setdefault("captain_name", player_names.get(cap_id, f"ID {cap_id}"))
                        init_d.setdefault("vice_captain_name", player_names.get(vc_id, f"ID {vc_id}"))
                        dec_list.append(init_d)

                    for h in sim.history:
                        d = h.get("decision_logged") or h.get("decision")
                        if d:
                            d_copy = dict(d)
                        else:
                            d_copy = {
                                "gameweek": h.get("gameweek"),
                                "season": sim.season,
                                "session_id": session_id,
                                "chip_played": h.get("chip_used"),
                                "transfer_hits": h.get("transfer_hits", 0),
                                "transfers": h.get("transfers_executed") or h.get("transfers") or [],
                                "squad_player_ids": h.get("squad_ids_after") or h.get("squad_ids") or [],
                                "starting_player_ids": [p["player_id"] for p in h.get("starters_points", [])] if h.get("starters_points") else [],
                                "bench_player_ids": [p["player_id"] for p in h.get("bench_points", [])] if h.get("bench_points") else [],
                                "captain_id": h.get("captain_id"),
                                "vice_captain_id": h.get("vice_captain_id"),
                                "predicted_lineup_xp": h.get("engine_recommendation", {}).get("predicted_lineup_xp", 0.0),
                                "notes": f"Simulated matchday GW{h.get('gameweek')}",
                            }
                        d_copy["actual_points"] = h.get("gross_points", h.get("points"))

                        # If GW1 and initial_decision exists with custom notes, use initial notes
                        if h.get("gameweek") == 1 and getattr(sim, "initial_decision", None):
                            init_notes = sim.initial_decision.get("notes")
                            if init_notes and (not d_copy.get("notes") or d_copy["notes"].startswith("Simulated matchday")):
                                d_copy["notes"] = init_notes

                        # Normalize captain & vice-captain names
                        cap_id = d_copy.get("captain_id") or h.get("captain_id")
                        vc_id = d_copy.get("vice_captain_id") or h.get("vice_captain_id")
                        d_copy.setdefault("captain_name", player_names.get(cap_id, f"ID {cap_id}"))
                        d_copy.setdefault("vice_captain_name", player_names.get(vc_id, f"ID {vc_id}"))

                        # Normalize transfers with player names
                        raw_txs = d_copy.get("transfers") or []
                        norm_txs = []
                        for t in raw_txs:
                            if isinstance(t, (list, tuple)) and len(t) >= 2:
                                o_id, i_id = int(t[0]), int(t[1])
                                norm_txs.append({
                                    "outgoing_id": o_id,
                                    "incoming_id": i_id,
                                    "outgoing_name": player_names.get(o_id, f"Player {o_id}"),
                                    "incoming_name": player_names.get(i_id, f"Player {i_id}"),
                                })
                            elif isinstance(t, dict):
                                o_id = t.get("outgoing_id", t.get("out_id"))
                                i_id = t.get("incoming_id", t.get("in_id"))
                                norm_txs.append({
                                    "outgoing_id": o_id,
                                    "incoming_id": i_id,
                                    "outgoing_name": t.get("outgoing_name") or t.get("out_name") or player_names.get(o_id, f"Player {o_id}"),
                                    "incoming_name": t.get("incoming_name") or t.get("in_name") or player_names.get(i_id, f"Player {i_id}"),
                                })
                        d_copy["transfers"] = norm_txs
                        dec_list.append(d_copy)

                    gw_arg = get_arg("gameweek")
                    if gw_arg:
                        gw = int(gw_arg)
                        dec = next((d for d in dec_list if d.get("gameweek") == gw), None)
                        self._send_json({"decision": dec, "session_id": session_id})
                    else:
                        self._send_json({"decisions": dec_list, "session_id": session_id})
                else:
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
                session_id = get_arg("session_id")
                if session_id:
                    sim_dir = self.config_dir / "simulations"
                    sim = HistoricalSimulationSession.load(session_id, config_dir=sim_dir)
                    gw_arg = get_arg("gameweek")
                    if gw_arg:
                        gw = int(gw_arg)
                        h_entry = next((h for h in sim.history if h.get("gameweek") == gw), None)
                        if not h_entry:
                            self._send_error_json(f"Gameweek {gw} not evaluated yet in session {session_id}", status=404)
                            return
                        dec = h_entry.get("decision_logged") or h_entry.get("decision") or {}
                        self._send_json({
                            "gameweek": gw,
                            "actual_lineup_score": h_entry.get("gross_points", 0),
                            "predicted_lineup_xp": dec.get("predicted_lineup_xp", 0.0),
                            "captaincy": {
                                "captain_name": h_entry.get("captain_name", "Captain"),
                                "captain_actual_points": h_entry.get("captain_points", 0),
                                "optimal_captain_name": h_entry.get("captain_name", "Captain"),
                                "optimal_captain_actual_points": h_entry.get("captain_points", 0),
                                "captaincy_regret_points": 0,
                            },
                            "bench": {
                                "total_bench_points": sum(b.get("points", 0) for b in h_entry.get("bench", [])),
                                "bench_regret_points": 0,
                            },
                        })
                    else:
                        # Full session evaluation summary
                        finalized = [h for h in sim.history if "gross_points" in h or "points" in h]
                        tot_pred = sum((h.get("decision_logged") or h.get("decision") or {}).get("predicted_lineup_xp", 0.0) for h in finalized)
                        tot_act = sum(h.get("gross_points", h.get("points", 0)) for h in finalized)
                        tot_hits = sum(h.get("transfer_hits", 0) for h in finalized)
                        n = len(finalized)
                        mae = (sum(abs((h.get("gross_points", h.get("points", 0))) - ((h.get("decision_logged") or h.get("decision") or {}).get("predicted_lineup_xp", 0.0))) for h in finalized) / n) if n else 0.0
                        self._send_json({
                            "finalized_gameweeks": n,
                            "total_predicted_xp": tot_pred,
                            "total_actual_points": tot_act,
                            "lineup_mae": mae,
                            "lineup_rmse": mae,
                            "mean_prediction_bias": ((tot_pred - tot_act) / n) if n else 0.0,
                            "bias_interpretation": "Slight Overprediction" if tot_pred > tot_act else "Underprediction",
                            "total_transfer_hits": tot_hits,
                        })
                else:
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
            elif path == "/api/overview":
                gw_arg = get_arg("gameweek")
                gw = int(gw_arg) if gw_arg else None
                past_gw_arg = get_arg("past_gw")
                past_gw = int(past_gw_arg) if past_gw_arg else None
                future_gw_arg = get_arg("future_gw")
                future_gw = int(future_gw_arg) if future_gw_arg else None
                data = get_live_matchday_overview(
                    self.database_path,
                    target_gw=gw,
                    past_gw=past_gw,
                    future_gw=future_gw,
                )
                self._send_json(data)
            elif path == "/api/historical/seasons":
                hist_dir = PROJECT_ROOT / "data" / "historical"
                seasons = sorted([
                    d.name for d in hist_dir.iterdir()
                    if d.is_dir() and d.name not in ("raw", "__pycache__") and (d / "fixtures.json").exists()
                ])
                self._send_json({"seasons": seasons})
            elif path == "/api/historical/overview":
                season = get_arg("season", "2023-24")
                gw = int(get_arg("gameweek", 1))
                past_gw_arg = get_arg("past_gw")
                past_gw = int(past_gw_arg) if past_gw_arg else None
                future_gw_arg = get_arg("future_gw")
                future_gw = int(future_gw_arg) if future_gw_arg else None
                data = get_historical_matchday_overview(
                    season,
                    gw,
                    past_gw=past_gw,
                    future_gw=future_gw,
                )
                self._send_json(data)
            elif path == "/api/historical/simulations":
                sim_dir = self.config_dir / "simulations"
                sessions = HistoricalSimulationSession.list_sessions(sim_dir)
                self._send_json({"simulations": sessions})
            elif path.startswith("/api/historical/simulations/"):
                sim_dir = self.config_dir / "simulations"
                sub = path[len("/api/historical/simulations/"):].strip("/")
                parts = sub.split("/")
                session_id = parts[0]
                action = parts[1] if len(parts) > 1 else None
                sim = HistoricalSimulationSession.load(session_id, config_dir=sim_dir)
                if action == "players":
                    snap = sim.get_current_snapshot()
                    season_dir = sim.historical_dir / sim.season
                    players_map, _ = load_historical_players_meta(snap, season_dir, horizon=1)
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
                            "expected_points": getattr(p, "gw_xp", getattr(p, "expected_points", 0.0)),
                            "total_points": p.total_points,
                            "status": getattr(p, "status", "a"),
                        }
                        for p in sorted(players_map.values(), key=lambda x: (x.position.value, -x.total_points))
                    ]
                    self._send_json({"players": player_list})
                elif action == "recommendations":
                    recs = sim.get_recommendations()
                    self._send_json(recs)
                elif action == "chips":
                    if sim.is_completed:
                        self._send_json({
                            "session_id": sim.session_id,
                            "season": sim.season,
                            "season_ended": True,
                            "message": "The season is ended. All 38 gameweeks have been completed.",
                            "available_chips": [],
                            "used_chips": [c.lower().replace("-", "_") for c in sim.chips_used.keys()],
                            "recommended_schedule": [],
                        })
                        return
                    start_gw_arg = get_arg("start_gw")
                    start_gw = int(start_gw_arg) if start_gw_arg else sim.current_gw
                    recs = sim.get_recommendations()
                    rec_chip = recs.get("recommended_chip")
                    is_seg1 = start_gw <= 19
                    seg_name = "1-19" if is_seg1 else "20-38"

                    # Map session chips to standard representation
                    remaining_clean = []
                    for c in sim.chips_remaining:
                        norm = c.lower().replace("-", "_")
                        if norm in ("wildcard_1", "wildcard_2", "wildcard"):
                            if (is_seg1 and norm in ("wildcard_1", "wildcard")) or (not is_seg1 and norm in ("wildcard_2", "wildcard")):
                                if "wildcard" not in remaining_clean:
                                    remaining_clean.append("wildcard")
                        elif norm in ("free_hit", "freehit"):
                            if "freehit" not in remaining_clean:
                                remaining_clean.append("freehit")
                        elif norm in ("bench_boost", "benchboost"):
                            if "benchboost" not in remaining_clean:
                                remaining_clean.append("benchboost")
                        elif norm in ("triple_captain", "triplecaptain"):
                            if "triplecaptain" not in remaining_clean:
                                remaining_clean.append("triplecaptain")

                    used_clean = []
                    for c, used_gw in sim.chips_used.items():
                        if (is_seg1 and used_gw <= 19) or (not is_seg1 and used_gw >= 20):
                            norm = c.lower().replace("-", "_")
                            if norm in ("wildcard_1", "wildcard_2", "wildcard"):
                                if "wildcard" not in used_clean:
                                    used_clean.append("wildcard")
                            elif norm.startswith("free_hit") or norm.startswith("freehit"):
                                if "freehit" not in used_clean:
                                    used_clean.append("freehit")
                            elif norm.startswith("bench_boost") or norm.startswith("benchboost"):
                                if "benchboost" not in used_clean:
                                    used_clean.append("benchboost")
                            elif norm.startswith("triple_captain") or norm.startswith("triplecaptain"):
                                if "triplecaptain" not in used_clean:
                                    used_clean.append("triplecaptain")

                    seg_end = 19 if is_seg1 else 38
                    schedule = []

                    from ..simulation.chip_optimizer import extract_season_fixture_topology
                    topo_map = extract_season_fixture_topology(season=sim.season)

                    assigned_gws = set()

                    # 1. If currently recommended chip by engine for current GW, lock it in
                    if rec_chip:
                        norm_rec = "freehit" if rec_chip == "free_hit" else ("benchboost" if rec_chip == "bench_boost" else ("triplecaptain" if rec_chip == "triple_captain" else "wildcard"))
                        if norm_rec in remaining_clean:
                            opp = recs.get("recommended_chip_opportunity") or {}
                            schedule.append({
                                "gameweek": sim.current_gw,
                                "chip": norm_rec,
                                "gw_type": "OPPORTUNITY_COST_OPTIMIZER",
                                "reasoning": opp.get("reasoning") or f"Recommended by ChipOpportunityOptimizer for GW{sim.current_gw}.",
                                "immediate_ev": opp.get("immediate_ev", 12.0),
                                "future_opportunity": opp.get("future_max_ev", 0.0),
                                "net_utility": opp.get("net_utility", 12.0),
                                "confidence": opp.get("confidence", 0.9),
                            })
                            assigned_gws.add(sim.current_gw)

                    # 2. Prioritize remaining available chips across the segment
                    chip_priority = ["freehit", "triplecaptain", "benchboost", "wildcard"]
                    unassigned_chips = [c for c in chip_priority if c in remaining_clean and not any(s["chip"] == c for s in schedule)]

                    for chip_name in unassigned_chips:
                        best_gw = None
                        best_score = -999.0
                        best_gw_type = "OPTIMAL_TIMING"
                        best_reason = ""
                        best_ev = 10.0

                        for cand_gw in range(max(start_gw, sim.current_gw), seg_end + 1):
                            if cand_gw in assigned_gws:
                                continue
                            topo = topo_map.get(cand_gw)
                            score = 0.0
                            gw_type = "OPTIMAL_TIMING"
                            reason = ""
                            ev = 10.0

                            if chip_name == "triplecaptain":
                                if topo and topo.is_double and len(topo.double_team_ids) >= 1:
                                    score = 15.0 + len(topo.double_team_ids) * 2.0
                                    gw_type = "DOUBLE_GAMEWEEK"
                                    reason = f"Double Gameweek {cand_gw} offers explosive 180-minute captain upside."
                                    ev = 16.5
                                elif cand_gw == seg_end:
                                    score = 9.0
                                    gw_type = "SEGMENT_EXPIRY"
                                    reason = f"Last remaining gameweek to deploy first-half Triple Captain before reset."
                                    ev = 10.0
                                else:
                                    score = 8.0 - (cand_gw - start_gw) * 0.1
                                    gw_type = "PREMIUM_FIXTURE"
                                    reason = f"Prime fixture matchup with minimal blank risk."
                                    ev = 9.5

                            elif chip_name == "benchboost":
                                if topo and topo.is_double and len(topo.double_team_ids) >= 2:
                                    score = 16.0 + len(topo.double_team_ids) * 2.0
                                    gw_type = "DOUBLE_GAMEWEEK"
                                    reason = f"Extensive Double Gameweek {cand_gw} maximizing 15-player bench returns."
                                    ev = 18.0
                                elif topo and topo.is_double:
                                    score = 13.0
                                    gw_type = "DOUBLE_GAMEWEEK"
                                    reason = f"Double Gameweek {cand_gw} bench scoring boost."
                                    ev = 13.5
                                elif cand_gw == seg_end - 1 or cand_gw == seg_end:
                                    score = 8.5
                                    gw_type = "SEGMENT_EXPIRY"
                                    reason = f"Deploy Bench Boost before segment boundary deadline."
                                    ev = 9.0
                                else:
                                    score = 7.0 - (cand_gw - start_gw) * 0.1
                                    gw_type = "BENCH_DEPTH"
                                    reason = f"Favorable all-round fixture alignment for all 15 squad members."
                                    ev = 8.5

                            elif chip_name == "freehit":
                                if topo and topo.is_blank and len(topo.blank_team_ids) >= 4:
                                    score = 18.0 + len(topo.blank_team_ids) * 2.0
                                    gw_type = "BLANK_GAMEWEEK"
                                    reason = f"Navigate severe Blank Gameweek {cand_gw} without burning permanent transfers."
                                    ev = 20.0
                                elif topo and topo.is_double and len(topo.double_team_ids) >= 4:
                                    score = 16.0
                                    gw_type = "DOUBLE_GAMEWEEK"
                                    reason = f"Mega Double Gameweek {cand_gw} short-term specialist rental."
                                    ev = 17.0
                                elif cand_gw == seg_end:
                                    score = 8.5
                                    gw_type = "SEGMENT_EXPIRY"
                                    reason = f"Deploy Free Hit before half-season chip expiration."
                                    ev = 9.5
                                else:
                                    score = 6.0 - (cand_gw - start_gw) * 0.1
                                    gw_type = "FIXTURE_SWING"
                                    reason = f"Navigate fixture congestion and rotation."
                                    ev = 8.0

                            elif chip_name == "wildcard":
                                opt_window = 8 if is_seg1 else 29
                                dist = abs(cand_gw - opt_window)
                                score = 14.0 - dist * 0.8
                                gw_type = "FIXTURE_SWING"
                                reason = f"Optimal long-term squad restructuring window capitalizing on fixture swings."
                                ev = 15.0

                            if score > best_score:
                                best_score = score
                                best_gw = cand_gw
                                best_gw_type = gw_type
                                best_reason = reason
                                best_ev = ev

                        if best_gw is not None:
                            assigned_gws.add(best_gw)
                            schedule.append({
                                "gameweek": best_gw,
                                "chip": chip_name,
                                "gw_type": best_gw_type,
                                "reasoning": best_reason,
                                "immediate_ev": round(best_ev, 1),
                                "future_opportunity": round(best_ev * 0.75, 1),
                                "net_utility": round(best_ev * 0.25, 1),
                                "confidence": 0.88,
                            })

                    schedule.sort(key=lambda s: s["gameweek"])

                    self._send_json({
                        "session_id": sim.session_id,
                        "season": sim.season,
                        "gameweek": sim.current_gw,
                        "segment": seg_name,
                        "available_chips": remaining_clean,
                        "used_chips": used_clean,
                        "active_chip": sim.active_chip,
                        "recommended_schedule": schedule,
                    })
                elif action == "report":
                    summary = sim.generate_summary()
                    self._send_json(summary.to_dict())
                elif action == "lineup":
                    gw_arg = get_arg("gw")
                    target_gw = int(gw_arg) if gw_arg else sim.current_gw
                    lineup_data = sim.get_historical_lineup_for_gw(target_gw)
                    self._send_json(lineup_data)
                else:
                    effective_fts = max(0, sim.free_transfers - len(sim.transfers_staged))
                    self._send_json({
                        "session_id": sim.session_id,
                        "season": sim.season,
                        "current_gw": sim.current_gw,
                        "status": sim.status,
                        "is_completed": sim.is_completed,
                        "bank_tenths": sim.bank_tenths,
                        "free_transfers": effective_fts,
                        "free_transfers_base": sim.free_transfers,
                        "chips_remaining": sim.chips_remaining,
                        "chips_used": sim.chips_used,
                        "active_chip": sim.active_chip,
                        "transfers_staged": sim.transfers_staged,
                        "squad": sim.get_squad_player_details(),
                        "history": sim.history,
                        "experiment_metadata": sim.experiment_metadata,
                        "total_net_points": sum(h.get("net_points", 0) for h in sim.history),
                    })
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
                session_id = body.get("session_id")
                tx_list = body.get("transfers", [])
                if not tx_list:
                    raise ValueError("Field 'transfers' is required.")
                if session_id:
                    sim_dir = self.config_dir / "simulations"
                    sim = HistoricalSimulationSession.load(session_id, config_dir=sim_dir)
                    for t in tx_list:
                        o_id = int(t.get("outgoing_id", t.get("out_id")))
                        i_id = int(t.get("incoming_id", t.get("in_id")))
                        sim.stage_transfer(o_id, i_id)
                    sim.save()
                    snap = sim.get_current_snapshot()
                    p_names = {p.player_id: p.web_name for p in snap.players}
                    executed = [
                        {
                            "outgoing_id": st["out_id"],
                            "incoming_id": st["in_id"],
                            "outgoing_name": st.get("out_name") or p_names.get(st["out_id"], f"Player {st['out_id']}"),
                            "incoming_name": st.get("in_name") or p_names.get(st["in_id"], f"Player {st['in_id']}"),
                            "selling_price_tenths": st.get("out_price_tenths", 50),
                            "purchase_price_tenths": st.get("in_price_tenths", 50),
                        }
                        for st in sim.transfers_staged
                    ]
                    self._send_json({
                        "success": True,
                        "session_id": session_id,
                        "transfers": executed,
                        "bank_fmt": f"£{sim.bank_tenths / 10:.1f}m",
                        "free_transfers": max(0, sim.free_transfers - len(sim.transfers_staged)),
                    })
                    return

                tid = body.get("team_id") or get_active_team_id(self.config_dir)
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
                session_id = body.get("session_id")
                if session_id:
                    sim_dir = self.config_dir / "simulations"
                    sim = HistoricalSimulationSession.load(session_id, config_dir=sim_dir)
                    gw = int(body.get("gameweek") or sim.current_gw)
                    snap = sim.get_current_snapshot()
                    player_names = {p.player_id: getattr(p, "web_name", getattr(p, "name", str(p.player_id))) for p in snap.players}
                    name_to_id = {getattr(p, "web_name", "").lower(): p.player_id for p in snap.players if hasattr(p, "web_name")}
                    name_to_id.update({getattr(p, "name", "").lower(): p.player_id for p in snap.players if hasattr(p, "name")})

                    cap_raw = body.get("captain") or body.get("captain_id") or sim.captain_id
                    if isinstance(cap_raw, str):
                        if cap_raw.isdigit():
                            cap_val = int(cap_raw)
                        else:
                            cap_val = name_to_id.get(cap_raw.lower(), cap_raw)
                    else:
                        cap_val = cap_raw

                    vc_raw = body.get("vice_captain") or body.get("vice_captain_id") or sim.vice_captain_id
                    if isinstance(vc_raw, str):
                        if vc_raw.isdigit():
                            vc_val = int(vc_raw)
                        else:
                            vc_val = name_to_id.get(vc_raw.lower(), vc_raw)
                    else:
                        vc_val = vc_raw

                    cap_name = player_names.get(cap_val) or (cap_raw if isinstance(cap_raw, str) else f"ID {cap_val}")
                    vc_name = player_names.get(vc_val) or (vc_raw if isinstance(vc_raw, str) else f"ID {vc_val}")

                    dec_obj = {
                        "gameweek": gw,
                        "season": sim.season,
                        "session_id": session_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "chip_played": body.get("chip"),
                        "transfer_hits": int(body.get("hits") or 0),
                        "transfers": body.get("transfers") or [],
                        "squad_player_ids": body.get("squad_players") or list(sim.squad_ids),
                        "starting_player_ids": body.get("starters") or list(sim.starting_ids),
                        "bench_player_ids": body.get("bench") or list(sim.bench_ids),
                        "captain_id": cap_val,
                        "captain_name": cap_name,
                        "vice_captain_id": vc_val,
                        "vice_captain_name": vc_name,
                        "notes": body.get("notes", ""),
                    }
                    existing_entry = next((h for h in sim.history if h.get("gameweek") == gw), None)
                    if existing_entry:
                        existing_entry["decision_logged"] = dec_obj
                        existing_entry["decision"] = dec_obj
                    elif getattr(sim, "initial_decision", None) and sim.initial_decision.get("gameweek") == gw:
                        sim.initial_decision = dec_obj
                    else:
                        sim.history.append({"gameweek": gw, "type": "manual_decision", "decision_logged": dec_obj, "decision": dec_obj})
                    if gw == sim.current_gw:
                        if dec_obj.get("captain_id"):
                            try:
                                sim.captain_id = int(dec_obj["captain_id"])
                            except Exception:
                                pass
                        if dec_obj.get("vice_captain_id"):
                            try:
                                sim.vice_captain_id = int(dec_obj["vice_captain_id"])
                            except Exception:
                                pass
                        sim.active_chip = dec_obj.get("chip_played")
                    sim.save()
                    self._send_json({"success": True, "gameweek": gw, "decision": dec_obj, "session_id": session_id})
                    return

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
                session_id = body.get("session_id")
                if session_id:
                    sim_dir = self.config_dir / "simulations"
                    sim = HistoricalSimulationSession.load(session_id, config_dir=sim_dir)
                    res = sim.undo_last_gameweek()
                else:
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
                season = body.get("season")
                gw_val = body.get("gameweek")
                gw = int(gw_val) if gw_val is not None else 1
                session_id = body.get("session_id")
                tid = body.get("team_id") or get_active_team_id(self.config_dir)
                mode = body.get("mode", "initial")
                horizon = int(body.get("horizon", 5))
                strategy = body.get("strategy", "balanced")
                budget = float(body.get("budget")) if body.get("budget") is not None else None
                locked_ids = [int(i) for i in body.get("locked_player_ids", [])]
                excluded_ids = [int(i) for i in body.get("excluded_player_ids", [])]
                preferred_ids = [int(i) for i in body.get("preferred_player_ids", [])]

                try:
                    if season:
                        hist_dir = PROJECT_ROOT / "data" / "historical"
                        season_dir = hist_dir / season
                        if not season_dir.exists():
                            raise FileNotFoundError(f"Historical season directory not found: {season_dir}")
                        snap = build_historical_snapshot(season_dir, gw)
                        h_len = 1 if mode == "free_hit" else max(1, min(8, horizon))
                        players_map, _ = load_historical_players_meta(snap, season_dir, horizon=h_len)

                        if budget is not None:
                            budget_tenths = int(round(budget * 10))
                        elif mode == "initial":
                            budget_tenths = 1000
                        elif session_id:
                            sim_dir = self.config_dir / "simulations"
                            sim = HistoricalSimulationSession.load(session_id, config_dir=sim_dir)
                            squad_selling_value = sum(
                                selling_price(sim.purchase_prices_tenths.get(str(p_id), players_map[p_id].price_tenths if p_id in players_map else 50), players_map[p_id].price_tenths)
                                for p_id in sim.squad_ids
                                if p_id in players_map
                            )
                            budget_tenths = sim.bank_tenths + squad_selling_value
                        else:
                            budget_tenths = 1000

                        target_gws = list(range(gw, min(39, gw + h_len)))
                        effective_constraints = StrategicConstraints(
                            budget_tenths=budget_tenths,
                            locked_player_ids=set(locked_ids),
                            excluded_player_ids=set(excluded_ids),
                            preferred_player_ids=set(preferred_ids),
                            target_gameweeks=tuple(target_gws),
                        )
                        candidate_pool = [
                            p for p in players_map.values()
                            if p.status in ("a", "d") and not getattr(p, "is_long_term_unavailable", False)
                        ]
                        primary_candidate = solve_strategic_squad(
                            candidate_pool=candidate_pool,
                            constraints=effective_constraints,
                            strategy=strategy,
                            mode=mode,
                            horizon=h_len,
                        )
                        rep = primary_candidate.to_dict()
                        rep["selected_candidate"] = primary_candidate.to_dict()
                        rep["mode"] = mode
                        rep["strategy"] = strategy
                        rep["horizon"] = h_len
                        rep["budget_millions"] = budget_tenths / 10.0
                        rep["bank_remaining_tenths"] = primary_candidate.bank_remaining_tenths

                        failed_profiles_map: dict[str, str] = {}
                        all_cands = generate_strategic_candidates(
                            candidate_pool=candidate_pool,
                            constraints=effective_constraints,
                            mode=mode,
                            horizon=h_len,
                            failed_profiles=failed_profiles_map,
                        )
                        rep["requested_profiles"] = getattr(all_cands, "requested_profiles", list(all_cands.keys()))
                        rep["successful_profiles"] = getattr(all_cands, "successful_profiles", list(all_cands.keys()))
                        rep["failed_profiles"] = failed_profiles_map
                        rep["strategic_candidates"] = {
                            s: cand.to_dict() for s, cand in all_cands.items()
                        }
                        rep["candidates"] = [cand.to_dict() for cand in all_cands.values()]
                        rep["season"] = season
                        rep["session_id"] = session_id
                    else:
                        squad_path = get_team_squad_path(tid, self.config_dir)
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
                season = body.get("season")
                gw_val = body.get("gameweek")
                gw = int(gw_val) if gw_val is not None else 1
                session_id = body.get("session_id")
                tid = body.get("team_id") or get_active_team_id(self.config_dir)
                prev_cand_data = body.get("previous_candidate", {})
                mode = body.get("mode") or prev_cand_data.get("mode", "initial")
                horizon = int(body.get("horizon") or len(prev_cand_data.get("horizon_gws", [1, 2, 3, 4, 5])))
                strategy = body.get("strategy") or prev_cand_data.get("strategy", "balanced")
                budget = float(body.get("budget")) if body.get("budget") is not None else None
                locked_ids = [int(i) for i in body.get("locked_player_ids", [])]
                excluded_ids = [int(i) for i in body.get("excluded_player_ids", [])]
                preferred_ids = [int(i) for i in body.get("preferred_player_ids", [])]

                h_len = max(1, min(8, horizon))
                if season:
                    hist_dir = PROJECT_ROOT / "data" / "historical"
                    season_dir = hist_dir / season
                    if not season_dir.exists():
                        raise FileNotFoundError(f"Historical season directory not found: {season_dir}")
                    snap = build_historical_snapshot(season_dir, gw)
                    players_map, _ = load_historical_players_meta(snap, season_dir, horizon=h_len)
                    target_gws = list(range(gw, min(39, gw + h_len)))

                    if budget is not None:
                        budget_tenths = int(round(budget * 10))
                    elif mode == "initial":
                        budget_tenths = 1000
                    elif session_id:
                        sim_dir = self.config_dir / "simulations"
                        sim = HistoricalSimulationSession.load(session_id, config_dir=sim_dir)
                        squad_selling_value = sum(
                            selling_price(sim.purchase_prices_tenths.get(str(p_id), players_map[p_id].price_tenths if p_id in players_map else 50), players_map[p_id].price_tenths)
                            for p_id in sim.squad_ids
                            if p_id in players_map
                        )
                        budget_tenths = sim.bank_tenths + squad_selling_value
                    else:
                        budget_tenths = 1000
                else:
                    squad_path = get_team_squad_path(tid, self.config_dir)
                    store = SnapshotStore(self.database_path)
                    start_gw = get_current_gameweek(store)
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
                candidate_pool = [
                    p for p in players_map.values()
                    if p.status in ("a", "d") and not getattr(p, "is_long_term_unavailable", False)
                ]
                new_cand = solve_strategic_squad(
                    candidate_pool=candidate_pool,
                    constraints=constraints,
                    strategy=strategy,
                    mode=mode,
                    horizon=h_len,
                )

                failed_profiles_map: dict[str, str] = {}
                all_cands = generate_strategic_candidates(
                    candidate_pool=candidate_pool,
                    constraints=constraints,
                    mode=mode,
                    horizon=h_len,
                    failed_profiles=failed_profiles_map,
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
                res["strategic_candidates"] = {
                    s: cand.to_dict() for s, cand in all_cands.items()
                }
                res["candidates"] = [cand.to_dict() for cand in all_cands.values()]
                res["failed_profiles"] = failed_profiles_map
                self._send_json(res)
            elif path == "/api/strategic-squad/apply":
                season = body.get("season")
                session_id = body.get("session_id")
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

                is_historical = bool(session_id or (season and "-" in season and len(season) == 7))
                if is_historical:
                    sim_dir = self.config_dir / "simulations"
                    target_session_id = session_id
                    if not target_session_id:
                        # Find active or first simulation matching season
                        active_sims = HistoricalSimulationSession.list_sessions(sim_dir)
                        matched = [s for s in active_sims if s.get("season") == season]
                        if matched:
                            target_session_id = matched[0]["session_id"]
                    if target_session_id and (sim_dir / f"{target_session_id}.json").exists():
                        sim = HistoricalSimulationSession.load(target_session_id, config_dir=sim_dir)
                        hist_dir = PROJECT_ROOT / "data" / "historical"
                        season_dir = hist_dir / (season or sim.season)
                        snap = build_historical_snapshot(season_dir, sim.current_gw)
                        price_map = {p.player_id: p.price_tenths for p in snap.players}
                        players_map = {p.player_id: p for p in snap.players}
                        norm_mode = (mode or "initial").lower().strip()

                        old_squad = list(sim.squad_ids)
                        outs = [pid for pid in old_squad if pid not in squad_ids]
                        ins = [pid for pid in squad_ids if pid not in old_squad]

                        # Pair transfers by position
                        staged_list = []
                        if outs and ins:
                            remaining_outs = list(outs)
                            remaining_ins = list(ins)
                            pos_order = [Position.GOALKEEPER, Position.DEFENDER, Position.MIDFIELDER, Position.FORWARD]
                            for pos in pos_order:
                                p_outs = [p for p in remaining_outs if players_map.get(p) and players_map[p].position == pos]
                                p_ins = [p for p in remaining_ins if players_map.get(p) and players_map[p].position == pos]
                                for o_id, i_id in zip(p_outs, p_ins):
                                    remaining_outs.remove(o_id)
                                    remaining_ins.remove(i_id)
                                    o_p = players_map.get(o_id)
                                    i_p = players_map.get(i_id)
                                    p_price = sim.purchase_prices_tenths.get(str(o_id), o_p.price_tenths if o_p else 50)
                                    s_price = selling_price(p_price, o_p.price_tenths if o_p else 50)
                                    i_price = i_p.price_tenths if i_p else 50
                                    staged_list.append({
                                        "out_id": o_id,
                                        "in_id": i_id,
                                        "out_name": o_p.web_name if o_p else f"Player {o_id}",
                                        "in_name": i_p.web_name if i_p else f"Player {i_id}",
                                        "cost_tenths": i_price - s_price,
                                        "out_selling_price_tenths": s_price,
                                        "in_price_tenths": i_price,
                                    })
                            for o_id, i_id in zip(remaining_outs, remaining_ins):
                                o_p = players_map.get(o_id)
                                i_p = players_map.get(i_id)
                                p_price = sim.purchase_prices_tenths.get(str(o_id), o_p.price_tenths if o_p else 50)
                                s_price = selling_price(p_price, o_p.price_tenths if o_p else 50)
                                i_price = i_p.price_tenths if i_p else 50
                                staged_list.append({
                                    "out_id": o_id,
                                    "in_id": i_id,
                                    "out_name": o_p.web_name if o_p else f"Player {o_id}",
                                    "in_name": i_p.web_name if i_p else f"Player {i_id}",
                                    "cost_tenths": i_price - s_price,
                                    "out_selling_price_tenths": s_price,
                                    "in_price_tenths": i_price,
                                })

                        chip_played = None
                        if norm_mode in ("wildcard", "wc"):
                            chip_played = sim.play_chip("wildcard")
                        elif norm_mode in ("freehit", "free_hit", "fh"):
                            chip_played = sim.play_chip("free_hit")
                            if not sim.pre_free_hit_state:
                                sim.pre_free_hit_state = {
                                    "squad_ids": list(old_squad),
                                    "purchase_prices_tenths": dict(sim.purchase_prices_tenths),
                                    "bank_tenths": sim.bank_tenths,
                                }

                        sim.squad_ids = list(squad_ids)
                        sim.starting_ids = list(starter_ids)
                        sim.bench_ids = list(bench_ids)
                        sim.captain_id = cap_id
                        sim.vice_captain_id = vc_id
                        sim.purchase_prices_tenths = {
                            str(pid): (sim.purchase_prices_tenths.get(str(pid)) if pid in old_squad else price_map.get(pid, 50))
                            for pid in squad_ids
                        }
                        sim.bank_tenths = bank_tenths

                        if norm_mode == "initial" and sim.current_gw == 1:
                            staged_list = []
                        else:
                            for st in staged_list:
                                st["already_applied"] = True

                        sim.transfers_staged = staged_list

                        strategy_lbl = cand_data.get("strategy", "strategic").upper()
                        notes_lbl = f"Applied {chip_played.upper()} squad from Strategic Studio ({strategy_lbl})" if chip_played else f"Initial squad selection from Strategic Studio ({strategy_lbl})"

                        cap_p = players_map.get(cap_id)
                        vc_p = players_map.get(vc_id)
                        dec_obj = {
                            "gameweek": sim.current_gw,
                            "season": sim.season,
                            "session_id": sim.session_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "chip_played": chip_played,
                            "transfer_hits": 0,
                            "transfers": [
                                {
                                    "outgoing_id": st["out_id"],
                                    "incoming_id": st["in_id"],
                                    "outgoing_name": st["out_name"],
                                    "incoming_name": st["in_name"],
                                    "selling_price_tenths": st["out_selling_price_tenths"],
                                    "purchase_price_tenths": st["in_price_tenths"],
                                }
                                for st in staged_list
                            ],
                            "squad_player_ids": list(squad_ids),
                            "starting_player_ids": list(starter_ids),
                            "bench_player_ids": list(bench_ids),
                            "captain_id": cap_id,
                            "captain_name": cap_p.web_name if cap_p else f"ID {cap_id}",
                            "vice_captain_id": vc_id,
                            "vice_captain_name": vc_p.web_name if vc_p else f"ID {vc_id}",
                            "predicted_lineup_xp": round(float(cand_data.get("predicted_lineup_xp") or cand_data.get("start_gw_lineup_xp") or 0.0), 2),
                            "notes": notes_lbl,
                        }

                        if norm_mode in ("initial", "init", "start") or sim.current_gw == 1:
                            sim.initial_decision = dict(dec_obj)

                        existing_entry = next((h for h in sim.history if h.get("gameweek") == sim.current_gw), None)
                        if existing_entry:
                            existing_entry["decision_logged"] = dec_obj
                            existing_entry["decision"] = dec_obj
                            if chip_played:
                                existing_entry["chip_used"] = chip_played
                        else:
                            sim.history.append({
                                "gameweek": sim.current_gw,
                                "type": "strategic_decision",
                                "decision_logged": dec_obj,
                                "decision": dec_obj,
                                "chip_used": chip_played,
                            })

                        sim.save()
                        self._send_json({
                            "success": True,
                            "session_id": sim.session_id,
                            "squad": sim.get_squad_player_details(),
                            "bank_tenths": sim.bank_tenths,
                            "active_chip": sim.active_chip,
                            "transfers_staged": sim.transfers_staged,
                            "message": f"Successfully applied {norm_mode.upper()} squad ({len(staged_list)} transfers, chip: {chip_played or 'None'})",
                        })
                    else:
                        raise ValueError(f"No active simulation session found for season '{season}' to apply squad.")
                else:
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
            elif path == "/api/historical/simulations/create":
                import time
                sim_id = body.get("session_id") or f"sim_{body.get('season', '2023-24').replace('-', '_')}_{int(time.time())}"
                season = body.get("season", "2023-24")
                start_gw = int(body.get("start_gw", 1))
                strategy = body.get("starting_strategy", "v1.3.5")
                manager_name = body.get("manager_name", "Human Manager")
                sim_dir = self.config_dir / "simulations"
                sim = HistoricalSimulationSession.create(
                    session_id=sim_id,
                    season=season,
                    start_gw=start_gw,
                    starting_strategy=strategy,
                    manager_name=manager_name,
                    config_dir=sim_dir,
                )
                self._send_json({
                    "session_id": sim.session_id,
                    "season": sim.season,
                    "current_gw": sim.current_gw,
                    "status": sim.status,
                    "squad": sim.get_squad_player_details(),
                    "bank_tenths": sim.bank_tenths,
                    "free_transfers": sim.free_transfers,
                    "chips_remaining": sim.chips_remaining,
                    "history": sim.history,
                })
            elif path.startswith("/api/historical/simulations/"):
                sim_dir = self.config_dir / "simulations"
                sub = path[len("/api/historical/simulations/"):].strip("/")
                parts = sub.split("/")
                session_id = parts[0]
                action = parts[1] if len(parts) > 1 else ""
                sim = HistoricalSimulationSession.load(session_id, config_dir=sim_dir)

                if action == "transfers":
                    sub_action = body.get("action")
                    if sub_action == "clear":
                        sim.clear_staged_transfers()
                        res = {"transfers_staged": []}
                    elif "transfers" in body and isinstance(body["transfers"], list):
                        staged = sim.stage_transfers_batch(body["transfers"])
                        res = {"staged": staged, "transfers_staged": sim.transfers_staged}
                    else:
                        out_id = int(body.get("out_id"))
                        in_id = int(body.get("in_id"))
                        staged = sim.stage_transfer(out_id, in_id)
                        res = {"staged": staged, "transfers_staged": sim.transfers_staged}
                    res["bank_tenths"] = sim.bank_tenths
                    res["bank_fmt"] = f"£{sim.bank_tenths / 10:.1f}m"
                    res["free_transfers"] = max(0, sim.free_transfers - len(sim.transfers_staged))
                    res["squad"] = sim.get_squad_player_details()
                    self._send_json(res)
                elif action == "lineup":
                    starters = [int(x) for x in body.get("starting_ids", [])]
                    bench = [int(x) for x in body.get("bench_ids", [])]
                    cap = int(body.get("captain_id"))
                    vc = int(body.get("vice_captain_id"))
                    sim.set_lineup(starters, bench, cap, vc)
                    self._send_json({"success": True, "squad": sim.get_squad_player_details()})
                elif action == "chip":
                    chip_name = body.get("chip")
                    if chip_name:
                        act = sim.play_chip(chip_name)
                    else:
                        sim.cancel_chip()
                        act = None
                    self._send_json({"active_chip": act})
                elif action == "run-gw":
                    res = sim.run_gameweek()
                    self._send_json({
                        "resolution": res,
                        "session": {
                            "session_id": sim.session_id,
                            "season": sim.season,
                            "current_gw": sim.current_gw,
                            "status": sim.status,
                            "is_completed": sim.is_completed,
                            "bank_tenths": sim.bank_tenths,
                            "free_transfers": sim.free_transfers,
                            "chips_remaining": sim.chips_remaining,
                            "chips_used": sim.chips_used,
                            "squad": sim.get_squad_player_details(),
                            "history": sim.history,
                            "total_net_points": sum(h.get("net_points", 0) for h in sim.history),
                        }
                    })
                else:
                    self._send_error_json(f"Unknown simulation action '{action}'", status=404)
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
            elif path.startswith("/api/historical/simulations/"):
                sid = path[len("/api/historical/simulations/"):].strip("/")
                sim_dir = self.config_dir / "simulations"
                sim_file = sim_dir / f"{sid}.json"
                if sim_file.exists():
                    sim_file.unlink()
                    self._send_json({"success": True, "deleted_session_id": sid})
                else:
                    self._send_error_json(f"Simulation session '{sid}' not found", status=404)
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
