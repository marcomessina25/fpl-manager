"""Historical Simulation Session state engine (V1.4).

Maintains strict point-in-time isolation:
- Sessions are saved in `config/simulations/<session_id>.json`.
- Never modifies `config/current_squad.json` or live database files.
- Operates strictly with historical snapshots before gameweek N deadline.
- Evaluates matchday outcomes strictly using ground-truth post-gameweek files.
- Records parallel frozen engine decisions for human-in-the-loop benchmark comparison.
"""

from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any

from ..backtest.decision_engine import BaseDecisionEngine, resolve_decision_engine
from ..backtest.engine import select_best_lineup, simulate_autosubs_and_score
from ..chip_strategy import SeasonalChipInventory, SeasonalChipPolicy
from ..errors import DataIntegrityError
from ..expected_points import ExpectedPointsProjection
from ..historical.models import GameweekOutcome, HistoricalGameweekSnapshot, Position
from ..historical.reconstruction import reconstruct_features_and_project
from ..historical.snapshots import build_historical_snapshot, load_gameweek_outcomes
from ..rules import MIN_STARTING_QUOTAS, SQUAD_QUOTAS, SQUAD_SIZE
from ..transfers import selling_price
from .models import GameweekResolution, SimulationSummary, StagedTransfer

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SIMULATIONS_DIR = PROJECT_ROOT / "config" / "simulations"
DEFAULT_HISTORICAL_DIR = PROJECT_ROOT / "data" / "historical"
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "reports" / "simulations"


class HistoricalSimulationSession:
    """Represents a stateful, interactive historical FPL simulation."""

    def __init__(
        self,
        session_id: str,
        season: str,
        current_gw: int = 1,
        status: str = "active",
        squad_ids: list[int] | None = None,
        purchase_prices_tenths: dict[str, int] | None = None,
        bank_tenths: int = 0,
        free_transfers: int = 1,
        chips_remaining: list[str] | None = None,
        chips_used: dict[str, int] | None = None,
        active_chip: str | None = None,
        pre_free_hit_state: dict[str, Any] | None = None,
        starting_ids: list[int] | None = None,
        bench_ids: list[int] | None = None,
        captain_id: int = 0,
        vice_captain_id: int = 0,
        transfers_staged: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        engine_baseline_squad_ids: list[int] | None = None,
        engine_baseline_purchase_prices: dict[str, int] | None = None,
        engine_baseline_bank_tenths: int = 0,
        engine_baseline_free_transfers: int = 1,
        engine_baseline_history: list[dict[str, Any]] | None = None,
        engine_baseline_chips_remaining: list[str] | None = None,
        engine_baseline_chips_used: dict[str, int] | None = None,
        engine_baseline_version: str = "v1.3.5",
        experiment_metadata: dict[str, Any] | None = None,
        config_dir: Path | None = None,
        historical_dir: Path | None = None,
    ) -> None:
        self.session_id = session_id
        self.season = season
        self.current_gw = current_gw
        self.status = status
        self.squad_ids = list(squad_ids or [])
        self.purchase_prices_tenths = dict(purchase_prices_tenths or {})
        self.bank_tenths = bank_tenths
        self.free_transfers = free_transfers
        self.chips_remaining = list(
            chips_remaining
            if chips_remaining is not None
            else ["wildcard_1", "wildcard_2", "free_hit", "bench_boost", "triple_captain"]
        )
        self.chips_used = dict(chips_used or {})
        self.active_chip = active_chip
        self.pre_free_hit_state = pre_free_hit_state
        self.starting_ids = list(starting_ids or [])
        self.bench_ids = list(bench_ids or [])
        self.captain_id = captain_id
        self.vice_captain_id = vice_captain_id
        self.transfers_staged = list(transfers_staged or [])
        self.history = list(history or [])

        # Parallel baseline engine tracking (frozen v1.3.5 default, or specified version)
        self.engine_baseline_version = engine_baseline_version
        self.engine_baseline_squad_ids = list(engine_baseline_squad_ids or self.squad_ids)
        self.engine_baseline_purchase_prices = dict(engine_baseline_purchase_prices or self.purchase_prices_tenths)
        self.engine_baseline_bank_tenths = engine_baseline_bank_tenths
        self.engine_baseline_free_transfers = engine_baseline_free_transfers
        self.engine_baseline_history = list(engine_baseline_history or [])
        self.engine_baseline_chips_remaining = list(
            engine_baseline_chips_remaining
            if engine_baseline_chips_remaining is not None
            else ["wildcard_1", "wildcard_2", "free_hit", "bench_boost", "triple_captain"]
        )
        self.engine_baseline_chips_used = dict(engine_baseline_chips_used or {})

        self.experiment_metadata = dict(experiment_metadata or {})
        self.config_dir = config_dir or DEFAULT_SIMULATIONS_DIR
        self.historical_dir = historical_dir or DEFAULT_HISTORICAL_DIR

    @property
    def max_free_transfers(self) -> int:
        """Season-specific maximum free transfers cap (5 for 2024-25+, 2 earlier)."""
        return 5 if self.season >= "2024-25" else 2

    @property
    def is_completed(self) -> bool:
        return self.status == "completed" or self.current_gw > 38

    # -------------------------------------------------------------------------
    # Factory & Storage
    # -------------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        session_id: str,
        season: str,
        start_gw: int = 1,
        starting_strategy: str = "v1.2.5",
        initial_squad_ids: list[int] | None = None,
        budget_tenths: int = 1000,
        manager_name: str = "Human Manager",
        config_dir: Path | None = None,
        historical_dir: Path | None = None,
    ) -> "HistoricalSimulationSession":
        """Create and initialize a new historical simulation session."""
        hist_dir = historical_dir or DEFAULT_HISTORICAL_DIR
        season_dir = hist_dir / season
        if not season_dir.exists():
            raise FileNotFoundError(f"Season directory not found: {season_dir}")

        snapshot_gw1 = build_historical_snapshot(season_dir, start_gw)
        projections_gw1 = reconstruct_features_and_project(snapshot_gw1)
        players_by_id = {p.player_id: p for p in snapshot_gw1.players}

        # Initialize squad: either custom or via baseline decision engine
        if initial_squad_ids:
            if len(initial_squad_ids) != SQUAD_SIZE:
                raise ValueError(f"Squad must contain exactly {SQUAD_SIZE} players.")
            squad_ids = list(initial_squad_ids)
            total_cost = sum(players_by_id[pid].price_tenths for pid in squad_ids)
            if total_cost > budget_tenths:
                raise ValueError(f"Squad cost (£{total_cost/10:.1f}m) exceeds budget (£{budget_tenths/10:.1f}m).")
            purchase_prices = {str(pid): players_by_id[pid].price_tenths for pid in squad_ids}
            bank = budget_tenths - total_cost
        else:
            engine = resolve_decision_engine(starting_strategy)
            squad_ids, purchase_prices_int, bank = engine.initialize_squad(
                snapshot=snapshot_gw1,
                projections=projections_gw1,
                budget_tenths=budget_tenths,
            )
            purchase_prices = {str(k): v for k, v in purchase_prices_int.items()}

        # Select initial lineup & captain
        starters, bench, cap, vc, _ = select_best_lineup(squad_ids, projections_gw1)

        # Baseline engine parallel state
        baseline_squad = list(squad_ids)
        baseline_prices = dict(purchase_prices)
        baseline_bank = bank

        meta = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "manager_name": manager_name,
            "starting_strategy": starting_strategy,
            "starting_policy": "custom" if initial_squad_ids else "engine_baseline",
            "frozen_engine_version": "v1.3.5",
        }

        session = cls(
            session_id=session_id,
            season=season,
            current_gw=start_gw,
            status="active",
            squad_ids=squad_ids,
            purchase_prices_tenths=purchase_prices,
            bank_tenths=bank,
            free_transfers=1,
            starting_ids=starters,
            bench_ids=bench,
            captain_id=cap,
            vice_captain_id=vc,
            engine_baseline_version="v1.3.5",
            engine_baseline_squad_ids=baseline_squad,
            engine_baseline_purchase_prices=baseline_prices,
            engine_baseline_bank_tenths=baseline_bank,
            engine_baseline_free_transfers=1,
            experiment_metadata=meta,
            config_dir=config_dir,
            historical_dir=historical_dir,
        )
        session.save()
        return session

    def save(self) -> Path:
        """Persist session state to isolated JSON file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.config_dir / f"{self.session_id}.json"
        data = {
            "session_id": self.session_id,
            "season": self.season,
            "current_gw": self.current_gw,
            "status": self.status,
            "squad_ids": self.squad_ids,
            "purchase_prices_tenths": self.purchase_prices_tenths,
            "bank_tenths": self.bank_tenths,
            "free_transfers": self.free_transfers,
            "chips_remaining": self.chips_remaining,
            "chips_used": self.chips_used,
            "active_chip": self.active_chip,
            "pre_free_hit_state": self.pre_free_hit_state,
            "starting_ids": self.starting_ids,
            "bench_ids": self.bench_ids,
            "captain_id": self.captain_id,
            "vice_captain_id": self.vice_captain_id,
            "transfers_staged": self.transfers_staged,
            "history": self.history,
            "engine_baseline_version": self.engine_baseline_version,
            "engine_baseline_squad_ids": self.engine_baseline_squad_ids,
            "engine_baseline_purchase_prices": self.engine_baseline_purchase_prices,
            "engine_baseline_bank_tenths": self.engine_baseline_bank_tenths,
            "engine_baseline_free_transfers": self.engine_baseline_free_transfers,
            "engine_baseline_chips_remaining": self.engine_baseline_chips_remaining,
            "engine_baseline_chips_used": self.engine_baseline_chips_used,
            "engine_baseline_history": self.engine_baseline_history,
            "experiment_metadata": self.experiment_metadata,
        }
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return file_path

    @classmethod
    def load(
        cls,
        session_id: str,
        config_dir: Path | None = None,
        historical_dir: Path | None = None,
    ) -> "HistoricalSimulationSession":
        """Load session from its isolated JSON file."""
        c_dir = config_dir or DEFAULT_SIMULATIONS_DIR
        file_path = c_dir / f"{session_id}.json"
        if not file_path.exists():
            raise FileNotFoundError(f"Simulation session file not found: {file_path}")
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return cls(
            session_id=data["session_id"],
            season=data["season"],
            current_gw=data.get("current_gw", 1),
            status=data.get("status", "active"),
            squad_ids=data.get("squad_ids", []),
            purchase_prices_tenths=data.get("purchase_prices_tenths", {}),
            bank_tenths=data.get("bank_tenths", 0),
            free_transfers=data.get("free_transfers", 1),
            chips_remaining=data.get("chips_remaining"),
            chips_used=data.get("chips_used", {}),
            active_chip=data.get("active_chip"),
            pre_free_hit_state=data.get("pre_free_hit_state"),
            starting_ids=data.get("starting_ids", []),
            bench_ids=data.get("bench_ids", []),
            captain_id=data.get("captain_id", 0),
            vice_captain_id=data.get("vice_captain_id", 0),
            transfers_staged=data.get("transfers_staged", []),
            history=data.get("history", []),
            engine_baseline_version=data.get("engine_baseline_version", "v1.3.5"),
            engine_baseline_squad_ids=data.get("engine_baseline_squad_ids"),
            engine_baseline_purchase_prices=data.get("engine_baseline_purchase_prices"),
            engine_baseline_bank_tenths=data.get("engine_baseline_bank_tenths", 0),
            engine_baseline_free_transfers=data.get("engine_baseline_free_transfers", 1),
            engine_baseline_chips_remaining=data.get("engine_baseline_chips_remaining"),
            engine_baseline_chips_used=data.get("engine_baseline_chips_used", {}),
            engine_baseline_history=data.get("engine_baseline_history", []),
            experiment_metadata=data.get("experiment_metadata", {}),
            config_dir=c_dir,
            historical_dir=historical_dir,
        )

    @classmethod
    def list_sessions(cls, config_dir: Path | None = None) -> list[dict[str, Any]]:
        """List all available historical simulation sessions."""
        c_dir = config_dir or DEFAULT_SIMULATIONS_DIR
        if not c_dir.exists():
            return []
        sessions: list[dict[str, Any]] = []
        for p in c_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data.get("session_id", p.stem),
                    "season": data.get("season"),
                    "current_gw": data.get("current_gw"),
                    "status": data.get("status"),
                    "gameweeks_completed": len(data.get("history", [])),
                    "total_net_points": sum(h.get("net_points", 0) for h in data.get("history", [])),
                    "created_at": data.get("experiment_metadata", {}).get("created_at"),
                    "manager_name": data.get("experiment_metadata", {}).get("manager_name", "Human"),
                })
            except json.JSONDecodeError as err:
                LOGGER.error("Corrupt session JSON in %s: %s", p, err)
                continue
            except Exception as err:
                LOGGER.warning("Failed to load session %s: %s", p.stem, err)
                continue
        sessions.sort(key=lambda s: s.get("created_at") or "", reverse=True)
        return sessions

    # -------------------------------------------------------------------------
    # Squad State & Point-in-Time Snapshot
    # -------------------------------------------------------------------------

    def get_current_snapshot(self) -> HistoricalGameweekSnapshot:
        """Point-in-time snapshot strictly knowable before current gameweek deadline."""
        season_dir = self.historical_dir / self.season
        return build_historical_snapshot(season_dir, self.current_gw)

    def get_squad_player_details(self) -> list[dict[str, Any]]:
        """Get rich player details for current squad at the current historical deadline."""
        snapshot = self.get_current_snapshot()
        players_map = {p.player_id: p for p in snapshot.players}
        teams_map = {t["team_id"]: t for t in snapshot.teams}

        result: list[dict[str, Any]] = []
        for pid in self.squad_ids:
            p = players_map.get(pid)
            if not p:
                continue
            t_info = teams_map.get(p.team_id, {})
            purch_price = self.purchase_prices_tenths.get(str(pid), p.price_tenths)
            curr_sell_price = selling_price(purch_price, p.price_tenths)

            pos_abbr = {
                Position.GOALKEEPER: "GKP",
                Position.DEFENDER: "DEF",
                Position.MIDFIELDER: "MID",
                Position.FORWARD: "FWD",
            }.get(p.position, "MID")

            result.append({
                "player_id": pid,
                "name": p.web_name,
                "position": p.position.name,
                "pos_abbr": pos_abbr,
                "team_id": p.team_id,
                "team_name": t_info.get("name", f"Team {p.team_id}"),
                "team_short": t_info.get("short_name", f"T{p.team_id}"),
                "current_price_tenths": p.price_tenths,
                "purchase_price_tenths": purch_price,
                "selling_price_tenths": curr_sell_price,
                "current_price_fmt": f"£{p.price_tenths/10:.1f}m",
                "selling_price_fmt": f"£{curr_sell_price/10:.1f}m",
                "total_points": p.total_points,
                "form": p.form,
                "status": p.status,
                "is_starter": pid in self.starting_ids,
                "is_bench": pid in self.bench_ids,
                "bench_order": self.bench_ids.index(pid) + 1 if pid in self.bench_ids else None,
                "is_captain": pid == self.captain_id,
                "is_vice_captain": pid == self.vice_captain_id,
            })
        return result

    # -------------------------------------------------------------------------
    # Staging Transfers & Lineup
    # -------------------------------------------------------------------------

    def stage_transfer(self, out_id: int, in_id: int) -> dict[str, Any]:
        """Stage a single transfer, validating legality against current snapshot."""
        if self.is_completed:
            raise RuntimeError("Simulation is already completed.")

        if out_id not in self.squad_ids:
            raise ValueError(f"Player {out_id} is not in the current squad.")
        if in_id in self.squad_ids:
            raise ValueError(f"Player {in_id} is already in the current squad.")

        snapshot = self.get_current_snapshot()
        players_map = {p.player_id: p for p in snapshot.players}

        out_p = players_map.get(out_id)
        in_p = players_map.get(in_id)
        if not out_p or not in_p:
            raise ValueError("Player not found in historical snapshot.")

        if out_p.position != in_p.position:
            raise ValueError(
                f"Position mismatch: cannot transfer {out_p.position.name} for {in_p.position.name}."
            )

        # Calculate finances
        purch_price = self.purchase_prices_tenths.get(str(out_id), out_p.price_tenths)
        sell_p = selling_price(purch_price, out_p.price_tenths)
        cost_delta = in_p.price_tenths - sell_p

        # Check budget with existing staged transfers
        curr_bank = self.bank_tenths
        # deduct/add previous staged transfers
        for st in self.transfers_staged:
            curr_bank -= st.get("cost_tenths", 0)

        if curr_bank - cost_delta < 0:
            raise ValueError(
                f"Insufficient funds: transfer requires £{cost_delta/10:.1f}m, "
                f"available bank is £{curr_bank/10:.1f}m."
            )

        # Check team quota (max 3 players from any club)
        temp_squad = [pid for pid in self.squad_ids if pid != out_id] + [in_id]
        club_counts: dict[int, int] = {}
        for pid in temp_squad:
            p_obj = players_map.get(pid)
            if p_obj:
                club_counts[p_obj.team_id] = club_counts.get(p_obj.team_id, 0) + 1
                if club_counts[p_obj.team_id] > 3:
                    raise ValueError(f"Club player limit exceeded: max 3 players allowed per Premier League club.")

        staged_obj = {
            "out_id": out_id,
            "in_id": in_id,
            "out_name": out_p.web_name,
            "in_name": in_p.web_name,
            "cost_tenths": cost_delta,
            "out_selling_price_tenths": sell_p,
            "in_price_tenths": in_p.price_tenths,
        }
        self.transfers_staged.append(staged_obj)
        self.save()
        return staged_obj

    def clear_staged_transfers(self) -> None:
        """Clear all staged transfers for the upcoming deadline."""
        self.transfers_staged = []
        self.save()

    def set_lineup(
        self,
        starting_ids: list[int],
        bench_ids: list[int],
        captain_id: int,
        vice_captain_id: int,
    ) -> None:
        """Validate and set starting 11, bench, captain and vice-captain."""
        if len(starting_ids) != 11:
            raise ValueError(f"Starting lineup must contain exactly 11 players (got {len(starting_ids)}).")
        if len(bench_ids) != 4:
            raise ValueError(f"Bench must contain exactly 4 players (got {len(bench_ids)}).")

        all_15 = set(starting_ids + bench_ids)
        # Verify all players are in current squad (or staged incoming)
        squad_set = set(self.squad_ids)
        for st in self.transfers_staged:
            squad_set.discard(st["out_id"])
            squad_set.add(st["in_id"])

        if all_15 != squad_set:
            diff = all_15.symmetric_difference(squad_set)
            raise ValueError(f"Lineup does not match squad players: mismatch on {diff}")

        # Validate formation legality
        snapshot = self.get_current_snapshot()
        players_map = {p.player_id: p for p in snapshot.players}
        pos_counts: dict[Position, int] = {pos: 0 for pos in Position}
        for pid in starting_ids:
            p = players_map.get(pid)
            if p:
                pos_counts[p.position] += 1

        if pos_counts[Position.GOALKEEPER] != 1:
            raise ValueError(f"Formation must have exactly 1 goalkeeper, got {pos_counts[Position.GOALKEEPER]}.")
        if pos_counts[Position.DEFENDER] < 3:
            raise ValueError(f"Formation must have at least 3 defenders, got {pos_counts[Position.DEFENDER]}.")
        if pos_counts[Position.MIDFIELDER] < 2:
            raise ValueError(f"Formation must have at least 2 midfielders, got {pos_counts[Position.MIDFIELDER]}.")
        if pos_counts[Position.FORWARD] < 1:
            raise ValueError(f"Formation must have at least 1 forward, got {pos_counts[Position.FORWARD]}.")

        # Captaincy
        if captain_id not in starting_ids:
            raise ValueError("Captain must be in the starting 11.")
        if vice_captain_id not in starting_ids:
            raise ValueError("Vice-captain must be in the starting 11.")
        if captain_id == vice_captain_id:
            raise ValueError("Captain and vice-captain cannot be the same player.")

        self.starting_ids = list(starting_ids)
        self.bench_ids = list(bench_ids)
        self.captain_id = captain_id
        self.vice_captain_id = vice_captain_id
        self.save()

    def play_chip(self, chip_name: str) -> str:
        """Activate a chip for the upcoming gameweek."""
        norm = chip_name.strip().lower().replace("-", "_").replace(" ", "_")
        alias_map = {
            "wildcard": "wildcard_1" if self.current_gw <= 19 else "wildcard_2",
            "wildcard_1": "wildcard_1",
            "wildcard_2": "wildcard_2",
            "wc": "wildcard_1" if self.current_gw <= 19 else "wildcard_2",
            "freehit": "free_hit",
            "free_hit": "free_hit",
            "fh": "free_hit",
            "benchboost": "bench_boost",
            "bench_boost": "bench_boost",
            "bb": "bench_boost",
            "triplecaptain": "triple_captain",
            "triple_captain": "triple_captain",
            "tc": "triple_captain",
        }
        canonical = alias_map.get(norm)
        if not canonical:
            raise ValueError(f"Unknown chip '{chip_name}'.")

        if canonical not in self.chips_remaining:
            raise ValueError(f"Chip '{canonical}' is not available (already used or expired).")

        if canonical == "wildcard_1" and self.current_gw > 19:
            raise ValueError("First Wildcard can only be played in GW 1-19.")
        if canonical == "wildcard_2" and self.current_gw < 20:
            raise ValueError("Second Wildcard can only be played in GW 20-38.")

        self.active_chip = canonical
        self.save()
        return canonical

    def cancel_chip(self) -> None:
        """Deactivate the active chip."""
        self.active_chip = None
        self.save()

    # -------------------------------------------------------------------------
    # Recommendations from Frozen Baseline
    # -------------------------------------------------------------------------

    def get_recommendations(self) -> dict[str, Any]:
        """Generate point-in-time recommendations using frozen baseline engine and seasonal chip policy."""
        snapshot = self.get_current_snapshot()
        projections = reconstruct_features_and_project(snapshot)
        proj_map = {p.player_id: p for p in projections}

        engine_ver = getattr(self, "engine_baseline_version", "v1.3.5")
        engine = resolve_decision_engine(engine_ver)

        # 1. Evaluate chip recommendation via SeasonalChipPolicy (exact simulation alignment)
        chip_inventory = SeasonalChipInventory(
            wildcard_w1="wildcard_1" in self.chips_remaining,
            free_hit_w1="free_hit" in self.chips_remaining and self.current_gw <= 19,
            triple_captain_w1="triple_captain" in self.chips_remaining and self.current_gw <= 19,
            bench_boost_w1="bench_boost" in self.chips_remaining and self.current_gw <= 19,
            wildcard_w2="wildcard_2" in self.chips_remaining,
            free_hit_w2="free_hit" in self.chips_remaining and self.current_gw >= 20,
            triple_captain_w2="triple_captain" in self.chips_remaining and self.current_gw >= 20,
            bench_boost_w2="bench_boost" in self.chips_remaining and self.current_gw >= 20,
        )
        policy = SeasonalChipPolicy()
        starting_tuple = tuple(self.squad_ids) if not self.history else tuple(self.history[0].get("squad_ids_after", self.squad_ids))
        try:
            rec_chip = policy.evaluate_gameweek_chip(
                self.current_gw,
                chip_inventory,
                self.squad_ids,
                snapshot,
                projections,
                starting_tuple,
            )
        except Exception as err:
            LOGGER.warning("Chip policy evaluation failed in GW %d: %s", self.current_gw, err)
            rec_chip = None

        free_hits_active = (
            self.active_chip in ("wildcard_1", "wildcard_2", "free_hit")
            or (rec_chip is not None and rec_chip in ("wildcard", "free_hit"))
        )
        eff_fts = 999 if free_hits_active else self.free_transfers

        # Get optimal lineup on current squad
        best_starters, best_bench, best_cap, best_vc, best_xp = select_best_lineup(self.squad_ids, projections)

        # Decide recommended transfers
        purch_prices_int = {int(k): v for k, v in self.purchase_prices_tenths.items()}
        rec_transfers = engine.decide_transfers(
            strategy_name="balanced",
            current_squad_ids=self.squad_ids,
            purchase_prices=purch_prices_int,
            bank_tenths=self.bank_tenths,
            free_transfers=eff_fts,
            snapshot=snapshot,
            projections=projections,
        )

        players_map = {p.player_id: p for p in snapshot.players}
        transfer_details = [
            {
                "out_id": out_id,
                "in_id": in_id,
                "out_name": players_map[out_id].web_name if out_id in players_map else f"Player {out_id}",
                "in_name": players_map[in_id].web_name if in_id in players_map else f"Player {in_id}",
                "xp_gain": round(
                    (proj_map[in_id].expected_points if in_id in proj_map else 0.0)
                    - (proj_map[out_id].expected_points if out_id in proj_map else 0.0),
                    2,
                ),
            }
            for out_id, in_id in rec_transfers
        ]

        rec_opportunity = None
        if rec_chip:
            try:
                from .chip_optimizer import ChipOpportunityOptimizer

                opt = ChipOpportunityOptimizer(variant="c1_linear_decay")
                opps = opt.evaluate_all_opportunities(
                    gameweek=self.current_gw,
                    available_chips=[rec_chip],
                    squad_ids=self.squad_ids,
                    snapshot=snapshot,
                    projections=projections,
                    chips_used=self.chips_used,
                )
                if rec_chip in opps:
                    rec_opportunity = opps[rec_chip].to_dict()
            except Exception:
                pass

        return {
            "gameweek": self.current_gw,
            "engine_version": engine_ver,
            "recommended_chip": rec_chip,
            "recommended_chip_opportunity": rec_opportunity,
            "recommended_transfers": transfer_details,
            "recommended_starters": best_starters,
            "recommended_bench": best_bench,
            "recommended_captain": best_cap,
            "recommended_vice_captain": best_vc,
            "predicted_lineup_xp": best_xp,
        }

    # -------------------------------------------------------------------------
    # Gameweek Resolution & Step Engine
    # -------------------------------------------------------------------------

    def run_gameweek(self) -> dict[str, Any]:
        """Resolve the matchday deterministically and advance to next gameweek."""
        if self.is_completed:
            raise RuntimeError("Simulation is already completed.")

        gw = self.current_gw
        snapshot = self.get_current_snapshot()
        players_map = {p.player_id: p for p in snapshot.players}
        player_positions = {p.player_id: p.position for p in snapshot.players}

        # 1. Apply staged transfers
        is_free_chip = self.active_chip in ("wildcard_1", "wildcard_2", "free_hit")
        num_transfers = len(self.transfers_staged)
        extra_transfers = max(0, num_transfers - self.free_transfers) if not is_free_chip else 0
        hits_cost = extra_transfers * 4

        # If Free Hit, stash pre-free-hit state before applying transfers
        if self.active_chip == "free_hit" and not self.pre_free_hit_state:
            self.pre_free_hit_state = {
                "squad_ids": list(self.squad_ids),
                "purchase_prices_tenths": dict(self.purchase_prices_tenths),
                "bank_tenths": self.bank_tenths,
            }

        transfers_executed = []
        for st in self.transfers_staged:
            out_id = st["out_id"]
            in_id = st["in_id"]
            cost = st.get("cost_tenths", 0)

            # Update squad
            if out_id in self.squad_ids:
                idx = self.squad_ids.index(out_id)
                self.squad_ids[idx] = in_id
            self.bank_tenths -= cost
            self.purchase_prices_tenths.pop(str(out_id), None)
            self.purchase_prices_tenths[str(in_id)] = st.get("in_price_tenths", players_map[in_id].price_tenths)

            # Update lineup replacements
            if out_id in self.starting_ids:
                s_idx = self.starting_ids.index(out_id)
                self.starting_ids[s_idx] = in_id
            elif out_id in self.bench_ids:
                b_idx = self.bench_ids.index(out_id)
                self.bench_ids[b_idx] = in_id

            if self.captain_id == out_id:
                self.captain_id = in_id
            if self.vice_captain_id == out_id:
                self.vice_captain_id = in_id

            transfers_executed.append(st)

        # 2. Re-verify lineup legality
        if len(self.starting_ids) != 11 or len(self.bench_ids) != 4:
            # Fall back to optimal lineup selection on new squad
            projections = reconstruct_features_and_project(snapshot)
            self.starting_ids, self.bench_ids, self.captain_id, self.vice_captain_id, _ = select_best_lineup(
                self.squad_ids, projections
            )

        # 3. Matchday resolution using ground-truth outcomes
        season_dir = self.historical_dir / self.season
        outcomes = load_gameweek_outcomes(season_dir, gw)

        gross_points, autosubs_tuple, cap_promoted = simulate_autosubs_and_score(
            starting_ids=self.starting_ids,
            bench_ids=self.bench_ids,
            captain_id=self.captain_id,
            vice_captain_id=self.vice_captain_id,
            outcomes=outcomes,
            player_positions=player_positions,
            chip_used=self.active_chip,
        )

        net_points = gross_points - hits_cost
        effective_cap = self.vice_captain_id if cap_promoted else self.captain_id
        cap_mult = 3 if self.active_chip in ("triple_captain", "triplecaptain") else 2
        cap_outcome = outcomes.get(effective_cap)
        cap_pts = (cap_outcome.total_points * cap_mult) if cap_outcome else 0

        # Detailed player breakdown
        starters_breakdown = []
        for pid in self.starting_ids:
            out_obj = outcomes.get(pid)
            pts = out_obj.total_points if out_obj else 0
            if pid == effective_cap:
                pts *= cap_mult
            starters_breakdown.append({
                "player_id": pid,
                "name": players_map[pid].web_name if pid in players_map else f"Player {pid}",
                "points": pts,
                "minutes": out_obj.minutes if out_obj else 0,
                "is_captain": pid == self.captain_id,
                "is_vice_captain": pid == self.vice_captain_id,
                "is_effective_captain": pid == effective_cap,
            })

        bench_breakdown = []
        for pid in self.bench_ids:
            out_obj = outcomes.get(pid)
            pts = out_obj.total_points if out_obj else 0
            bench_breakdown.append({
                "player_id": pid,
                "name": players_map[pid].web_name if pid in players_map else f"Player {pid}",
                "points": pts,
                "minutes": out_obj.minutes if out_obj else 0,
            })

        autosubs_list = [
            {
                "out_id": s_out,
                "in_id": b_in,
                "out_name": players_map[s_out].web_name if s_out in players_map else f"Player {s_out}",
                "in_name": players_map[b_in].web_name if b_in in players_map else f"Player {b_in}",
            }
            for s_out, b_in in autosubs_tuple
        ]

        # 4. Parallel baseline execution (v1.2.5 frozen engine)
        engine_recs = self.get_recommendations()
        engine_net = self._step_baseline_engine(gw, snapshot, outcomes, player_positions)

        # Calculate divergence
        rec_transfer_pairs = {
            (t["out_id"], t["in_id"]) for t in engine_recs.get("recommended_transfers", [])
        }
        human_transfer_pairs = {(t["out_id"], t["in_id"]) for t in transfers_executed}
        transfers_differed = rec_transfer_pairs != human_transfer_pairs
        captain_differed = self.captain_id != engine_recs.get("recommended_captain")
        divergence = {
            "transfers_differed": transfers_differed,
            "captain_differed": captain_differed,
            "human_override": transfers_differed or captain_differed,
            "point_delta_vs_engine": net_points - (engine_net if engine_net is not None else net_points),
        }

        # Calculate squad value
        squad_value = sum(
            selling_price(self.purchase_prices_tenths.get(str(pid), players_map[pid].price_tenths), players_map[pid].price_tenths)
            for pid in self.squad_ids if pid in players_map
        ) + self.bank_tenths

        cum_net = sum(h.get("net_points", 0) for h in self.history) + net_points

        resolution = GameweekResolution(
            gameweek=gw,
            gross_points=gross_points,
            transfer_hits=hits_cost,
            net_points=net_points,
            cumulative_net_points=cum_net,
            captain_id=self.captain_id,
            vice_captain_id=self.vice_captain_id,
            effective_captain_id=effective_cap,
            captain_promoted=cap_promoted,
            captain_points=cap_pts,
            chip_used=self.active_chip,
            autosubs=autosubs_list,
            starters_points=starters_breakdown,
            bench_points=bench_breakdown,
            transfers_executed=transfers_executed,
            squad_ids_after=list(self.squad_ids),
            bank_tenths_after=self.bank_tenths,
            squad_value_tenths_after=squad_value,
            engine_recommendation=engine_recs,
            engine_net_points=engine_net,
            human_engine_divergence=divergence,
        )
        self.history.append(resolution.to_dict())

        # 5. Post-GW updates
        if self.active_chip:
            self.chips_used[self.active_chip] = gw
            if self.active_chip in self.chips_remaining:
                self.chips_remaining.remove(self.active_chip)

        # If Free Hit, revert squad state
        if self.active_chip == "free_hit" and self.pre_free_hit_state:
            self.squad_ids = list(self.pre_free_hit_state["squad_ids"])
            self.purchase_prices_tenths = dict(self.pre_free_hit_state["purchase_prices_tenths"])
            self.bank_tenths = self.pre_free_hit_state["bank_tenths"]
            self.pre_free_hit_state = None

        # Free transfer rollover
        if self.active_chip in ("wildcard_1", "wildcard_2", "free_hit"):
            self.free_transfers = 1
        else:
            used_fts = min(num_transfers, self.free_transfers)
            remaining_fts = self.free_transfers - used_fts
            self.free_transfers = min(self.max_free_transfers, remaining_fts + 1)

        self.transfers_staged = []
        self.active_chip = None

        # Advance gameweek
        if self.current_gw >= 38:
            self.status = "completed"
        else:
            self.current_gw += 1
            # Auto-align lineup for next GW if players were transferred
            try:
                next_snap = self.get_current_snapshot()
                next_proj = reconstruct_features_and_project(next_snap)
                self.starting_ids, self.bench_ids, self.captain_id, self.vice_captain_id, _ = select_best_lineup(
                    self.squad_ids, next_proj
                )
            except Exception as err:
                LOGGER.warning("Failed to auto-align lineup for GW %d: %s", self.current_gw, err)
                if "warnings" not in self.experiment_metadata:
                    self.experiment_metadata["warnings"] = []
                self.experiment_metadata["warnings"].append({
                    "gameweek": self.current_gw,
                    "issue": f"Lineup auto-update failed: {err}",
                })

        self.save()
        return resolution.to_dict()

    def _step_baseline_engine(
        self,
        gw: int,
        snapshot: HistoricalGameweekSnapshot,
        outcomes: dict[int, GameweekOutcome],
        player_positions: dict[int, Position],
    ) -> int:
        """Step the parallel frozen baseline engine on its own squad trajectory with chip execution."""
        engine_ver = getattr(self, "engine_baseline_version", "v1.3.5")
        engine = resolve_decision_engine(engine_ver)
        projections = reconstruct_features_and_project(snapshot)
        proj_map = {p.player_id: p for p in projections}
        players_by_id = {p.player_id: p for p in snapshot.players}

        # 1. Evaluate chip deployment via SeasonalChipPolicy
        chip_inventory = SeasonalChipInventory(
            wildcard_w1="wildcard_1" in self.engine_baseline_chips_remaining,
            free_hit_w1="free_hit" in self.engine_baseline_chips_remaining and gw <= 19,
            triple_captain_w1="triple_captain" in self.engine_baseline_chips_remaining and gw <= 19,
            bench_boost_w1="bench_boost" in self.engine_baseline_chips_remaining and gw <= 19,
            wildcard_w2="wildcard_2" in self.engine_baseline_chips_remaining,
            free_hit_w2="free_hit" in self.engine_baseline_chips_remaining and gw >= 20,
            triple_captain_w2="triple_captain" in self.engine_baseline_chips_remaining and gw >= 20,
            bench_boost_w2="bench_boost" in self.engine_baseline_chips_remaining and gw >= 20,
        )
        policy = SeasonalChipPolicy()
        starting_tuple = (
            tuple(self.engine_baseline_squad_ids)
            if not self.engine_baseline_history
            else tuple(self.engine_baseline_history[0].get("squad_ids", self.engine_baseline_squad_ids))
        )
        current_chip = policy.evaluate_gameweek_chip(
            gw,
            chip_inventory,
            self.engine_baseline_squad_ids,
            snapshot,
            projections,
            starting_tuple,
        )

        saved_squad_ids = None
        saved_prices = None
        saved_bank = None

        # Determine dynamic chip-aware bench weight
        eff_bench_weight = getattr(engine, "bench_weight", 0.15)
        is_dynamic_chip = engine.version in ("v1.2.5", "v1.3") or getattr(engine, "is_chip_aware", False) or engine.version.startswith("v1.3.5")
        if current_chip and is_dynamic_chip:
            if current_chip == "free_hit":
                eff_bench_weight = 0.05
            elif current_chip == "bench_boost":
                eff_bench_weight = 0.99
            elif "bench_boost" in chip_inventory.available_chips(gw):
                fixtures = getattr(snapshot, "fixtures", [])
                team_counts: dict[int, int] = {}
                for f in fixtures:
                    th = f.team_h if hasattr(f, "team_h") else f.get("team_h")
                    ta = f.team_a if hasattr(f, "team_a") else f.get("team_a")
                    if th:
                        team_counts[th] = team_counts.get(th, 0) + 1
                    if ta:
                        team_counts[ta] = team_counts.get(ta, 0) + 1
                if any(cnt >= 2 for cnt in team_counts.values()):
                    eff_bench_weight = 0.60

        if current_chip in ("wildcard", "free_hit"):
            if current_chip == "free_hit":
                saved_squad_ids = list(self.engine_baseline_squad_ids)
                saved_prices = dict(self.engine_baseline_purchase_prices)
                saved_bank = self.engine_baseline_bank_tenths

            selling_prices = {
                pid: self.engine_baseline_purchase_prices.get(str(pid), players_by_id[pid].price_tenths if pid in players_by_id else 50)
                + max(0, ((proj_map[pid].price_tenths if pid in proj_map else 50) - self.engine_baseline_purchase_prices.get(str(pid), 50)) // 2)
                for pid in self.engine_baseline_squad_ids
            }
            total_funds = self.engine_baseline_bank_tenths + sum(selling_prices.values())

            try:
                chip_mode = "free_hit" if current_chip == "free_hit" else None
                new_squad_ids, new_prices_int, new_bank = engine.initialize_squad(
                    snapshot, projections, budget_tenths=total_funds, bench_weight=eff_bench_weight, mode=chip_mode
                )
                if len(new_squad_ids) == 15:
                    old_set = set(self.engine_baseline_squad_ids)
                    new_set = set(new_squad_ids)
                    out_list = sorted(list(old_set - new_set))
                    in_list = sorted(list(new_set - old_set))
                    txs = list(zip(out_list, in_list))
                    self.engine_baseline_squad_ids = new_squad_ids
                    self.engine_baseline_purchase_prices = {str(k): v for k, v in new_prices_int.items()}
                    self.engine_baseline_bank_tenths = new_bank
                else:
                    LOGGER.error(
                        "Baseline engine chip squad initialization returned %d players (expected 15) for %s in GW %d",
                        len(new_squad_ids), current_chip, gw
                    )
                    raise DataIntegrityError(
                        f"Baseline engine chip squad initialization returned {len(new_squad_ids)} players (expected 15)",
                        details={"gameweek": gw, "chip": current_chip, "returned_count": len(new_squad_ids)},
                    )
            except Exception as err:
                LOGGER.error("Baseline engine chip deployment failed for %s in GW %d: %s", current_chip, gw, err)
                raise DataIntegrityError(
                    f"Baseline engine chip deployment failed for {current_chip} in GW {gw}: {err}",
                    details={"gameweek": gw, "chip": current_chip, "error": str(err)},
                ) from err
            hits = 0
            self.engine_baseline_free_transfers = 1
        else:
            purch_prices_int = {int(k): v for k, v in self.engine_baseline_purchase_prices.items()}
            old_bw = getattr(engine, "bench_weight", 0.15)
            txs: list[tuple[int, int]] = []
            try:
                if is_dynamic_chip:
                    engine.bench_weight = eff_bench_weight
                txs = engine.decide_transfers(
                    strategy_name="balanced",
                    current_squad_ids=self.engine_baseline_squad_ids,
                    purchase_prices=purch_prices_int,
                    bank_tenths=self.engine_baseline_bank_tenths,
                    free_transfers=self.engine_baseline_free_transfers,
                    snapshot=snapshot,
                    projections=projections,
                )
            except Exception as err:
                LOGGER.error("Baseline engine transfer optimization failed in GW %d: %s", gw, err)
                raise DataIntegrityError(
                    f"Baseline engine transfer optimization failed in GW {gw}: {err}",
                    details={"gameweek": gw, "error": str(err)},
                ) from err
            finally:
                if is_dynamic_chip:
                    engine.bench_weight = old_bw

            for out_id, in_id in txs:
                out_p = players_by_id.get(out_id)
                in_p = players_by_id.get(in_id)
                if out_p and in_p and out_id in self.engine_baseline_squad_ids:
                    cur_out_price = out_p.price_tenths
                    bought_price = self.engine_baseline_purchase_prices.get(str(out_id), cur_out_price)
                    sell_price = bought_price + max(0, (cur_out_price - bought_price) // 2)
                    self.engine_baseline_bank_tenths += sell_price - in_p.price_tenths
                    idx = self.engine_baseline_squad_ids.index(out_id)
                    self.engine_baseline_squad_ids[idx] = in_id
                    self.engine_baseline_purchase_prices.pop(str(out_id), None)
                    self.engine_baseline_purchase_prices[str(in_id)] = in_p.price_tenths

            hits = max(0, len(txs) - self.engine_baseline_free_transfers) * 4
            used_ft = min(len(txs), self.engine_baseline_free_transfers)
            rem_ft = self.engine_baseline_free_transfers - used_ft
            self.engine_baseline_free_transfers = min(self.max_free_transfers, rem_ft + 1)

        b_starters, b_bench, b_cap, b_vc, _ = engine.select_lineup(self.engine_baseline_squad_ids, projections)
        gross_pts, _, _ = simulate_autosubs_and_score(
            b_starters, b_bench, b_cap, b_vc, outcomes, player_positions, chip_used=current_chip
        )
        net_pts = gross_pts - hits

        # Record consumed chip in engine baseline state
        if current_chip:
            canon_key = "wildcard_1" if (current_chip == "wildcard" and gw <= 19) else (
                "wildcard_2" if current_chip == "wildcard" else current_chip
            )
            self.engine_baseline_chips_used[canon_key] = gw
            if canon_key in self.engine_baseline_chips_remaining:
                self.engine_baseline_chips_remaining.remove(canon_key)

        # Free hit squad revert
        if current_chip == "free_hit" and saved_squad_ids is not None:
            self.engine_baseline_squad_ids = saved_squad_ids
            self.engine_baseline_purchase_prices = saved_prices
            self.engine_baseline_bank_tenths = saved_bank

        self.engine_baseline_history.append({
            "gameweek": gw,
            "gross_points": gross_pts,
            "transfer_hits": hits,
            "net_points": net_pts,
            "chip_used": current_chip,
            "transfers": txs,
            "squad_ids": list(self.engine_baseline_squad_ids),
            "bank_tenths": self.engine_baseline_bank_tenths,
        })
        return net_pts

    # -------------------------------------------------------------------------
    # Analytics & Season Report Export
    # -------------------------------------------------------------------------

    def generate_summary(self) -> SimulationSummary:
        """Generate high-level season simulation summary."""
        tot_gross = sum(h.get("gross_points", 0) for h in self.history)
        tot_hits = sum(h.get("transfer_hits", 0) for h in self.history)
        tot_net = sum(h.get("net_points", 0) for h in self.history)
        tot_txs = sum(len(h.get("transfers_executed", [])) for h in self.history)
        cap_pts = sum(h.get("captain_points", 0) for h in self.history)
        cap_proms = sum(1 for h in self.history if h.get("captain_promoted"))
        autosub_cnt = sum(len(h.get("autosubs", [])) for h in self.history)

        engine_tot = sum(e.get("net_points", 0) for e in self.engine_baseline_history) if self.engine_baseline_history else None
        delta = (tot_net - engine_tot) if engine_tot is not None else None

        overrides = [h for h in self.history if h.get("human_engine_divergence", {}).get("human_override")]
        pos_overrides = sum(1 for h in overrides if h.get("human_engine_divergence", {}).get("point_delta_vs_engine", 0) > 0)
        neg_overrides = sum(1 for h in overrides if h.get("human_engine_divergence", {}).get("point_delta_vs_engine", 0) < 0)

        last_val = self.history[-1].get("squad_value_tenths_after", 1000) if self.history else 1000

        return SimulationSummary(
            session_id=self.session_id,
            season=self.season,
            gameweeks_completed=len(self.history),
            total_gross_points=tot_gross,
            total_transfer_hits=tot_hits,
            total_net_points=tot_net,
            total_transfers_made=tot_txs,
            final_bank_tenths=self.bank_tenths,
            final_squad_value_tenths=last_val,
            chips_used=dict(self.chips_used),
            captain_points=cap_pts,
            captain_promotions=cap_proms,
            autosubs_count=autosub_cnt,
            engine_baseline_total_net_points=engine_tot,
            human_vs_engine_delta=delta,
            override_count=len(overrides),
            override_positive_count=pos_overrides,
            override_negative_count=neg_overrides,
        )

    def export_report(self, output_dir: Path | None = None) -> tuple[Path, Path]:
        """Export comprehensive JSON and Markdown report to reports/simulations/<session_id>/."""
        out_dir = (output_dir or DEFAULT_REPORTS_DIR) / self.session_id
        out_dir.mkdir(parents=True, exist_ok=True)

        summary = self.generate_summary()
        json_path = out_dir / "summary.json"
        md_path = out_dir / "report.md"

        json_path.write_text(json.dumps(summary.to_dict(), indent=2), encoding="utf-8")

        # Markdown report
        lines = [
            f"# Historical Simulation Report: {self.session_id}",
            "",
            f"- **Season:** `{self.season}`",
            f"- **Manager:** `{self.experiment_metadata.get('manager_name', 'Human')}`",
            f"- **Gameweeks Completed:** {summary.gameweeks_completed}/38",
            f"- **Total Net Points:** **{summary.total_net_points}**",
            f"- **Total Gross Points:** {summary.total_gross_points}",
            f"- **Total Transfer Hits Cost:** -{summary.total_transfer_hits} pts",
            f"- **Transfers Made:** {summary.total_transfers_made}",
            f"- **Final Squad Value:** £{summary.final_squad_value_tenths/10:.1f}m",
            f"- **Captain Points Contributed:** {summary.captain_points}",
            f"- **Autosub Events:** {summary.autosubs_count}",
            "",
            f"## Benchmark Comparison vs Frozen Engine ({self.engine_baseline_version})",
            "",
            f"- **Engine Baseline Total Net Points:** {summary.engine_baseline_total_net_points}",
            f"- **Human-vs-Engine Delta:** {'+' if (summary.human_vs_engine_delta or 0) > 0 else ''}{summary.human_vs_engine_delta} pts",
            f"- **Human Overrides Count:** {summary.override_count}",
            f"  - Positive overrides (helped): {summary.override_positive_count}",
            f"  - Negative overrides (hurt): {summary.override_negative_count}",
            "",
            "## Gameweek by Gameweek Progression",
            "",
            "| GW | Gross | Hits | Net | Cum Net | Captain | Chip | Engine Net | Delta |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for h in self.history:
            gw_num = h["gameweek"]
            gross = h["gross_points"]
            hits = h["transfer_hits"]
            net = h["net_points"]
            cum = h["cumulative_net_points"]
            chip = h.get("chip_used") or "-"
            e_net = h.get("engine_net_points", "-")
            delta_val = h.get("human_engine_divergence", {}).get("point_delta_vs_engine", "-")
            lines.append(f"| GW{gw_num:02d} | {gross} | -{hits} | {net} | {cum} | {h['effective_captain_id']} | {chip} | {e_net} | {delta_val} |")

        md_path.write_text("\n".join(lines), encoding="utf-8")
        return json_path, md_path
