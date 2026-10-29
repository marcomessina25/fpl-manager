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
from ..transfers import resolve_chained_transfers, selling_price
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
        initial_decision: dict[str, Any] | None = None,
        engine_baseline_squad_ids: list[int] | None = None,
        engine_baseline_purchase_prices: dict[str, int] | None = None,
        engine_baseline_bank_tenths: int = 0,
        engine_baseline_free_transfers: int = 1,
        engine_baseline_history: list[dict[str, Any]] | None = None,
        engine_baseline_chips_remaining: list[str] | None = None,
        engine_baseline_chips_used: dict[str, int] | None = None,
        engine_baseline_version: str = "v1.3.5",
        baseline_chip_use_optimizer: bool | None = None,
        baseline_chip_optimizer_variant: str | None = None,
        experiment_metadata: dict[str, Any] | None = None,
        gw_start_state: dict[str, Any] | None = None,
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
        self.pre_free_hit_state = pre_free_hit_state if self.active_chip in ("free_hit", "freehit", "fh") else None
        self.starting_ids = list(starting_ids or [])
        self.bench_ids = list(bench_ids or [])
        self.captain_id = captain_id
        self.vice_captain_id = vice_captain_id
        self.transfers_staged = list(transfers_staged or [])
        self.history = list(history or [])
        self.initial_decision = initial_decision

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
        if baseline_chip_use_optimizer is not None:
            self.baseline_chip_use_optimizer = bool(baseline_chip_use_optimizer)
        elif "baseline_chip_use_optimizer" in self.experiment_metadata:
            self.baseline_chip_use_optimizer = bool(self.experiment_metadata["baseline_chip_use_optimizer"])
        else:
            self.baseline_chip_use_optimizer = True

        if baseline_chip_optimizer_variant is not None:
            self.baseline_chip_optimizer_variant = str(baseline_chip_optimizer_variant)
        elif "baseline_chip_optimizer_variant" in self.experiment_metadata:
            self.baseline_chip_optimizer_variant = str(self.experiment_metadata["baseline_chip_optimizer_variant"])
        else:
            self.baseline_chip_optimizer_variant = "c1_linear_decay"

        self.experiment_metadata["baseline_chip_use_optimizer"] = self.baseline_chip_use_optimizer
        self.experiment_metadata["baseline_chip_optimizer_variant"] = self.baseline_chip_optimizer_variant
        self.experiment_metadata["baseline_chip_policy"] = (
            f"optimizer:{self.baseline_chip_optimizer_variant}"
            if self.baseline_chip_use_optimizer
            else "legacy_c0_heuristic"
        )

        self.config_dir = config_dir or DEFAULT_SIMULATIONS_DIR
        self.historical_dir = historical_dir or DEFAULT_HISTORICAL_DIR

        # Start gameweek tracking
        if self.experiment_metadata and "start_gw" in self.experiment_metadata:
            self.start_gw = int(self.experiment_metadata["start_gw"])
        elif initial_decision and "gameweek" in initial_decision:
            self.start_gw = int(initial_decision["gameweek"])
        elif self.history:
            self.start_gw = int(self.history[0].get("gameweek", 1))
        else:
            self.start_gw = int(current_gw or 1)

        # Normalize persisted hit units across history and baseline history
        self._normalize_history_hit_units()

        # Reconcile chip inventory according to 2-segment rules (GW1-19 and GW20-38)
        self._reconcile_chips()

        # Capture or restore clean pre-gameweek start state before staging mutations
        if gw_start_state and gw_start_state.get("gameweek") == self.current_gw:
            self.gw_start_state = dict(gw_start_state)
        else:
            self.gw_start_state = self._reconstruct_gw_start_state()

        # Align lineup player references with staged transfers if present
        if self.transfers_staged:
            for st in self.transfers_staged:
                o_id = st["out_id"]
                i_id = st["in_id"]
                if o_id in self.starting_ids:
                    self.starting_ids = [i_id if x == o_id else x for x in self.starting_ids]
                if o_id in self.bench_ids:
                    self.bench_ids = [i_id if x == o_id else x for x in self.bench_ids]
                if self.captain_id == o_id:
                    self.captain_id = i_id
                if self.vice_captain_id == o_id:
                    self.vice_captain_id = i_id

    def _normalize_history_hit_units(self) -> None:
        """Normalize transfer_hits to hit count (and transfer_hit_points to points) across history records."""
        for h in self.history:
            if not isinstance(h, dict):
                continue
            if "gross_points" in h and "net_points" in h and h["gross_points"] is not None and h["net_points"] is not None:
                gross = int(h["gross_points"])
                net = int(h["net_points"])
                hit_pts = max(0, gross - net)
                hit_count = hit_pts // 4
                h["transfer_hits"] = hit_count
                h["transfer_hit_points"] = hit_pts
                h["hit_unit"] = "count"
                for dec_key in ("decision_logged", "decision"):
                    dec = h.get(dec_key)
                    if isinstance(dec, dict):
                        dec["transfer_hits"] = hit_count
                        dec["transfer_hit_points"] = hit_pts
        for eh in self.engine_baseline_history:
            if not isinstance(eh, dict):
                continue
            if "gross_points" in eh and "net_points" in eh and eh["gross_points"] is not None and eh["net_points"] is not None:
                gross = int(eh["gross_points"])
                net = int(eh["net_points"])
                hit_pts = max(0, gross - net)
                hit_count = hit_pts // 4
                eh["transfer_hits"] = hit_count
                eh["transfer_hit_points"] = hit_pts
                eh["hit_unit"] = "count"

    def _recover_trusted_purchase_price(
        self,
        player_id: int,
        transfer_record: dict[str, Any] | None = None,
        current_prices: dict[str, int] | None = None,
    ) -> int | None:
        """Recover authoritative historical purchase price for a player without fabricating selling price."""
        pid_str = str(player_id)
        # 1. Direct transfer record properties
        if transfer_record:
            for k in ("out_purchase_price_tenths", "outgoing_purchase_price_tenths", "purchase_price_tenths"):
                val = transfer_record.get(k)
                if val is not None:
                    return int(val)

        # 2. Persisted in current_prices dictionary if not popped
        if current_prices and pid_str in current_prices:
            return int(current_prices[pid_str])

        # 3. Present in clean start state of current gameweek
        gw_start = getattr(self, "gw_start_state", None)
        if isinstance(gw_start, dict) and gw_start.get("gameweek") == self.current_gw:
            if not gw_start.get("purchase_basis_unverified"):
                sp = gw_start.get("purchase_prices_tenths", {})
                if pid_str in sp:
                    return int(sp[pid_str])

        # 4. Check historical gameweeks backwards
        for h in reversed(self.history):
            if not isinstance(h, dict) or h.get("gameweek", 0) >= self.current_gw:
                continue
            if "purchase_prices_after" in h and pid_str in h["purchase_prices_after"]:
                return int(h["purchase_prices_after"][pid_str])
            # Check if acquired in transfers_executed
            for tx in h.get("transfers_executed", []):
                if isinstance(tx, dict) and tx.get("in_id") == player_id:
                    tx_price = tx.get("in_price_tenths") or tx.get("purchase_price_tenths")
                    if tx_price is not None:
                        return int(tx_price)
            if "purchase_prices_before" in h and pid_str in h["purchase_prices_before"]:
                if not h.get("purchase_basis_unverified"):
                    # Only valid if player was not transferred out in this historical step
                    out_ids = [tx.get("out_id") for tx in h.get("transfers_executed", []) if isinstance(tx, dict)]
                    if player_id not in out_ids:
                        return int(h["purchase_prices_before"][pid_str])

        # 5. Check initial decision if from session inception
        if getattr(self, "initial_decision", None) and isinstance(self.initial_decision, dict):
            init_squad = self.initial_decision.get("squad_player_ids", [])
            if player_id in init_squad:
                # If never transferred out prior to current gw, check initial prices or baseline
                if pid_str in getattr(self, "engine_baseline_purchase_prices", {}):
                    return int(self.engine_baseline_purchase_prices[pid_str])

        return None

    def _reconstruct_gw_start_state(self) -> dict[str, Any]:
        """Reconstruct clean start-of-GW state prior to any current-GW staged or applied transfers."""
        base_squad = list(self.squad_ids)
        base_prices = dict(self.purchase_prices_tenths)
        base_bank = int(self.bank_tenths)
        base_starters = list(self.starting_ids)
        base_bench = list(self.bench_ids)
        base_cap = int(self.captain_id)
        base_vc = int(self.vice_captain_id)
        unverified_pids: list[int] = []

        if self.active_chip in ("free_hit", "freehit", "fh") and self.pre_free_hit_state:
            base_squad = list(self.pre_free_hit_state.get("squad_ids", base_squad))
            base_prices = dict(self.pre_free_hit_state.get("purchase_prices_tenths", base_prices))
            base_bank = int(self.pre_free_hit_state.get("bank_tenths", base_bank))
        elif self.transfers_staged:
            for st in reversed(self.transfers_staged):
                o_id = st["out_id"]
                i_id = st["in_id"]
                if st.get("already_applied"):
                    if i_id in base_squad:
                        base_squad[base_squad.index(i_id)] = o_id
                    base_bank += int(st.get("cost_tenths", 0))
                    if i_id not in base_squad:
                        base_prices.pop(str(i_id), None)
                    rec_price = self._recover_trusted_purchase_price(o_id, st, current_prices=base_prices)
                    if rec_price is not None:
                        base_prices[str(o_id)] = rec_price
                    else:
                        unverified_pids.append(o_id)
                        base_prices.pop(str(o_id), None)
                if i_id in base_starters:
                    base_starters = [o_id if x == i_id else x for x in base_starters]
                if i_id in base_bench:
                    base_bench = [o_id if x == i_id else x for x in base_bench]
                if base_cap == i_id:
                    base_cap = o_id
                if base_vc == i_id:
                    base_vc = o_id

        return {
            "gameweek": self.current_gw,
            "squad_ids": base_squad,
            "purchase_prices_tenths": base_prices,
            "bank_tenths": base_bank,
            "free_transfers": int(self.free_transfers),
            "starting_ids": base_starters,
            "bench_ids": base_bench,
            "captain_id": base_cap,
            "vice_captain_id": base_vc,
            "chips_remaining": list(self.chips_remaining),
            "chips_used": dict(self.chips_used),
            "purchase_basis_unverified": bool(unverified_pids),
            "unverified_player_ids": unverified_pids,
        }

    def _capture_gw_start_state(self) -> None:
        """Record the clean start-of-gameweek state before any staging or mid-GW mutations."""
        self.gw_start_state = {
            "gameweek": self.current_gw,
            "squad_ids": list(self.squad_ids),
            "purchase_prices_tenths": dict(self.purchase_prices_tenths),
            "bank_tenths": int(self.bank_tenths),
            "free_transfers": int(self.free_transfers),
            "starting_ids": list(self.starting_ids),
            "bench_ids": list(self.bench_ids),
            "captain_id": int(self.captain_id),
            "vice_captain_id": int(self.vice_captain_id),
            "chips_remaining": list(self.chips_remaining),
            "chips_used": dict(self.chips_used),
        }

    def _reconcile_chips(self) -> None:
        """Ensure chip inventory matches FPL 2-segment rules (GW1-19 and GW20-38).

        Rules:
        - Window 1 (GW 1–19): Wildcard, Free Hit, Triple Captain, Bench Boost.
        - Window 2 (GW 20–38): Wildcard, Free Hit, Triple Captain, Bench Boost.
        - Unused Window 1 chips expire at the end of GW19 and DO NOT roll over.
        - Chips used in Window 1 do NOT deplete Window 2 chips.
        """
        w2_base = ["wildcard_2", "free_hit", "bench_boost", "triple_captain"]
        if self.current_gw >= 20:
            used_w2 = set()
            for h in self.history:
                if h.get("gameweek", 0) >= 20 and h.get("chip_used"):
                    c_norm = str(h["chip_used"]).lower().replace("-", "_")
                    if c_norm.startswith("wildcard"):
                        used_w2.add("wildcard_2")
                    elif c_norm.startswith("free_hit") or c_norm.startswith("freehit"):
                        used_w2.add("free_hit")
                    elif c_norm.startswith("bench_boost") or c_norm.startswith("benchboost"):
                        used_w2.add("bench_boost")
                    elif c_norm.startswith("triple_captain") or c_norm.startswith("triplecaptain"):
                        used_w2.add("triple_captain")
            for c, used_gw in self.chips_used.items():
                if used_gw >= 20:
                    c_norm = str(c).lower().replace("-", "_")
                    if c_norm.startswith("wildcard"):
                        used_w2.add("wildcard_2")
                    elif c_norm.startswith("free_hit") or c_norm.startswith("freehit"):
                        used_w2.add("free_hit")
                    elif c_norm.startswith("bench_boost") or c_norm.startswith("benchboost"):
                        used_w2.add("bench_boost")
                    elif c_norm.startswith("triple_captain") or c_norm.startswith("triplecaptain"):
                        used_w2.add("triple_captain")
            if self.active_chip:
                act_norm = str(self.active_chip).lower().replace("-", "_")
                if act_norm.startswith("wildcard"):
                    used_w2.add("wildcard_2")
                elif act_norm.startswith("free_hit") or act_norm.startswith("freehit"):
                    used_w2.add("free_hit")
                elif act_norm.startswith("bench_boost") or act_norm.startswith("benchboost"):
                    used_w2.add("bench_boost")
                elif act_norm.startswith("triple_captain") or act_norm.startswith("triplecaptain"):
                    used_w2.add("triple_captain")

            self.chips_remaining = [c for c in w2_base if c not in used_w2]

            engine_used_w2 = set()
            for h in self.engine_baseline_history:
                if h.get("gameweek", 0) >= 20 and h.get("chip_used"):
                    c_norm = str(h["chip_used"]).lower().replace("-", "_")
                    if c_norm.startswith("wildcard"):
                        engine_used_w2.add("wildcard_2")
                    elif c_norm.startswith("free_hit") or c_norm.startswith("freehit"):
                        engine_used_w2.add("free_hit")
                    elif c_norm.startswith("bench_boost") or c_norm.startswith("benchboost"):
                        engine_used_w2.add("bench_boost")
                    elif c_norm.startswith("triple_captain") or c_norm.startswith("triplecaptain"):
                        engine_used_w2.add("triple_captain")
            for c, used_gw in self.engine_baseline_chips_used.items():
                if used_gw >= 20:
                    c_norm = str(c).lower().replace("-", "_")
                    if c_norm.startswith("wildcard"):
                        engine_used_w2.add("wildcard_2")
                    elif c_norm.startswith("free_hit") or c_norm.startswith("freehit"):
                        engine_used_w2.add("free_hit")
                    elif c_norm.startswith("bench_boost") or c_norm.startswith("benchboost"):
                        engine_used_w2.add("bench_boost")
                    elif c_norm.startswith("triple_captain") or c_norm.startswith("triplecaptain"):
                        engine_used_w2.add("triple_captain")

            self.engine_baseline_chips_remaining = [c for c in w2_base if c not in engine_used_w2]

    def reset_chips_for_segment_2(self) -> None:
        """Reset chip inventory at Gameweek 20 for Season Segment 2 (GW20–38)."""
        self._reconcile_chips()

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
        baseline_chip_use_optimizer: bool | None = None,
        baseline_chip_optimizer_variant: str | None = None,
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
            "start_gw": start_gw,
        }

        # Initial squad selection logged decision
        initial_decision = {
            "gameweek": start_gw,
            "season": season,
            "session_id": session_id,
            "timestamp": meta["created_at"],
            "notes": "Initial squad selection",
            "chip_played": None,
            "transfer_hits": 0,
            "transfers": [],
            "squad_player_ids": list(squad_ids),
            "starting_player_ids": list(starters),
            "bench_player_ids": list(bench),
            "captain_id": cap,
            "vice_captain_id": vc,
            "predicted_lineup_xp": sum(
                (next((p.expected_points for p in projections_gw1 if p.player_id == pid), 0.0) * (2 if pid == cap else 1))
                for pid in starters
            ),
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
            history=[],
            initial_decision=initial_decision,
            engine_baseline_version="v1.3.5",
            engine_baseline_squad_ids=baseline_squad,
            engine_baseline_purchase_prices=baseline_prices,
            engine_baseline_bank_tenths=baseline_bank,
            engine_baseline_free_transfers=1,
            baseline_chip_use_optimizer=baseline_chip_use_optimizer,
            baseline_chip_optimizer_variant=baseline_chip_optimizer_variant,
            experiment_metadata=meta,
            config_dir=config_dir,
            historical_dir=historical_dir,
        )
        session.save()
        return session

    def save(self) -> Path:
        """Persist session state to isolated JSON file."""
        self._normalize_history_hit_units()
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
            "initial_decision": self.initial_decision,
            "engine_baseline_version": self.engine_baseline_version,
            "engine_baseline_squad_ids": self.engine_baseline_squad_ids,
            "engine_baseline_purchase_prices": self.engine_baseline_purchase_prices,
            "engine_baseline_bank_tenths": self.engine_baseline_bank_tenths,
            "engine_baseline_free_transfers": self.engine_baseline_free_transfers,
            "engine_baseline_chips_remaining": self.engine_baseline_chips_remaining,
            "engine_baseline_chips_used": self.engine_baseline_chips_used,
            "engine_baseline_history": self.engine_baseline_history,
            "experiment_metadata": self.experiment_metadata,
            "gw_start_state": getattr(self, "gw_start_state", None),
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
        session = cls(
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
            initial_decision=data.get("initial_decision"),
            engine_baseline_version=data.get("engine_baseline_version", "v1.3.5"),
            engine_baseline_squad_ids=data.get("engine_baseline_squad_ids"),
            engine_baseline_purchase_prices=data.get("engine_baseline_purchase_prices"),
            engine_baseline_bank_tenths=data.get("engine_baseline_bank_tenths", 0),
            engine_baseline_free_transfers=data.get("engine_baseline_free_transfers", 1),
            engine_baseline_chips_remaining=data.get("engine_baseline_chips_remaining"),
            engine_baseline_chips_used=data.get("engine_baseline_chips_used", {}),
            engine_baseline_history=data.get("engine_baseline_history", []),
            experiment_metadata=data.get("experiment_metadata", {}),
            gw_start_state=data.get("gw_start_state"),
            config_dir=c_dir,
            historical_dir=historical_dir,
        )
        if session.current_gw <= 2 and session.free_transfers > 1:
            session.free_transfers = 1
        if session.current_gw <= 2 and session.engine_baseline_free_transfers > 1:
            session.engine_baseline_free_transfers = 1
        if session.current_gw >= 20 and session.chips_remaining != data.get("chips_remaining"):
            session.save()
        return session

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
                completed_hist = [h for h in data.get("history", []) if isinstance(h, dict) and "gross_points" in h]
                sessions.append({
                    "session_id": data.get("session_id", p.stem),
                    "season": data.get("season"),
                    "current_gw": data.get("current_gw"),
                    "status": data.get("status"),
                    "is_completed": data.get("status") == "completed" or data.get("current_gw", 1) > 38 or len(completed_hist) >= 38,
                    "gameweeks_completed": len(completed_hist),
                    "total_net_points": sum(h.get("net_points", 0) for h in completed_hist),
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
        return build_historical_snapshot(season_dir, self.current_gw, include_prior_players=True)

    def get_squad_player_details(self) -> list[dict[str, Any]]:
        """Get rich player details for current squad at the current historical deadline."""
        snapshot = self.get_current_snapshot()
        players_map = {p.player_id: p for p in snapshot.players}
        teams_map = {t["team_id"]: t for t in snapshot.teams}

        # Compute point-in-time projections for expected points before gameweek runs
        try:
            projections = reconstruct_features_and_project(snapshot)
            proj_map = {p.player_id: p for p in projections}
        except Exception:
            proj_map = {}

        # Effective squad reflects staged transfers for the upcoming gameweek
        effective_squad_ids = list(self.squad_ids)
        staged_in_map = {st["in_id"]: st for st in self.transfers_staged}
        for st in self.transfers_staged:
            if st.get("already_applied"):
                continue
            o_id = st["out_id"]
            i_id = st["in_id"]
            if o_id in effective_squad_ids:
                idx = effective_squad_ids.index(o_id)
                effective_squad_ids[idx] = i_id
            elif i_id not in effective_squad_ids:
                effective_squad_ids.append(i_id)

        result: list[dict[str, Any]] = []
        for pid in effective_squad_ids:
            p = players_map.get(pid)
            if not p:
                continue
            t_info = teams_map.get(p.team_id, {})
            if pid in staged_in_map:
                purch_price = staged_in_map[pid].get("in_price_tenths", p.price_tenths)
                curr_sell_price = purch_price
            else:
                purch_price = self.purchase_prices_tenths.get(str(pid), p.price_tenths)
                curr_sell_price = selling_price(purch_price, p.price_tenths)

            pos_abbr = {
                Position.GOALKEEPER: "GKP",
                Position.DEFENDER: "DEF",
                Position.MIDFIELDER: "MID",
                Position.FORWARD: "FWD",
            }.get(p.position, "MID")

            p_proj = proj_map.get(pid)
            exp_pts = round(p_proj.expected_points, 1) if p_proj else 0.0
            next_fdr = p_proj.fixtures[0].fdr if (p_proj and p_proj.fixtures) else 3

            result.append({
                "id": pid,
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
                "expected_points": exp_pts,
                "next_fixture_fdr": next_fdr,
                "form": p.form,
                "status": p.status,
                "is_staged": pid in staged_in_map,
                "is_starter": pid in self.starting_ids,
                "is_bench": pid in self.bench_ids,
                "bench_order": self.bench_ids.index(pid) + 1 if pid in self.bench_ids else None,
                "is_captain": pid == self.captain_id,
                "is_vice_captain": pid == self.vice_captain_id,
            })
        return result

    def get_historical_lineup_for_gw(self, gw: int) -> dict[str, Any]:
        """Point-in-time matchday lineup. If gw < current_gw, returns simulated ground truth.
        If gw == current_gw, returns upcoming matchday lineup with projected xP."""
        if gw > self.current_gw:
            raise ValueError(f"Zero future leakage: Gameweek {gw} is in the future (current GW is {self.current_gw}).")

        if gw == self.current_gw and not self.is_completed:
            squad_details = self.get_squad_player_details()
            starters = [p for p in squad_details if p.get("is_starter")]
            bench = sorted([p for p in squad_details if p.get("is_bench")], key=lambda x: x.get("bench_order") or 99)
            return {
                "gameweek": self.current_gw,
                "is_past": False,
                "squad": squad_details,
                "starters": starters,
                "bench": bench,
                "captain_id": self.captain_id,
                "vice_captain_id": self.vice_captain_id,
                "chip_played": self.active_chip,
                "gross_points": None,
                "transfer_hits": 0,
                "net_points": None,
                "cumulative_net_points": sum(h.get("net_points", 0) for h in self.history),
                "autosubs": [],
                "transfers_executed": [],
            }

        # Historical simulated gameweek
        history_entry = next((h for h in self.history if h.get("gameweek") == gw), None)
        if not history_entry:
            raise ValueError(f"No simulation history found for Gameweek {gw}.")

        season_dir = self.historical_dir / self.season
        snapshot = build_historical_snapshot(season_dir, gw)
        players_map = {p.player_id: p for p in snapshot.players}
        teams_map = {t["team_id"]: t for t in snapshot.teams}

        autosubs = history_entry.get("autosubs", [])
        sub_out_ids = {s.get("out_id") for s in autosubs}
        sub_in_ids = {s.get("in_id") for s in autosubs}

        cap_id = history_entry.get("effective_captain_id") or history_entry.get("captain_id")
        orig_cap_id = history_entry.get("captain_id")
        orig_vc_id = history_entry.get("vice_captain_id")
        cap_promoted = history_entry.get("captain_promoted", False)

        def _map_player(sp: dict[str, Any], is_starter: bool, bench_order: int | None = None) -> dict[str, Any]:
            pid = sp["player_id"]
            p = players_map.get(pid)
            t_info = teams_map.get(p.team_id, {}) if p else {}
            pos_abbr = {
                Position.GOALKEEPER: "GKP",
                Position.DEFENDER: "DEF",
                Position.MIDFIELDER: "MID",
                Position.FORWARD: "FWD",
            }.get(p.position, "MID") if p else "MID"

            is_cap = sp.get("is_captain", False) or pid == orig_cap_id or pid == cap_id
            is_vc = sp.get("is_vice_captain", False) or pid == orig_vc_id
            is_eff_cap = sp.get("is_effective_captain", False) or pid == cap_id

            return {
                "id": pid,
                "player_id": pid,
                "name": sp.get("name") or (p.web_name if p else f"Player {pid}"),
                "position": p.position.name if p else pos_abbr,
                "pos_abbr": pos_abbr,
                "team_id": p.team_id if p else 0,
                "team_name": t_info.get("name", ""),
                "team_short": t_info.get("short_name", ""),
                "points": sp.get("points", 0),
                "minutes": sp.get("minutes", 0),
                "is_starter": is_starter,
                "is_bench": not is_starter,
                "bench_order": bench_order,
                "is_captain": is_cap,
                "is_vice_captain": is_vc,
                "is_effective_captain": is_eff_cap,
                "captain_promoted": cap_promoted if is_eff_cap else False,
                "subbed_out": pid in sub_out_ids,
                "subbed_in": pid in sub_in_ids,
            }

        starters = [_map_player(sp, is_starter=True) for sp in history_entry.get("starters_points", [])]
        bench = [_map_player(bp, is_starter=False, bench_order=idx + 1) for idx, bp in enumerate(history_entry.get("bench_points", []))]

        return {
            "gameweek": gw,
            "is_past": True,
            "squad": starters + bench,
            "starters": starters,
            "bench": bench,
            "captain_id": orig_cap_id,
            "vice_captain_id": orig_vc_id,
            "effective_captain_id": cap_id,
            "captain_promoted": cap_promoted,
            "captain_points": history_entry.get("captain_points"),
            "chip_played": history_entry.get("chip_used"),
            "gross_points": history_entry.get("gross_points", 0),
            "transfer_hits": history_entry.get("transfer_hits", 0),
            "net_points": history_entry.get("net_points", 0),
            "cumulative_net_points": history_entry.get("cumulative_net_points", 0),
            "autosubs": autosubs,
            "transfers_executed": history_entry.get("transfers_executed", []),
        }

    # -------------------------------------------------------------------------
    # Staging Transfers & Lineup
    # -------------------------------------------------------------------------

    def stage_transfers_batch(self, transfers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Stage a batch of transfers atomically, validating legality and net budget."""
        if self.is_completed:
            raise RuntimeError("Simulation is already completed.")
        if not transfers:
            return list(self.transfers_staged)

        # Collapse any internal chains (e.g. A -> B, B -> C => A -> C) on the incoming batch first
        from ..transfers import Transfer
        raw_tx_objs = [
            Transfer(outgoing_id=int(t["out_id"]), incoming_id=int(t["in_id"]))
            for t in transfers
        ]
        collapsed_raw = resolve_chained_transfers(raw_tx_objs)
        if not collapsed_raw and transfers:
            raise ValueError("Transfer batch cancels out to no net transfers.")

        # Normalize transfers into collapsed representation
        norm_transfers = [{"out_id": t.outgoing_id, "in_id": t.incoming_id} for t in collapsed_raw]

        # Idempotency check: if all requested net transfers are already staged, return existing records
        existing_map = {(st["out_id"], st["in_id"]): st for st in self.transfers_staged}
        if all((t["out_id"], t["in_id"]) in existing_map for t in norm_transfers):
            return [existing_map[(t["out_id"], t["in_id"])] for t in norm_transfers]

        snapshot = self.get_current_snapshot()
        players_map = {p.player_id: p for p in snapshot.players}

        # Calculate effective squad excluding unapplied staged transfers being replaced
        batch_out_ids = {t["out_id"] for t in norm_transfers}
        batch_in_ids = {t["in_id"] for t in norm_transfers}

        # Validate legality against current squad and positions
        for t in norm_transfers:
            out_id = t["out_id"]
            in_id = t["in_id"]
            if out_id not in self.squad_ids:
                raise ValueError(f"Player {out_id} is not in the current squad.")
            if in_id in self.squad_ids and in_id not in batch_out_ids:
                raise ValueError(f"Player {in_id} is already in the current squad.")

            out_p = players_map.get(out_id)
            in_p = players_map.get(in_id)
            if not out_p or not in_p:
                raise ValueError("Player not found in historical snapshot.")
            if out_p.position != in_p.position:
                raise ValueError(
                    f"Position mismatch: cannot transfer {out_p.position.name} for {in_p.position.name}."
                )

        validated_items = []
        for t in norm_transfers:
            out_id = t["out_id"]
            in_id = t["in_id"]
            out_p = players_map[out_id]
            in_p = players_map[in_id]

            purch_price = self.purchase_prices_tenths.get(str(out_id), out_p.price_tenths)
            sell_p = selling_price(purch_price, out_p.price_tenths)
            cost_delta = in_p.price_tenths - sell_p

            validated_items.append({
                "out_id": out_id,
                "in_id": in_id,
                "out_name": out_p.web_name,
                "in_name": in_p.web_name,
                "cost_tenths": cost_delta,
                "out_selling_price_tenths": sell_p,
                "out_purchase_price_tenths": purch_price,
                "in_price_tenths": in_p.price_tenths,
            })

        # Calculate net finances: available bank excluding unapplied transfers replaced by this batch
        curr_bank = self.bank_tenths
        for st in self.transfers_staged:
            if not st.get("already_applied") and st["out_id"] not in batch_out_ids:
                curr_bank -= st.get("cost_tenths", 0)

        batch_cost = sum(item["cost_tenths"] for item in validated_items)
        if curr_bank - batch_cost < 0:
            raise ValueError(
                f"Insufficient funds: transfer requires £{batch_cost/10:.1f}m, "
                f"available bank is £{curr_bank/10:.1f}m."
            )

        # Team quota check (max 3 players from any club) on resulting squad
        final_squad = [pid for pid in self.squad_ids if pid not in batch_out_ids]
        for st in self.transfers_staged:
            if not st.get("already_applied") and st["out_id"] not in batch_out_ids:
                if st["out_id"] in final_squad:
                    final_squad.remove(st["out_id"])
                if st["in_id"] not in final_squad:
                    final_squad.append(st["in_id"])
        final_squad.extend(batch_in_ids)

        club_counts: dict[int, int] = {}
        for pid in final_squad:
            p_obj = players_map.get(pid)
            if p_obj:
                club_counts[p_obj.team_id] = club_counts.get(p_obj.team_id, 0) + 1
                if club_counts[p_obj.team_id] > 3:
                    raise ValueError("Club player limit exceeded: max 3 players allowed per Premier League club.")

        # Revert lineup references for any old unapplied staged transfers being replaced
        for old_st in self.transfers_staged:
            if not old_st.get("already_applied") and old_st["out_id"] in batch_out_ids:
                old_in = old_st["in_id"]
                orig_out = old_st["out_id"]
                if old_in in self.starting_ids:
                    self.starting_ids = [orig_out if x == old_in else x for x in self.starting_ids]
                if old_in in self.bench_ids:
                    self.bench_ids = [orig_out if x == old_in else x for x in self.bench_ids]
                if self.captain_id == old_in:
                    self.captain_id = orig_out
                if self.vice_captain_id == old_in:
                    self.vice_captain_id = orig_out

        # Merge new validated transfers with un-replaced staged transfers (keeping already_applied chains)
        new_staged = [
            st for st in self.transfers_staged
            if st.get("already_applied") or st["out_id"] not in batch_out_ids
        ]
        new_staged.extend(validated_items)
        self.transfers_staged = new_staged

        # Update lineup player references so starting XI, bench, and captaincy reflect new staged transfers
        for item in validated_items:
            o_id = item["out_id"]
            i_id = item["in_id"]
            if o_id in self.starting_ids:
                self.starting_ids = [i_id if x == o_id else x for x in self.starting_ids]
            if o_id in self.bench_ids:
                self.bench_ids = [i_id if x == o_id else x for x in self.bench_ids]
            if self.captain_id == o_id:
                self.captain_id = i_id
            if self.vice_captain_id == o_id:
                self.vice_captain_id = i_id

        self.save()
        return validated_items

    def stage_transfer(self, out_id: int, in_id: int) -> dict[str, Any]:
        """Stage a single transfer, validating legality against current snapshot."""
        res = self.stage_transfers_batch([{"out_id": out_id, "in_id": in_id}])
        return res[0]

    def clear_staged_transfers(self) -> None:
        """Clear all staged transfers for the upcoming deadline, reversing any committed transfers atomically."""
        has_applied = any(st.get("already_applied") for st in self.transfers_staged)
        if has_applied:
            # Check whether cost basis can be deterministically reversed
            for st in reversed(self.transfers_staged):
                if st.get("already_applied"):
                    o_id = st["out_id"]
                    rec_p = self._recover_trusted_purchase_price(o_id, st)
                    if rec_p is None:
                        raise DataIntegrityError(
                            f"Cannot deterministically reverse committed transfer for player {o_id}: original purchase basis is unverified.",
                            details={"player_id": o_id, "transfer": st},
                        )

            # Revert applied transfers
            for st in reversed(self.transfers_staged):
                o_id = st["out_id"]
                i_id = st["in_id"]
                if st.get("already_applied"):
                    if i_id in self.squad_ids:
                        self.squad_ids[self.squad_ids.index(i_id)] = o_id
                    self.bank_tenths += int(st.get("cost_tenths", 0))
                    if i_id not in self.squad_ids:
                        self.purchase_prices_tenths.pop(str(i_id), None)
                    rec_p = self._recover_trusted_purchase_price(o_id, st)
                    self.purchase_prices_tenths[str(o_id)] = int(rec_p)

                if i_id in self.starting_ids:
                    self.starting_ids = [o_id if x == i_id else x for x in self.starting_ids]
                if i_id in self.bench_ids:
                    self.bench_ids = [o_id if x == i_id else x for x in self.bench_ids]
                if self.captain_id == i_id:
                    self.captain_id = o_id
                if self.vice_captain_id == i_id:
                    self.vice_captain_id = o_id

            # Restore lineup from clean gw_start_state if needed
            gw_start = getattr(self, "gw_start_state", None)
            if isinstance(gw_start, dict) and gw_start.get("gameweek") == self.current_gw:
                if set(gw_start.get("squad_ids", [])) == set(self.squad_ids):
                    self.starting_ids = list(gw_start.get("starting_ids", self.starting_ids))
                    self.bench_ids = list(gw_start.get("bench_ids", self.bench_ids))
                    self.captain_id = int(gw_start.get("captain_id", self.captain_id))
                    self.vice_captain_id = int(gw_start.get("vice_captain_id", self.vice_captain_id))

            # Strip pending decision record from history if present
            if self.history and self.history[-1].get("gameweek") == self.current_gw and "gross_points" not in self.history[-1]:
                self.history.pop()
        else:
            for st in reversed(self.transfers_staged):
                o_id = st["out_id"]
                i_id = st["in_id"]
                if i_id in self.starting_ids:
                    self.starting_ids = [o_id if x == i_id else x for x in self.starting_ids]
                if i_id in self.bench_ids:
                    self.bench_ids = [o_id if x == i_id else x for x in self.bench_ids]
                if self.captain_id == i_id:
                    self.captain_id = o_id
                if self.vice_captain_id == i_id:
                    self.vice_captain_id = o_id

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
        if self.is_completed:
            raise RuntimeError("Simulation is already completed.")
        if len(starting_ids) != 11:
            raise ValueError(f"Starting lineup must contain exactly 11 players (got {len(starting_ids)}).")
        if len(bench_ids) != 4:
            raise ValueError(f"Bench must contain exactly 4 players (got {len(bench_ids)}).")

        # Normalize any unstaged player IDs to their staged counterparts if transfers are staged
        staged_map = {st["out_id"]: st["in_id"] for st in self.transfers_staged}
        mapped_starters = [staged_map.get(pid, pid) for pid in starting_ids]
        mapped_bench = [staged_map.get(pid, pid) for pid in bench_ids]
        mapped_cap = staged_map.get(captain_id, captain_id)
        mapped_vc = staged_map.get(vice_captain_id, vice_captain_id)

        all_15 = set(mapped_starters + mapped_bench)
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
        for pid in mapped_starters:
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
        if mapped_cap not in mapped_starters:
            raise ValueError("Captain must be in the starting 11.")
        if mapped_vc not in mapped_starters:
            raise ValueError("Vice-captain must be in the starting 11.")
        if mapped_cap == mapped_vc:
            raise ValueError("Captain and vice-captain cannot be the same player.")

        self.starting_ids = list(mapped_starters)
        self.bench_ids = list(mapped_bench)
        self.captain_id = mapped_cap
        self.vice_captain_id = mapped_vc
        self.save()

    def play_chip(self, chip_name: str) -> str:
        """Activate a chip for the upcoming gameweek."""
        if self.is_completed:
            raise RuntimeError("Simulation is already completed.")
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
            "bboost": "bench_boost",
            "bb": "bench_boost",
            "triplecaptain": "triple_captain",
            "triple_captain": "triple_captain",
            "3xc": "triple_captain",
            "tc": "triple_captain",
        }
        canonical = alias_map.get(norm)
        if not canonical:
            raise ValueError(f"Unknown chip '{chip_name}'.")

        # Check availability
        avail_chips = [c.lower().replace("-", "_") for c in self.chips_remaining]
        base = canonical.replace("_1", "").replace("_2", "")
        if canonical not in avail_chips and base not in avail_chips:
            raise ValueError(f"Chip '{canonical}' is not available (already used or expired).")

        if canonical == "wildcard_1" and self.current_gw > 19:
            raise ValueError("First Wildcard can only be played in GW 1-19.")
        if canonical == "wildcard_2" and self.current_gw < 20:
            raise ValueError("Second Wildcard can only be played in GW 20-38.")

        self.active_chip = canonical
        if canonical == "free_hit":
            gw_start = getattr(self, "gw_start_state", None)
            if not isinstance(gw_start, dict) or gw_start.get("gameweek") != self.current_gw:
                gw_start = self._reconstruct_gw_start_state()
            self.pre_free_hit_state = {
                "gameweek": self.current_gw,
                "squad_ids": list(gw_start.get("squad_ids", self.squad_ids)),
                "purchase_prices_tenths": dict(gw_start.get("purchase_prices_tenths", self.purchase_prices_tenths)),
                "bank_tenths": int(gw_start.get("bank_tenths", self.bank_tenths)),
            }
        else:
            self.pre_free_hit_state = None
        self.save()
        return canonical

    def cancel_chip(self) -> None:
        """Deactivate the active chip and clear any temporary Free Hit restoration snapshot."""
        self.active_chip = None
        self.pre_free_hit_state = None
        self.save()

    # -------------------------------------------------------------------------
    # Recommendations from Frozen Baseline
    # -------------------------------------------------------------------------

    def get_recommendations(self) -> dict[str, Any]:
        """Generate point-in-time recommendations using frozen baseline engine and seasonal chip policy."""
        if self.is_completed:
            return {
                "season_ended": True,
                "message": "The season is ended. All 38 gameweeks have been completed.",
                "recommended_transfers": [],
                "recommended_lineup": None,
                "recommended_chip": None,
            }
        snapshot = self.get_current_snapshot()
        projections = reconstruct_features_and_project(snapshot)
        proj_map = {p.player_id: p for p in projections}

        engine_ver = getattr(self, "engine_baseline_version", "v1.3.5")
        engine = resolve_decision_engine(engine_ver)

        # 1. Evaluate chip recommendation via SeasonalChipPolicy (exact simulation alignment)
        avail_set = {c.lower().replace("-", "_") for c in self.chips_remaining}
        if self.current_gw <= 19:
            chip_inventory = SeasonalChipInventory(
                wildcard_w1="wildcard_1" in avail_set or "wildcard" in avail_set,
                free_hit_w1="free_hit" in avail_set or "freehit" in avail_set,
                triple_captain_w1="triple_captain" in avail_set or "triplecaptain" in avail_set,
                bench_boost_w1="bench_boost" in avail_set or "benchboost" in avail_set,
                wildcard_w2=True,
                free_hit_w2=True,
                triple_captain_w2=True,
                bench_boost_w2=True,
            )
        else:
            chip_inventory = SeasonalChipInventory(
                wildcard_w1=False,
                free_hit_w1=False,
                triple_captain_w1=False,
                bench_boost_w1=False,
                wildcard_w2="wildcard_2" in avail_set or "wildcard" in avail_set,
                free_hit_w2="free_hit" in avail_set or "freehit" in avail_set,
                triple_captain_w2="triple_captain" in avail_set or "triplecaptain" in avail_set,
                bench_boost_w2="bench_boost" in avail_set or "benchboost" in avail_set,
            )
        policy = SeasonalChipPolicy(
            use_optimizer=self.baseline_chip_use_optimizer,
            optimizer_variant=self.baseline_chip_optimizer_variant,
        )
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

        # Get optimal lineup on current squad (reflecting staged transfers if present)
        players_map = {p.player_id: p for p in snapshot.players}
        eff_squad = list(self.squad_ids)
        eff_bank = self.bank_tenths
        purch_prices_int = {int(k): v for k, v in self.purchase_prices_tenths.items()}
        for st in self.transfers_staged:
            if not st.get("already_applied"):
                o_id = st["out_id"]
                i_id = st["in_id"]
                if o_id in eff_squad:
                    eff_squad[eff_squad.index(o_id)] = i_id
                eff_bank -= st.get("cost_tenths", 0)
                purch_prices_int.pop(o_id, None)
                purch_prices_int[i_id] = st.get(
                    "in_price_tenths",
                    players_map[i_id].price_tenths if i_id in players_map else 50,
                )
        if not free_hits_active:
            eff_fts = max(0, self.free_transfers - len(self.transfers_staged))

        best_starters, best_bench, best_cap, best_vc, best_xp = select_best_lineup(eff_squad, projections)

        # Decide recommended transfers
        rec_transfers = engine.decide_transfers(
            strategy_name="balanced",
            current_squad_ids=eff_squad,
            purchase_prices=purch_prices_int,
            bank_tenths=eff_bank,
            free_transfers=eff_fts,
            snapshot=snapshot,
            projections=projections,
        )
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

        # Capture pre-gameweek state snapshots for 1:1 undo and decision logging
        gw_start = getattr(self, "gw_start_state", None)
        if not isinstance(gw_start, dict) or gw_start.get("gameweek") != gw:
            gw_start = self._reconstruct_gw_start_state()
        pre_squad_ids = list(gw_start.get("squad_ids", self.squad_ids))
        pre_prices = dict(gw_start.get("purchase_prices_tenths", self.purchase_prices_tenths))
        pre_bank = int(gw_start.get("bank_tenths", self.bank_tenths))
        pre_fts = int(gw_start.get("free_transfers", self.free_transfers))
        pre_starters = list(gw_start.get("starting_ids", self.starting_ids))
        pre_bench = list(gw_start.get("bench_ids", self.bench_ids))
        pre_cap = int(gw_start.get("captain_id", self.captain_id))
        pre_vc = int(gw_start.get("vice_captain_id", self.vice_captain_id))
        pre_chips_rem = list(gw_start.get("chips_remaining", self.chips_remaining))
        pre_chips_used = dict(gw_start.get("chips_used", self.chips_used))

        # Ensure pre_starters and pre_bench strictly belong to pre_squad_ids
        if set(pre_starters + pre_bench) != set(pre_squad_ids) or len(pre_starters) != 11 or len(pre_bench) != 4:
            rev_map = {st["in_id"]: st["out_id"] for st in self.transfers_staged}
            cand_st = [rev_map.get(x, x) for x in pre_starters]
            cand_bn = [rev_map.get(x, x) for x in pre_bench]
            if set(cand_st + cand_bn) == set(pre_squad_ids) and len(cand_st) == 11 and len(cand_bn) == 4:
                pre_starters = cand_st
                pre_bench = cand_bn
                pre_cap = rev_map.get(pre_cap, pre_cap)
                pre_vc = rev_map.get(pre_vc, pre_vc)
            else:
                try:
                    projs_pre = reconstruct_features_and_project(snapshot)
                    pre_starters, pre_bench, pre_cap, pre_vc, _ = select_best_lineup(pre_squad_ids, projs_pre)
                except Exception:
                    pass
        if pre_cap not in pre_starters and pre_starters:
            pre_cap = pre_starters[0]
        if (pre_vc not in pre_starters or pre_vc == pre_cap) and len(pre_starters) > 1:
            pre_vc = next((x for x in pre_starters if x != pre_cap), pre_starters[0])

        # Normalize active_chip if an alias was set
        if self.active_chip:
            norm_chip = str(self.active_chip).strip().lower().replace("-", "_").replace(" ", "_")
            chip_alias_map = {
                "wildcard": "wildcard_1" if gw <= 19 else "wildcard_2",
                "wildcard_1": "wildcard_1",
                "wildcard_2": "wildcard_2",
                "wc": "wildcard_1" if gw <= 19 else "wildcard_2",
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
            self.active_chip = chip_alias_map.get(norm_chip, self.active_chip)

        # If Free Hit, stash pre-free-hit state before applying transfers
        if self.active_chip == "free_hit":
            if not self.pre_free_hit_state or self.pre_free_hit_state.get("gameweek") != gw:
                self.pre_free_hit_state = {
                    "gameweek": gw,
                    "squad_ids": list(pre_squad_ids),
                    "purchase_prices_tenths": dict(pre_prices),
                    "bank_tenths": pre_bank,
                }
        else:
            self.pre_free_hit_state = None

        # 1a. Collapse chained staged transfers (A -> B, B -> C => A -> C) on unapplied transfers
        is_free_chip = bool(
            self.active_chip
            and (self.active_chip.startswith("wildcard") or self.active_chip in ("free_hit", "freehit"))
        )
        if self.transfers_staged:
            from ..transfers import Transfer
            # If all are already applied, preserve them; otherwise collapse unapplied chains
            unapplied = [st for st in self.transfers_staged if not st.get("already_applied")]
            applied = [st for st in self.transfers_staged if st.get("already_applied")]
            if unapplied:
                tx_objs = [
                    Transfer(outgoing_id=st["out_id"], incoming_id=st["in_id"])
                    for st in unapplied
                ]
                collapsed = resolve_chained_transfers(tx_objs)
                collapsed_unapplied = []
                for t in collapsed:
                    orig_st = next(
                        (s for s in unapplied if s["out_id"] == t.outgoing_id and s["in_id"] == t.incoming_id),
                        None,
                    )
                    out_p = players_map.get(t.outgoing_id)
                    in_p = players_map.get(t.incoming_id)
                    p_price = (
                        orig_st.get("out_purchase_price_tenths")
                        if orig_st and orig_st.get("out_purchase_price_tenths") is not None
                        else pre_prices.get(
                            str(t.outgoing_id),
                            self.purchase_prices_tenths.get(str(t.outgoing_id), out_p.price_tenths if out_p else 50),
                        )
                    )
                    s_price = (
                        orig_st.get("out_selling_price_tenths")
                        if orig_st and orig_st.get("out_selling_price_tenths") is not None
                        else selling_price(p_price, out_p.price_tenths if out_p else 50)
                    )
                    in_price = (
                        orig_st.get("in_price_tenths")
                        if orig_st and orig_st.get("in_price_tenths") is not None
                        else (in_p.price_tenths if in_p else 50)
                    )
                    cost = in_price - s_price

                    collapsed_unapplied.append({
                        "out_id": t.outgoing_id,
                        "in_id": t.incoming_id,
                        "out_name": out_p.web_name if out_p else f"Player {t.outgoing_id}",
                        "in_name": in_p.web_name if in_p else f"Player {t.incoming_id}",
                        "cost_tenths": cost,
                        "out_selling_price_tenths": s_price,
                        "out_purchase_price_tenths": p_price,
                        "in_price_tenths": in_price,
                        "already_applied": False,
                    })
                self.transfers_staged = applied + collapsed_unapplied

            # Execute any unapplied transfers
            for st in self.transfers_staged:
                out_id = st["out_id"]
                in_id = st["in_id"]
                cost = st.get("cost_tenths", 0)

                if not st.get("already_applied"):
                    if out_id in self.squad_ids:
                        idx = self.squad_ids.index(out_id)
                        self.squad_ids[idx] = in_id
                    self.bank_tenths -= cost
                    self.purchase_prices_tenths.pop(str(out_id), None)
                    self.purchase_prices_tenths[str(in_id)] = st.get(
                        "in_price_tenths",
                        players_map[in_id].price_tenths if in_id in players_map else 50,
                    )

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

                    st["already_applied"] = True

        num_transfers = len(self.transfers_staged)
        extra_transfers = 0 if (self.current_gw == 1 or is_free_chip) else max(0, num_transfers - self.free_transfers)
        hits_cost = extra_transfers * 4
        transfers_executed = list(self.transfers_staged)

        # 2. Re-verify lineup legality and squad membership
        if (
            len(self.starting_ids) != 11
            or len(self.bench_ids) != 4
            or set(self.starting_ids + self.bench_ids) != set(self.squad_ids)
        ):
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

        cum_net = sum(h.get("net_points", 0) for h in self.history if "gross_points" in h and h.get("gameweek") != gw) + net_points

        # Check for pre-logged decision for this gameweek to preserve user notes/metadata
        existing_hist_idx = next((i for i, h in enumerate(self.history) if h.get("gameweek") == gw), None)
        pre_decision = None
        if existing_hist_idx is not None:
            pre_decision = self.history[existing_hist_idx].get("decision_logged") or self.history[existing_hist_idx].get("decision")
        elif gw == 1 and getattr(self, "initial_decision", None):
            pre_decision = self.initial_decision

        user_notes = (pre_decision.get("notes") if pre_decision and pre_decision.get("notes") and not pre_decision.get("notes", "").startswith("Simulated matchday") else f"Simulated matchday GW{gw}")
        dec_ts = (pre_decision.get("timestamp") if pre_decision and pre_decision.get("timestamp") else datetime.now(timezone.utc).isoformat())

        # Auto-log decision record for this gameweek (1:1 with live manager Decision Logger)
        decision_obj = {
            "gameweek": gw,
            "season": self.season,
            "session_id": self.session_id,
            "timestamp": dec_ts,
            "chip_played": self.active_chip,
            "transfer_hits": extra_transfers,
            "transfers": transfers_executed,
            "squad_player_ids": list(self.squad_ids),
            "starting_player_ids": list(self.starting_ids),
            "bench_player_ids": list(self.bench_ids),
            "captain_id": self.captain_id,
            "vice_captain_id": self.vice_captain_id,
            "predicted_lineup_xp": engine_recs.get("predicted_lineup_xp", 0.0),
            "notes": user_notes,
        }

        resolution = GameweekResolution(
            gameweek=gw,
            gross_points=gross_points,
            transfer_hits=extra_transfers,
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
            squad_ids_before=pre_squad_ids,
            purchase_prices_before=pre_prices if not gw_start.get("purchase_basis_unverified") else None,
            bank_tenths_before=pre_bank,
            free_transfers_before=pre_fts,
            starting_ids_before=pre_starters,
            bench_ids_before=pre_bench,
            captain_id_before=pre_cap,
            vice_captain_id_before=pre_vc,
            chips_remaining_before=pre_chips_rem,
            chips_used_before=pre_chips_used,
            decision_logged=decision_obj,
            engine_recommendation=engine_recs,
            engine_net_points=engine_net,
            human_engine_divergence=divergence,
            purchase_basis_unverified=bool(gw_start.get("purchase_basis_unverified")),
        )
        if existing_hist_idx is not None:
            self.history[existing_hist_idx] = resolution.to_dict()
        else:
            self.history.append(resolution.to_dict())

        # 5. Post-GW updates
        if self.active_chip:
            chip_key = self.active_chip
            if gw >= 20 and chip_key in self.chips_used and self.chips_used[chip_key] <= 19:
                chip_key = f"{chip_key}_2"
            self.chips_used[chip_key] = gw
            if self.active_chip in self.chips_remaining:
                self.chips_remaining.remove(self.active_chip)
            else:
                base = self.active_chip.replace("_1", "").replace("_2", "")
                if base in self.chips_remaining:
                    self.chips_remaining.remove(base)

        # If Free Hit, revert squad state
        if self.active_chip == "free_hit" and self.pre_free_hit_state:
            self.squad_ids = list(self.pre_free_hit_state["squad_ids"])
            self.purchase_prices_tenths = dict(self.pre_free_hit_state["purchase_prices_tenths"])
            self.bank_tenths = self.pre_free_hit_state["bank_tenths"]
            self.pre_free_hit_state = None

        # Free transfer rollover
        # In FPL, Gameweek 1 (initial squad setup) does NOT roll over a free transfer into GW2.
        # Gameweek 2 always begins with exactly 1 free transfer.
        if self.active_chip in ("wildcard_1", "wildcard_2", "free_hit"):
            self.free_transfers = 1
        elif gw == 1 or gw == getattr(self, "start_gw", 1):
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
            if self.current_gw == 20:
                self.reset_chips_for_segment_2()
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
            self._capture_gw_start_state()

        self.save()
        return resolution.to_dict()

    def undo_last_gameweek(self) -> dict[str, Any]:
        """Undo the last simulated gameweek, restoring squad, bank, chips, lineup, and baseline state to the clean pre-GW state."""
        if not self.history:
            raise ValueError("No gameweeks have been simulated yet to undo.")

        # Strip any un-run pending decision entries for the current gameweek first
        while self.history and "gross_points" not in self.history[-1] and self.history[-1].get("type") != "initial_squad":
            self.history.pop()

        if not self.history:
            raise ValueError("No gameweeks have been simulated yet to undo.")

        last_entry = self.history.pop()
        # If the only entry was initial squad, cannot undo further
        if last_entry.get("type") == "initial_squad" or "gross_points" not in last_entry:
            self.history.append(last_entry)
            raise ValueError("Cannot undo initial squad creation.")

        reverted_gw = last_entry["gameweek"]

        # Validate that cost basis can be deterministically recovered
        tx_executed = last_entry.get("transfers_executed", [])
        if tx_executed and (last_entry.get("purchase_basis_unverified") or last_entry.get("purchase_prices_before") is None):
            unverified_pids = []
            for tx in tx_executed:
                o_id = tx.get("out_id")
                if o_id is not None:
                    rec_p = self._recover_trusted_purchase_price(o_id, tx)
                    if rec_p is None:
                        unverified_pids.append(o_id)
            if unverified_pids:
                self.history.append(last_entry)
                raise DataIntegrityError(
                    f"Cannot undo gameweek {reverted_gw}: legacy session is missing verified purchase price basis for outgoing player(s) {unverified_pids}.",
                    details={"gameweek": reverted_gw, "unverified_player_ids": unverified_pids},
                )

        # Restore pre-gameweek state if recorded
        if "squad_ids_before" in last_entry and last_entry["squad_ids_before"]:
            self.squad_ids = list(last_entry["squad_ids_before"])
        elif "squad_ids_after" in last_entry:
            pass

        if "purchase_prices_before" in last_entry and last_entry["purchase_prices_before"] is not None:
            self.purchase_prices_tenths = dict(last_entry["purchase_prices_before"])
        if "bank_tenths_before" in last_entry and last_entry["bank_tenths_before"] is not None:
            self.bank_tenths = int(last_entry["bank_tenths_before"])
        if "free_transfers_before" in last_entry and last_entry["free_transfers_before"] is not None:
            if reverted_gw <= 2:
                self.free_transfers = 1
            else:
                self.free_transfers = int(last_entry["free_transfers_before"])
        if "starting_ids_before" in last_entry and last_entry["starting_ids_before"]:
            self.starting_ids = list(last_entry["starting_ids_before"])
        if "bench_ids_before" in last_entry and last_entry["bench_ids_before"]:
            self.bench_ids = list(last_entry["bench_ids_before"])
        if "captain_id_before" in last_entry and last_entry["captain_id_before"]:
            self.captain_id = int(last_entry["captain_id_before"])
        if "vice_captain_id_before" in last_entry and last_entry["vice_captain_id_before"]:
            self.vice_captain_id = int(last_entry["vice_captain_id_before"])
        if "chips_remaining_before" in last_entry and last_entry["chips_remaining_before"] is not None:
            self.chips_remaining = list(last_entry["chips_remaining_before"])
        if "chips_used_before" in last_entry and last_entry["chips_used_before"] is not None:
            self.chips_used = dict(last_entry["chips_used_before"])

        self.current_gw = reverted_gw
        self.status = "active"
        self.transfers_staged = []
        self.active_chip = None
        self.pre_free_hit_state = None

        # Ensure restored lineup strictly matches restored squad_ids (fixing any legacy staged-lineup leakage)
        if (
            len(self.starting_ids) != 11
            or len(self.bench_ids) != 4
            or set(self.starting_ids + self.bench_ids) != set(self.squad_ids)
        ):
            rev_map = {}
            for tx in reversed(last_entry.get("transfers_executed", [])):
                if isinstance(tx, dict) and "in_id" in tx and "out_id" in tx:
                    rev_map[int(tx["in_id"])] = int(tx["out_id"])
            cand_st = [rev_map.get(x, x) for x in self.starting_ids]
            cand_bn = [rev_map.get(x, x) for x in self.bench_ids]
            if len(cand_st) == 11 and len(cand_bn) == 4 and set(cand_st + cand_bn) == set(self.squad_ids):
                self.starting_ids = cand_st
                self.bench_ids = cand_bn
                self.captain_id = rev_map.get(self.captain_id, self.captain_id)
                self.vice_captain_id = rev_map.get(self.vice_captain_id, self.vice_captain_id)
            else:
                try:
                    snap_rev = self.get_current_snapshot()
                    proj_rev = reconstruct_features_and_project(snap_rev)
                    self.starting_ids, self.bench_ids, self.captain_id, self.vice_captain_id, _ = select_best_lineup(
                        self.squad_ids, proj_rev
                    )
                except Exception:
                    self.starting_ids = list(self.squad_ids[:11])
                    self.bench_ids = list(self.squad_ids[11:15])
        if self.captain_id not in self.starting_ids and self.starting_ids:
            self.captain_id = self.starting_ids[0]
        if (self.vice_captain_id not in self.starting_ids or self.vice_captain_id == self.captain_id) and len(self.starting_ids) > 1:
            self.vice_captain_id = next((x for x in self.starting_ids if x != self.captain_id), self.starting_ids[0])

        # Revert baseline engine history and mutable baseline state
        if self.engine_baseline_history and self.engine_baseline_history[-1].get("gameweek") == reverted_gw:
            eng_last = self.engine_baseline_history.pop()
            if "squad_ids_before" in eng_last and eng_last["squad_ids_before"]:
                self.engine_baseline_squad_ids = list(eng_last["squad_ids_before"])
                self.engine_baseline_purchase_prices = dict(eng_last.get("purchase_prices_before") or {})
                self.engine_baseline_bank_tenths = int(eng_last.get("bank_tenths_before", 0))
                self.engine_baseline_free_transfers = (
                    1 if reverted_gw <= 2 else int(eng_last.get("free_transfers_before", 1))
                )
                if eng_last.get("chips_remaining_before") is not None:
                    self.engine_baseline_chips_remaining = list(eng_last["chips_remaining_before"])
                if eng_last.get("chips_used_before") is not None:
                    self.engine_baseline_chips_used = dict(eng_last["chips_used_before"])
            elif self.engine_baseline_history:
                prev_eng = self.engine_baseline_history[-1]
                if "squad_ids" in prev_eng and "purchase_prices_tenths" in prev_eng:
                    self.engine_baseline_squad_ids = list(prev_eng["squad_ids"])
                    self.engine_baseline_purchase_prices = dict(prev_eng["purchase_prices_tenths"])
                    self.engine_baseline_bank_tenths = int(prev_eng.get("bank_tenths", 0))
                    self.engine_baseline_free_transfers = int(prev_eng.get("free_transfers_after", 1))
                    if prev_eng.get("chips_remaining_after") is not None:
                        self.engine_baseline_chips_remaining = list(prev_eng["chips_remaining_after"])
                    if prev_eng.get("chips_used_after") is not None:
                        self.engine_baseline_chips_used = dict(prev_eng["chips_used_after"])
                else:
                    raise DataIntegrityError(
                        f"Legacy session missing pre-GW baseline state for GW{reverted_gw}; cannot deterministically restore baseline engine state.",
                        details={"session_id": self.session_id, "gameweek": reverted_gw},
                    )
            elif reverted_gw == getattr(self, "start_gw", 1):
                self.engine_baseline_squad_ids = list(self.squad_ids)
                self.engine_baseline_purchase_prices = dict(self.purchase_prices_tenths)
                self.engine_baseline_bank_tenths = int(self.bank_tenths)
                self.engine_baseline_free_transfers = 1
                self.engine_baseline_chips_remaining = list(self.chips_remaining)
                self.engine_baseline_chips_used = dict(self.chips_used)

        self._capture_gw_start_state()
        self.save()
        return {
            "success": True,
            "undone_gameweek": reverted_gw,
            "current_gw": self.current_gw,
            "squad": self.get_squad_player_details(),
            "bank_tenths": self.bank_tenths,
            "free_transfers": self.free_transfers,
            "chips_remaining": self.chips_remaining,
            "chips_used": self.chips_used,
        }

    def _step_baseline_engine(
        self,
        gw: int,
        snapshot: HistoricalGameweekSnapshot,
        outcomes: dict[int, GameweekOutcome],
        player_positions: dict[int, Position],
    ) -> int:
        """Step the parallel frozen baseline engine on its own squad trajectory with chip execution."""
        eng_pre_squad_ids = list(self.engine_baseline_squad_ids)
        eng_pre_prices = dict(self.engine_baseline_purchase_prices)
        eng_pre_bank = int(self.engine_baseline_bank_tenths)
        eng_pre_fts = int(self.engine_baseline_free_transfers)
        eng_pre_chips_rem = list(self.engine_baseline_chips_remaining)
        eng_pre_chips_used = dict(self.engine_baseline_chips_used)

        engine_ver = getattr(self, "engine_baseline_version", "v1.3.5")
        engine = resolve_decision_engine(engine_ver)
        projections = reconstruct_features_and_project(snapshot)
        proj_map = {p.player_id: p for p in projections}
        players_by_id = {p.player_id: p for p in snapshot.players}

        # 1. Evaluate chip deployment via SeasonalChipPolicy
        eng_avail = {c.lower().replace("-", "_") for c in self.engine_baseline_chips_remaining}
        if gw <= 19:
            chip_inventory = SeasonalChipInventory(
                wildcard_w1="wildcard_1" in eng_avail or "wildcard" in eng_avail,
                free_hit_w1="free_hit" in eng_avail or "freehit" in eng_avail,
                triple_captain_w1="triple_captain" in eng_avail or "triplecaptain" in eng_avail,
                bench_boost_w1="bench_boost" in eng_avail or "benchboost" in eng_avail,
                wildcard_w2=True,
                free_hit_w2=True,
                triple_captain_w2=True,
                bench_boost_w2=True,
            )
        else:
            chip_inventory = SeasonalChipInventory(
                wildcard_w1=False,
                free_hit_w1=False,
                triple_captain_w1=False,
                bench_boost_w1=False,
                wildcard_w2="wildcard_2" in eng_avail or "wildcard" in eng_avail,
                free_hit_w2="free_hit" in eng_avail or "freehit" in eng_avail,
                triple_captain_w2="triple_captain" in eng_avail or "triplecaptain" in eng_avail,
                bench_boost_w2="bench_boost" in eng_avail or "benchboost" in eng_avail,
            )
        policy = SeasonalChipPolicy(
            use_optimizer=self.baseline_chip_use_optimizer,
            optimizer_variant=self.baseline_chip_optimizer_variant,
        )
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
            if gw == 1 or gw == getattr(self, "start_gw", 1):
                self.engine_baseline_free_transfers = 1
            else:
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
            used_key = canon_key
            if gw >= 20 and used_key in self.engine_baseline_chips_used and self.engine_baseline_chips_used[used_key] <= 19:
                used_key = f"{used_key}_2"
            self.engine_baseline_chips_used[used_key] = gw
            if canon_key in self.engine_baseline_chips_remaining:
                self.engine_baseline_chips_remaining.remove(canon_key)
            else:
                base = canon_key.replace("_1", "").replace("_2", "")
                if base in self.engine_baseline_chips_remaining:
                    self.engine_baseline_chips_remaining.remove(base)

        # Free hit squad revert
        if current_chip == "free_hit" and saved_squad_ids is not None:
            self.engine_baseline_squad_ids = saved_squad_ids
            self.engine_baseline_purchase_prices = saved_prices
            self.engine_baseline_bank_tenths = saved_bank

        self.engine_baseline_history.append({
            "gameweek": gw,
            "gross_points": gross_pts,
            "transfer_hits": hits // 4,
            "transfer_hit_points": hits,
            "hit_unit": "count",
            "net_points": net_pts,
            "chip_used": current_chip,
            "transfers": txs,
            "squad_ids": list(self.engine_baseline_squad_ids),
            "bank_tenths": self.engine_baseline_bank_tenths,
            "purchase_prices_tenths": dict(self.engine_baseline_purchase_prices),
            "free_transfers_after": self.engine_baseline_free_transfers,
            "chips_remaining_after": list(self.engine_baseline_chips_remaining),
            "chips_used_after": dict(self.engine_baseline_chips_used),
            "squad_ids_before": eng_pre_squad_ids,
            "purchase_prices_before": eng_pre_prices,
            "bank_tenths_before": eng_pre_bank,
            "free_transfers_before": eng_pre_fts,
            "chips_remaining_before": eng_pre_chips_rem,
            "chips_used_before": eng_pre_chips_used,
        })
        return net_pts

    # -------------------------------------------------------------------------
    # Analytics & Season Report Export
    # -------------------------------------------------------------------------

    def generate_summary(self) -> SimulationSummary:
        """Generate high-level season simulation summary."""
        self._normalize_history_hit_units()
        completed_hist = [h for h in self.history if isinstance(h, dict) and "gross_points" in h]
        tot_gross = sum(h.get("gross_points", 0) for h in completed_hist)
        tot_hits = sum(h.get("transfer_hits", 0) for h in completed_hist)
        tot_net = sum(h.get("net_points", 0) for h in completed_hist)
        tot_txs = sum(len(h.get("transfers_executed", [])) for h in completed_hist)
        cap_pts = sum(h.get("captain_points", 0) for h in completed_hist)
        cap_proms = sum(1 for h in completed_hist if h.get("captain_promoted"))
        autosub_cnt = sum(len(h.get("autosubs", [])) for h in completed_hist)

        engine_tot = sum(e.get("net_points", 0) for e in self.engine_baseline_history) if self.engine_baseline_history else None
        delta = (tot_net - engine_tot) if engine_tot is not None else None

        overrides = [h for h in completed_hist if h.get("human_engine_divergence", {}).get("human_override")]
        pos_overrides = sum(1 for h in overrides if h.get("human_engine_divergence", {}).get("point_delta_vs_engine", 0) > 0)
        neg_overrides = sum(1 for h in overrides if h.get("human_engine_divergence", {}).get("point_delta_vs_engine", 0) < 0)

        last_val = completed_hist[-1].get("squad_value_tenths_after", 1000) if completed_hist else 1000

        return SimulationSummary(
            session_id=self.session_id,
            season=self.season,
            gameweeks_completed=len(completed_hist),
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
            f"- **Total Transfer Hits Cost:** -{summary.total_transfer_hits * 4} pts ({summary.total_transfer_hits} hits)",
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
            if not isinstance(h, dict) or "gross_points" not in h:
                continue
            gw_num = h["gameweek"]
            gross = h["gross_points"]
            hits = h["transfer_hits"]
            net = h["net_points"]
            cum = h["cumulative_net_points"]
            chip = h.get("chip_used") or "-"
            e_net = h.get("engine_net_points", "-")
            delta_val = h.get("human_engine_divergence", {}).get("point_delta_vs_engine", "-")
            lines.append(f"| GW{gw_num:02d} | {gross} | -{hits * 4} | {net} | {cum} | {h['effective_captain_id']} | {chip} | {e_net} | {delta_val} |")

        md_path.write_text("\n".join(lines), encoding="utf-8")
        return json_path, md_path
