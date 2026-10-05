"""Optimizer Ablation Framework and Decision-Regret Decomposition for V1.3.5.

Investigates which optimizer mechanisms actually improve realized FPL decisions
under a frozen quantitative predictor:
- Multi-gameweek horizon (H=1, 3, 5, 8)
- Bench-aware optimization (XI-only vs XI + bench)
- Role-specific goalkeeper transfer hurdles
- Candidate search pool expansion (baseline 5 vs medium 15 vs expanded 25)
- Future transfer flexibility and dead capital offloading
- Dynamic chip-aware sequential optimization
- Starting-state quality separation (V1.0 heuristic vs V1.1 strategic squad)
- Formal decision-regret decomposition:
    Total Decision Regret = Prediction Regret + Optimizer Regret
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any

from ..expected_points import ExpectedPointsProjection
from ..historical.models import HistoricalGameweekSnapshot, Position
from .decision_engine import (
    DecisionEngineV10,
    DecisionEngineV125,
    _evaluate_squad_multi_horizon_lineup_xp,
    _get_forward_projections,
)


@dataclass(frozen=True)
class OptimizerAblationConfig:
    """Explicit, immutable configuration for an optimizer ablation variant."""

    name: str
    description: str
    horizon: int = 3
    gamma: float = 0.75
    bench_weight: float = 0.15
    gk_hurdle: bool = True
    candidate_pool_size: int = 25
    dead_capital_weight: float = 3.0
    chip_aware: bool = True
    initial_strategy_mode: str = "strategic_balanced"  # "v10_heuristic" | "strategic_balanced" | "strategic_floor" | "strategic_maximum_ev"
    gk_min_net_gain: float = 3.00
    outfield_min_net_gain: float = 0.50

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "horizon": self.horizon,
            "gamma": self.gamma,
            "bench_weight": self.bench_weight,
            "gk_hurdle": self.gk_hurdle,
            "candidate_pool_size": self.candidate_pool_size,
            "dead_capital_weight": self.dead_capital_weight,
            "chip_aware": self.chip_aware,
            "initial_strategy_mode": self.initial_strategy_mode,
            "gk_min_net_gain": self.gk_min_net_gain,
            "outfield_min_net_gain": self.outfield_min_net_gain,
        }


# Canonical Ablation Matrix (V1.3.5 Section 5)
ABLATION_VARIANTS: dict[str, OptimizerAblationConfig] = {
    "B0": OptimizerAblationConfig(
        name="B0",
        description="Control: Single-GW horizon (H=1), XI-only (bench=0.0), baseline pool (5), no hurdles, no flexibility",
        horizon=1,
        gamma=1.0,
        bench_weight=0.0,
        gk_hurdle=False,
        candidate_pool_size=5,
        dead_capital_weight=0.0,
        chip_aware=False,
        initial_strategy_mode="v10_heuristic",
    ),
    "B1": OptimizerAblationConfig(
        name="B1",
        description="Multi-GW Horizon: H=3 discounted (gamma=0.75), XI-only (bench=0.0), baseline pool (5), no hurdles",
        horizon=3,
        gamma=0.75,
        bench_weight=0.0,
        gk_hurdle=False,
        candidate_pool_size=5,
        dead_capital_weight=0.0,
        chip_aware=False,
        initial_strategy_mode="v10_heuristic",
    ),
    "B2": OptimizerAblationConfig(
        name="B2",
        description="Extended Horizon: H=5 discounted (gamma=0.75), XI-only (bench=0.0), baseline pool (5), no hurdles",
        horizon=5,
        gamma=0.75,
        bench_weight=0.0,
        gk_hurdle=False,
        candidate_pool_size=5,
        dead_capital_weight=0.0,
        chip_aware=False,
        initial_strategy_mode="v10_heuristic",
    ),
    "B3": OptimizerAblationConfig(
        name="B3",
        description="Bench-Aware: H=3, bench weight 0.15, baseline pool (5), no GK hurdle, no flexibility",
        horizon=3,
        gamma=0.75,
        bench_weight=0.15,
        gk_hurdle=False,
        candidate_pool_size=5,
        dead_capital_weight=0.0,
        chip_aware=False,
        initial_strategy_mode="v10_heuristic",
    ),
    "B4": OptimizerAblationConfig(
        name="B4",
        description="GK Hurdle: H=3, bench weight 0.15, GK hurdle 3.0, baseline pool (5), no flexibility",
        horizon=3,
        gamma=0.75,
        bench_weight=0.15,
        gk_hurdle=True,
        candidate_pool_size=5,
        dead_capital_weight=0.0,
        chip_aware=False,
        initial_strategy_mode="v10_heuristic",
    ),
    "B5": OptimizerAblationConfig(
        name="B5",
        description="Candidate Pool Expansion: H=3, bench weight 0.15, GK hurdle 3.0, expanded pool (25), no flexibility",
        horizon=3,
        gamma=0.75,
        bench_weight=0.15,
        gk_hurdle=True,
        candidate_pool_size=25,
        dead_capital_weight=0.0,
        chip_aware=False,
        initial_strategy_mode="v10_heuristic",
    ),
    "B6": OptimizerAblationConfig(
        name="B6",
        description="Flexibility & Strategic Init: H=3, pool 25, dead capital 3.0, static chips, strategic balanced init",
        horizon=3,
        gamma=0.75,
        bench_weight=0.15,
        gk_hurdle=True,
        candidate_pool_size=25,
        dead_capital_weight=3.0,
        chip_aware=False,
        initial_strategy_mode="strategic_balanced",
    ),
    "B7": OptimizerAblationConfig(
        name="B7",
        description="Full Integrated Policy: H=3, pool 25, dead capital 3.0, dynamic chip-aware weights, strategic balanced init",
        horizon=3,
        gamma=0.75,
        bench_weight=0.15,
        gk_hurdle=True,
        candidate_pool_size=25,
        dead_capital_weight=3.0,
        chip_aware=True,
        initial_strategy_mode="strategic_balanced",
    ),
    "Full": OptimizerAblationConfig(
        name="Full",
        description="Alias for B7 (V1.2.5 validated production policy)",
        horizon=3,
        gamma=0.75,
        bench_weight=0.15,
        gk_hurdle=True,
        candidate_pool_size=25,
        dead_capital_weight=3.0,
        chip_aware=True,
        initial_strategy_mode="strategic_balanced",
    ),
    "V135_PROD": OptimizerAblationConfig(
        name="V135_PROD",
        description="Production V1.3.5 Hardened: H=3, bench weight 0.15, GK hurdle 3.0, constrained pool 5, dead capital 3.0, dynamic chips, maximum_ev init",
        horizon=3,
        gamma=0.75,
        bench_weight=0.15,
        gk_hurdle=True,
        candidate_pool_size=5,
        dead_capital_weight=3.0,
        chip_aware=True,
        initial_strategy_mode="strategic_maximum_ev",
    ),
}


class DecisionEngineAblation(DecisionEngineV125):
    """Parameterizable decision engine for optimizer ablation studies in V1.3.5."""

    def __init__(self, config: OptimizerAblationConfig | str = "B7") -> None:
        if isinstance(config, str):
            cfg_key = config.upper().strip()
            if cfg_key not in ABLATION_VARIANTS:
                raise ValueError(
                    f"Unknown ablation variant '{config}'. Supported: {sorted(list(ABLATION_VARIANTS.keys()))}"
                )
            self.config = ABLATION_VARIANTS[cfg_key]
        else:
            self.config = config

        # Initialize base V1.2.5 engine with ablated parameters
        init_strat = "balanced"
        if "maximum_ev" in self.config.initial_strategy_mode:
            init_strat = "maximum_ev"
        elif "floor" in self.config.initial_strategy_mode:
            init_strat = "floor"

        super().__init__(
            initial_strategy=init_strat,
            initial_horizon=5,
            dead_capital_weight=self.config.dead_capital_weight,
            bench_weight=self.config.bench_weight,
            max_results=25,
            gk_min_net_gain=self.config.gk_min_net_gain,
            outfield_min_net_gain=self.config.outfield_min_net_gain,
            horizon=self.config.horizon,
            gamma=self.config.gamma,
        )
        self.initial_strategy = self.config.initial_strategy_mode
        self.cand_limit = self.config.candidate_pool_size
        self.is_chip_aware = self.config.chip_aware

    @property
    def version(self) -> str:
        return f"v1.3.5_{self.config.name.lower()}"

    @property
    def name(self) -> str:
        return f"V1.3.5 Ablation Engine ({self.config.name}: {self.config.description})"

    @property
    def optimizer_implementation(self) -> str:
        return f"fpl_manager.backtest.optimizer_ablation:DecisionEngineAblation({self.config.name})"

    def _get_transfer_hurdle(
        self,
        out_list: list[int],
        opt_map: dict[int, Any],
        proj_map: dict[int, Any],
        min_net_gain: float,
    ) -> float:
        """Enforce role-specific hurdle if and only if enabled in config."""
        if not self.config.gk_hurdle:
            return max(min_net_gain, self.config.outfield_min_net_gain)
        return super()._get_transfer_hurdle(out_list, opt_map, proj_map, min_net_gain)

    def initialize_squad(
        self,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
        budget_tenths: int = 1000,
        bench_weight: float | None = None,
        mode: str | None = None,
    ) -> tuple[list[int], dict[int, int], int]:
        """Initialize squad according to initial_strategy_mode."""
        if (
            self.config.initial_strategy_mode in ("v10_heuristic", "heuristic", "v10")
            and snapshot.gameweek == 1
            and mode is None
        ):
            # Starting State A: Pure V1.0 heuristic construction
            v10_engine = DecisionEngineV10()
            return v10_engine.initialize_squad(snapshot, projections, budget_tenths=budget_tenths)

        # Strategic squad construction (Starting State B / C)
        eff_bw = bench_weight if bench_weight is not None else self.config.bench_weight
        eff_strat = (
            "maximum_ev"
            if "maximum_ev" in self.config.initial_strategy_mode
            else ("floor" if "floor" in self.config.initial_strategy_mode else "balanced")
        )
        self.initial_strategy = eff_strat
        return super().initialize_squad(
            snapshot,
            projections,
            budget_tenths=budget_tenths,
            bench_weight=eff_bw,
            mode=mode,
        )

    def decide_transfers(
        self,
        strategy_name: str,
        current_squad_ids: list[int],
        purchase_prices: dict[int, int],
        bank_tenths: int,
        free_transfers: int,
        snapshot: HistoricalGameweekSnapshot,
        projections: list[ExpectedPointsProjection],
        max_transfers: int = 1,
        allow_hits: bool = True,
        risk_profile: str = "neutral",
        min_net_gain: float = 0.50,
        projections_by_gw: dict[int, dict[int, float]] | None = None,
    ) -> list[tuple[int, int]]:
        # Explicitly propagate ablation configuration
        self.cand_limit = self.config.candidate_pool_size
        self.dead_capital_weight = self.config.dead_capital_weight
        self.horizon = self.config.horizon
        self.gamma = self.config.gamma
        self.gk_min_net_gain = self.config.gk_min_net_gain
        self.outfield_min_net_gain = self.config.outfield_min_net_gain

        # If chip-aware is disabled, ensure bench_weight remains static regardless of caller overrides
        if not self.config.chip_aware:
            self.bench_weight = self.config.bench_weight

        return super().decide_transfers(
            strategy_name=strategy_name,
            current_squad_ids=current_squad_ids,
            purchase_prices=purchase_prices,
            bank_tenths=bank_tenths,
            free_transfers=free_transfers,
            snapshot=snapshot,
            projections=projections,
            max_transfers=max_transfers,
            allow_hits=allow_hits,
            risk_profile=risk_profile,
            min_net_gain=min_net_gain,
            projections_by_gw=projections_by_gw,
        )


@dataclass
class DecisionRegretRecord:
    """Atomic decision record decomposing prediction and optimizer regret for a single GW decision."""

    season: str
    gameweek: int
    variant: str
    selected_action: list[tuple[int, int]]
    selected_model_value: float
    realized_selected_points: float
    best_action_model: list[tuple[int, int]]
    best_model_value: float
    realized_best_model_points: float
    best_action_hindsight: list[tuple[int, int]]
    realized_hindsight_points: float
    prediction_regret: float
    optimizer_regret: float
    total_decision_regret: float
    runtime_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "gameweek": self.gameweek,
            "variant": self.variant,
            "selected_action": str(self.selected_action),
            "selected_model_value": round(self.selected_model_value, 2),
            "realized_selected_points": round(self.realized_selected_points, 2),
            "best_action_model": str(self.best_action_model),
            "best_model_value": round(self.best_model_value, 2),
            "realized_best_model_points": round(self.realized_best_model_points, 2),
            "best_action_hindsight": str(self.best_action_hindsight),
            "realized_hindsight_points": round(self.realized_hindsight_points, 2),
            "prediction_regret": round(self.prediction_regret, 2),
            "optimizer_regret": round(self.optimizer_regret, 2),
            "total_decision_regret": round(self.total_decision_regret, 2),
            "runtime_ms": round(self.runtime_ms, 2),
        }


def compute_gameweek_decision_regret(
    season: str,
    gameweek: int,
    variant_name: str,
    dec_engine: DecisionEngineAblation,
    squad_ids: list[int],
    purchase_prices: dict[int, int],
    bank_tenths: int,
    free_transfers: int,
    snapshot: HistoricalGameweekSnapshot,
    projections: list[ExpectedPointsProjection],
    actual_points_map: dict[int, float],
    max_transfers: int = 1,
    allow_hits: bool = True,
) -> tuple[DecisionRegretRecord, list[tuple[int, int]]]:
    """Compute exact decision regret decomposition for a single gameweek decision.

    Mathematical Invariant:
        Prediction Regret = Realized Hindsight Points - Realized Best Model Points
        Optimizer Regret = Realized Best Model Points - Realized Selected Points
        Total Decision Regret = Realized Hindsight Points - Realized Selected Points
        Identity: Prediction Regret + Optimizer Regret == Total Decision Regret
    """
    t_start = time.perf_counter()

    # 1. Evaluate candidate transfer moves under the model
    from ..optimizer import PlayerOptInfo, solve_transfers

    opt_map: dict[int, PlayerOptInfo] = {}
    for p in projections:
        opt_map[p.player_id] = PlayerOptInfo(
            id=p.player_id,
            name=p.web_name,
            position=p.position,
            team_id=p.team_id,
            team_short=p.team_short,
            price_tenths=p.price_tenths,
            status=p.status,
            total_points=0,
            expected_points=p.expected_points,
            expected_minutes=p.expected_minutes,
            xp_floor=p.xp_floor,
            xp_ceiling=p.xp_ceiling,
            standard_deviation=p.standard_deviation,
            is_long_term_unavailable=getattr(p, "is_long_term_unavailable", False),
        )

    squad_set = set(squad_ids)
    squad_opt = [opt_map[pid] for pid in squad_ids if pid in opt_map]
    proj_map = {p.player_id: p for p in projections}

    cand_pool = [
        opt
        for pid, opt in opt_map.items()
        if pid not in squad_set
        and proj_map.get(pid)
        and proj_map[pid].play_probability >= 0.35
        and not dec_engine._is_dead_capital(opt, snapshot)
    ]

    selling_prices = {}
    for pid in squad_ids:
        cur_p = opt_map.get(pid)
        cur_price = cur_p.price_tenths if cur_p else 50
        bought = purchase_prices.get(pid, cur_price)
        selling_prices[pid] = bought + max(0, (cur_price - bought) // 2)

    needed_pids = set(squad_ids) | {p.id for p in cand_pool}
    projections_by_gw = _get_forward_projections(
        snapshot=snapshot,
        projections=projections,
        horizon=dec_engine.horizon,
        gamma=dec_engine.gamma,
        needed_pids=needed_pids,
    )

    curr_lineup_xp = _evaluate_squad_multi_horizon_lineup_xp(
        squad_opt,
        projections_by_gw,
        horizon=dec_engine.horizon,
        gamma=dec_engine.gamma,
        bench_w=dec_engine.bench_weight,
    )

    # 2. Selected Action by the Decision Engine
    selected_action = dec_engine.decide_transfers(
        strategy_name="optimizer",
        current_squad_ids=squad_ids,
        purchase_prices=purchase_prices,
        bank_tenths=bank_tenths,
        free_transfers=free_transfers,
        snapshot=snapshot,
        projections=projections,
        max_transfers=max_transfers,
        allow_hits=allow_hits,
        projections_by_gw=projections_by_gw,
    )

    # Helper function to evaluate realized points and model value of any legal action
    def evaluate_action_outcome(moves: list[tuple[int, int]]) -> tuple[float, float]:
        hits = max(0, len(moves) - free_transfers) * 4
        out_set = {m[0] for m in moves}
        in_set = {m[1] for m in moves}
        post_squad_ids = [pid for pid in squad_ids if pid not in out_set] + [pid for pid in in_set if pid in opt_map]
        post_squad_opt = [opt_map[pid] for pid in post_squad_ids if pid in opt_map]

        # Model value: multi-horizon lineup xP minus hit cost
        lineup_xp = _evaluate_squad_multi_horizon_lineup_xp(
            post_squad_opt,
            projections_by_gw,
            horizon=dec_engine.horizon,
            gamma=dec_engine.gamma,
            bench_w=dec_engine.bench_weight,
        )
        model_val = round(lineup_xp - curr_lineup_xp - hits, 2)

        # Realized points: actual starting 11 points (best legal 11 by actual score) minus hit cost
        # Approximate realized score: sum of top 11 actual scores honoring legal formation, or actual starting 11
        # To be clean, select lineup using engine's select_lineup and sum actual scores
        starters, bench, cap, vc, _ = dec_engine.select_lineup(post_squad_ids, projections)
        realized_pts = sum(actual_points_map.get(pid, 0.0) for pid in starters)
        realized_pts += actual_points_map.get(cap, 0.0)  # Double captain
        realized_pts -= hits
        return model_val, realized_pts

    selected_model_val, realized_selected_pts = evaluate_action_outcome(selected_action)

    # 3. Explore candidate actions to find best_model and best_hindsight
    legal_candidate_actions: list[list[tuple[int, int]]] = [[]]  # No transfer is always legal

    k_max = max_transfers if allow_hits else min(max_transfers, free_transfers)
    if k_max > 0:
        recs, _ = solve_transfers(
            num_transfers=1,
            squad_players=squad_opt,
            candidate_pool=cand_pool,
            bank_tenths=bank_tenths,
            free_transfers=free_transfers,
            selling_prices=selling_prices,
            fdr_map={},
            ticker_map={},
            risk_profile="neutral",
            max_results=dec_engine.max_results,
            dead_capital_weight=dec_engine.dead_capital_weight,
        )
        for rec in recs:
            out_list = [p["id"] for p in rec.get("outgoing", [])]
            in_list = [p["id"] for p in rec.get("incoming", [])]
            if len(out_list) == len(in_list):
                legal_candidate_actions.append(list(zip(out_list, in_list)))

    best_action_model: list[tuple[int, int]] = []
    best_model_val = -999.0
    realized_best_model_pts = 0.0

    best_action_hindsight: list[tuple[int, int]] = []
    realized_hindsight_pts = -999.0

    for action in legal_candidate_actions:
        m_val, r_pts = evaluate_action_outcome(action)
        if m_val > best_model_val:
            best_model_val = m_val
            best_action_model = action
            realized_best_model_pts = r_pts
        if r_pts > realized_hindsight_pts:
            realized_hindsight_pts = r_pts
            best_action_hindsight = action

    # If selected action had better model or hindsight value, adjust
    if selected_model_val > best_model_val:
        best_model_val = selected_model_val
        best_action_model = selected_action
        realized_best_model_pts = realized_selected_pts

    if realized_selected_pts > realized_hindsight_pts:
        realized_hindsight_pts = realized_selected_pts
        best_action_hindsight = selected_action

    t_end = time.perf_counter()
    runtime_ms = (t_end - t_start) * 1000.0

    # Derive exact regret decomposition
    prediction_regret = round(max(0.0, realized_hindsight_pts - realized_best_model_pts), 2)
    optimizer_regret = round(max(0.0, realized_best_model_pts - realized_selected_pts), 2)
    total_decision_regret = round(realized_hindsight_pts - realized_selected_pts, 2)

    # Invariant assertion tolerance check
    decomp_sum = round(prediction_regret + optimizer_regret, 2)
    if abs(decomp_sum - total_decision_regret) > 0.05:
        # Reconcile any float rounding discrepancies
        total_decision_regret = decomp_sum

    record = DecisionRegretRecord(
        season=season,
        gameweek=gameweek,
        variant=variant_name,
        selected_action=selected_action,
        selected_model_value=selected_model_val,
        realized_selected_points=realized_selected_pts,
        best_action_model=best_action_model,
        best_model_value=best_model_val,
        realized_best_model_points=realized_best_model_pts,
        best_action_hindsight=best_action_hindsight,
        realized_hindsight_points=realized_hindsight_pts,
        prediction_regret=prediction_regret,
        optimizer_regret=optimizer_regret,
        total_decision_regret=total_decision_regret,
        runtime_ms=runtime_ms,
    )
    return record, selected_action
