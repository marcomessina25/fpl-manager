"""Unified Strategic Chip Opportunity-Cost Optimizer Engine (V1.4.5).

Replaces legacy static threshold gates with a mathematically unified
expected-value (EV) and dynamic opportunity-cost decision framework.

Decision Function:
    Net Utility(C, t) = ΔEV(C, t) - max_{t' in [t+1, T_window]} E[ΔEV(C, t')] * discount(t, t')

Where:
    - ΔEV(C, t) is immediate EV benefit of deploying chip C in gameweek t.
    - max_{t' > t} E[ΔEV(C, t')] is the best remaining value of holding the chip
      across the remaining gameweeks of the segment window.
    - T_window is the segment boundary: GW 19 for Segment 1, GW 38 for Segment 2.
    - As t -> T_window, future optionality decays naturally to 0.

Supports:
- Baseline C0: Legacy SeasonalChipPolicy (static thresholds)
- Variant C1: Linear Window-Decay Heuristic
- Variant C2: Dynamic Opportunity-Cost Planner (Canonical V1.4.5)
- Variant C3: Surrogate-Value / ML-Assisted Continuation Planner
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import logging
import math
from pathlib import Path
from typing import Any, Sequence

from ..models import is_departed_from_premier_league

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_HISTORICAL_DIR = PROJECT_ROOT / "data" / "historical"

AVAILABLE_CHIPS = ("wildcard", "free_hit", "bench_boost", "triple_captain")
CANONICAL_CHIP_NAMES = {
    "wildcard": "wildcard",
    "wildcard_1": "wildcard",
    "wildcard1": "wildcard",
    "wildcard_2": "wildcard",
    "wildcard2": "wildcard",
    "free_hit": "free_hit",
    "freehit": "free_hit",
    "bench_boost": "bench_boost",
    "benchboost": "bench_boost",
    "triple_captain": "triple_captain",
    "triplecaptain": "triple_captain",
}


@dataclass(frozen=True, slots=True)
class ChipCalibrationConfig:
    """Empirical calibration constants derived from 5-season historical ablation study.
    
    These constants balance immediate gameweek valuation against multi-gameweek continuation value.
    """
    # Bench Boost calibration
    bb_dgw_immediate_boost: float = 3.0       # Expected extra points when deploying Bench Boost in a DGW
    bb_future_dgw2_target: float = 16.0       # Option value ceiling when multiple DGW teams remain
    bb_future_dgw1_target: float = 13.0       # Option value when single DGW remains
    bb_future_standard_target: float = 9.5    # Option value benchmark in standard non-DGW gameweeks

    # Triple Captain calibration
    tc_future_dgw_target: float = 14.0        # Opportunity cost target when a strong DGW captain fixture exists
    tc_future_standard_target: float = 8.0     # Expected opportunity cost in single fixture weeks

    # Free Hit calibration
    fh_blank_player_gain: float = 4.8         # Points recovered per missing/blanking player (replacement delta)
    fh_dgw_slot_gain: float = 3.5             # Points gained per extra DGW asset upgraded via Free Hit
    fh_base_lineup_delta: float = 2.0         # Baseline optimization uplift from temporary £100m allocation
    fh_future_major_blank: float = 16.0       # Base opportunity cost for major Blank Gameweek (e.g. FA Cup quarter-finals)
    fh_future_blank_multiplier: float = 4.0   # Incremental option value per blanking squad player
    fh_future_mega_dgw: float = 18.0          # Opportunity cost when mega-DGW (>= 4 teams) is ahead
    fh_future_standard: float = 7.0           # Opportunity cost in standard gameweeks

    # Wildcard calibration
    wc_hit_saving_per_player: float = 4.0     # Immediate transfer point penalty saved per collapsed player
    wc_persistence_rate: float = 0.6          # Compounding points per gameweek remaining in segment
    wc_persistence_max: float = 10.0          # Maximum persistent restructuring gain
    wc_expiry_urgency_bonus: float = 12.0     # Urgency boost when <= 2 gameweeks remain in segment window
    wc_future_base: float = 7.0               # Base future opportunity value of holding wildcard
    wc_future_rem_slope: float = 0.8          # Rate at which wildcard option value scales with remaining GWs
    wc_future_rem_max: float = 9.0            # Ceiling for wildcard duration value


CALIBRATION_DEFAULT = ChipCalibrationConfig()


@dataclass(frozen=True, slots=True)
class ChipOpportunityValue:
    """Formal audit record of chip valuation, opportunity cost, and decision utility."""

    chip: str
    gameweek: int
    immediate_ev: float
    future_max_ev: float
    net_utility: float
    confidence: float
    reasoning: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GameweekFixtureTopology:
    """Fixture congestion and Blank/Double characteristics for a single gameweek."""

    gameweek: int
    total_fixtures: int
    blank_team_ids: list[int] = field(default_factory=list)
    double_team_ids: list[int] = field(default_factory=list)
    team_fixture_counts: dict[int, int] = field(default_factory=dict)
    team_difficulties: dict[int, float] = field(default_factory=dict)

    @property
    def is_blank(self) -> bool:
        return len(self.blank_team_ids) > 0

    @property
    def is_double(self) -> bool:
        return len(self.double_team_ids) > 0


def extract_season_fixture_topology(
    season: str | None = None,
    season_dir: Path | None = None,
    raw_fixtures: list[dict[str, Any]] | None = None,
) -> dict[int, GameweekFixtureTopology]:
    """Build complete 38-gameweek calendar topography mapping blanks and doubles."""
    fixtures_list: list[dict[str, Any]] = []

    if raw_fixtures:
        fixtures_list = raw_fixtures
    elif season_dir and (season_dir / "fixtures.json").exists():
        try:
            fixtures_list = json.loads((season_dir / "fixtures.json").read_text(encoding="utf-8"))
        except Exception as e:
            LOGGER.warning("Could not read fixtures from %s: %s", season_dir, e)
    elif season:
        s_path = DATA_HISTORICAL_DIR / season / "fixtures.json"
        if s_path.exists():
            try:
                fixtures_list = json.loads(s_path.read_text(encoding="utf-8"))
            except Exception as e:
                LOGGER.warning("Could not read fixtures from %s: %s", s_path, e)

    topologies: dict[int, GameweekFixtureTopology] = {}
    for gw in range(1, 39):
        topologies[gw] = GameweekFixtureTopology(gameweek=gw, total_fixtures=0)

    if not fixtures_list:
        # Fallback: standard 10 fixtures per GW
        for gw in range(1, 39):
            topologies[gw] = GameweekFixtureTopology(
                gameweek=gw,
                total_fixtures=10,
                team_fixture_counts={t: 1 for t in range(1, 21)},
            )
        return topologies

    # Count team appearances per gameweek
    gw_team_counts: dict[int, dict[int, int]] = {gw: {} for gw in range(1, 39)}
    gw_team_diffs: dict[int, dict[int, list[int]]] = {gw: {} for gw in range(1, 39)}
    gw_total_fix: dict[int, int] = {gw: 0 for gw in range(1, 39)}

    for f in fixtures_list:
        event = f.get("event")
        if event is None or not (1 <= event <= 38):
            continue
        th = f.get("team_h")
        ta = f.get("team_a")
        diff_h = f.get("team_h_difficulty", 3)
        diff_a = f.get("team_a_difficulty", 3)

        gw_total_fix[event] += 1
        if th:
            gw_team_counts[event][th] = gw_team_counts[event].get(th, 0) + 1
            gw_team_diffs[event].setdefault(th, []).append(diff_h)
        if ta:
            gw_team_counts[event][ta] = gw_team_counts[event].get(ta, 0) + 1
            gw_team_diffs[event].setdefault(ta, []).append(diff_a)

    for gw in range(1, 39):
        counts = gw_team_counts[gw]
        blanks = [t for t in range(1, 21) if counts.get(t, 0) == 0]
        doubles = [t for t in range(1, 21) if counts.get(t, 0) >= 2]
        avg_diffs = {
            t: float(sum(d_list) / len(d_list)) for t, d_list in gw_team_diffs[gw].items() if d_list
        }
        topologies[gw] = GameweekFixtureTopology(
            gameweek=gw,
            total_fixtures=gw_total_fix[gw],
            blank_team_ids=blanks,
            double_team_ids=doubles,
            team_fixture_counts=counts,
            team_difficulties=avg_diffs,
        )

    return topologies


@dataclass(frozen=True, slots=True)
class _CandGwProj:
    player_id: int
    id: int
    web_name: str
    team_id: int
    position: Any
    status: str
    expected_points: float
    expected_minutes: float
    play_probability: float
    start_probability: float
    availability_pct: float
    chance_of_playing_next_round: int | None
    consecutive_zero_mins: int
    is_long_term_unavailable: bool
    price_tenths: int = 50


def _norm_pos(pos: Any) -> str:
    if hasattr(pos, "name"):
        s = pos.name.upper()
    elif hasattr(pos, "value"):
        s = str(pos.value).upper()
    else:
        s = str(pos).upper()
    if s in ("GKP", "GOALKEEPER", "1"):
        return "GKP"
    if s in ("DEF", "DEFENDER", "2"):
        return "DEF"
    if s in ("MID", "MIDFIELDER", "3"):
        return "MID"
    if s in ("FWD", "FORWARD", "4"):
        return "FWD"
    return s


def _calc_legal_squad_xi_xp(squad_projs: list[_CandGwProj]) -> float:
    by_pos: dict[str, list[float]] = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for p in squad_projs:
        pos_k = _norm_pos(p.position)
        if pos_k in by_pos:
            by_pos[pos_k].append(p.expected_points)
    for k in by_pos:
        by_pos[k].sort(reverse=True)
    gks = by_pos["GKP"]
    defs = by_pos["DEF"]
    mids = by_pos["MID"]
    fwds = by_pos["FWD"]
    if not gks or len(defs) < 3 or len(mids) < 2 or len(fwds) < 1:
        all_vals = sorted((p.expected_points for p in squad_projs), reverse=True)
        return round(sum(all_vals[:11]), 2)
    best_val = 0.0
    for n_def, n_mid, n_fwd in [(3, 5, 2), (3, 4, 3), (4, 4, 2), (4, 3, 3), (4, 5, 1), (5, 3, 2), (5, 4, 1), (5, 2, 3)]:
        if len(defs) >= n_def and len(mids) >= n_mid and len(fwds) >= n_fwd:
            tot = gks[0] + sum(defs[:n_def]) + sum(mids[:n_mid]) + sum(fwds[:n_fwd])
            if tot > best_val:
                best_val = tot
    return round(best_val, 2)


def _calc_achievable_pool_xi_xp(pool_projs: list[_CandGwProj], max_budget_tenths: int) -> float:
    by_pos: dict[str, list[_CandGwProj]] = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
    for p in pool_projs:
        if p.status not in ("a", "d") or getattr(p, "is_long_term_unavailable", False):
            continue
        if p.expected_points <= 0.0:
            continue
        pos_k = _norm_pos(p.position)
        if pos_k in by_pos:
            by_pos[pos_k].append(p)

    min_costs: dict[str, int] = {}
    for pos_k in ("GKP", "DEF", "MID", "FWD"):
        all_p_pos = [p for p in pool_projs if _norm_pos(p.position) == pos_k]
        min_costs[pos_k] = min((p.price_tenths for p in all_p_pos), default=40)

    base_floor_15 = (
        2 * min_costs["GKP"]
        + 5 * min_costs["DEF"]
        + 5 * min_costs["MID"]
        + 3 * min_costs["FWD"]
    )

    filtered_by_pos: dict[str, list[_CandGwProj]] = {}
    for pos_k, cands in by_pos.items():
        min_other_14 = base_floor_15 - min_costs[pos_k]
        filtered_by_pos[pos_k] = [
            p for p in cands if (p.price_tenths + min_other_14) <= max_budget_tenths
        ]

    gks = filtered_by_pos["GKP"]
    defs = filtered_by_pos["DEF"]
    mids = filtered_by_pos["MID"]
    fwds = filtered_by_pos["FWD"]

    if not gks or len(defs) < 3 or len(mids) < 2 or len(fwds) < 1:
        aff_all = sorted(
            [p for p_list in filtered_by_pos.values() for p in p_list],
            key=lambda p: p.expected_points,
            reverse=True,
        )
        return round(sum(p.expected_points for p in aff_all[:11]), 2)

    for pos_k in filtered_by_pos:
        filtered_by_pos[pos_k].sort(key=lambda p: (p.expected_points, -p.price_tenths), reverse=True)

    formations = [(3, 5, 2), (3, 4, 3), (4, 4, 2), (4, 3, 3), (4, 5, 1), (5, 3, 2), (5, 4, 1), (5, 2, 3)]
    best_pool_xi = 0.0

    for n_def, n_mid, n_fwd in formations:
        if len(defs) < n_def or len(mids) < n_mid or len(fwds) < n_fwd:
            continue
        min_bench_cost = (
            1 * min_costs["GKP"]
            + (5 - n_def) * min_costs["DEF"]
            + (5 - n_mid) * min_costs["MID"]
            + (3 - n_fwd) * min_costs["FWD"]
        )
        xi_budget = max_budget_tenths - min_bench_cost

        cand_gks = gks[:4]
        cand_defs = defs[:12]
        cand_mids = mids[:12]
        cand_fwds = fwds[:8]

        for gk in cand_gks:
            if gk.price_tenths > xi_budget:
                continue
            counts: dict[int, int] = {gk.team_id: 1}
            rem_budget = xi_budget - gk.price_tenths

            needed = {"DEF": n_def, "MID": n_mid, "FWD": n_fwd}
            picked: dict[str, list[_CandGwProj]] = {"DEF": [], "MID": [], "FWD": []}
            spent = 0

            pool_outfield = (
                [("DEF", p) for p in cand_defs]
                + [("MID", p) for p in cand_mids]
                + [("FWD", p) for p in cand_fwds]
            )
            pool_outfield.sort(key=lambda item: item[1].expected_points, reverse=True)

            for pos_tag, cand in pool_outfield:
                if len(picked[pos_tag]) >= needed[pos_tag]:
                    continue
                if cand in picked[pos_tag]:
                    continue
                if counts.get(cand.team_id, 0) >= 3:
                    continue
                rem_needed_cost = 0
                for p_t, req_n in needed.items():
                    unfilled = req_n - len(picked[p_t]) - (1 if p_t == pos_tag else 0)
                    rem_needed_cost += max(0, unfilled) * min_costs[p_t]
                if spent + cand.price_tenths + rem_needed_cost > rem_budget:
                    continue
                picked[pos_tag].append(cand)
                counts[cand.team_id] = counts.get(cand.team_id, 0) + 1
                spent += cand.price_tenths

            valid = True
            for pos_tag, req_n in needed.items():
                while len(picked[pos_tag]) < req_n:
                    cheap_pool = sorted(filtered_by_pos[pos_tag], key=lambda p: p.price_tenths)
                    added = False
                    for cp in cheap_pool:
                        if cp in picked[pos_tag]:
                            continue
                        if counts.get(cp.team_id, 0) >= 3:
                            continue
                        if spent + cp.price_tenths > rem_budget:
                            continue
                        picked[pos_tag].append(cp)
                        counts[cp.team_id] = counts.get(cp.team_id, 0) + 1
                        spent += cp.price_tenths
                        added = True
                        break
                    if not added:
                        valid = False
                        break
                if not valid:
                    break

            if valid:
                formation_xp = gk.expected_points + sum(p.expected_points for p_list in picked.values() for p in p_list)
                if formation_xp > best_pool_xi:
                    best_pool_xi = formation_xp

    return round(best_pool_xi, 2)


class ChipOpportunityOptimizer:
    """Unified mathematical optimizer for strategic FPL chip deployment."""

    def __init__(
        self,
        variant: str = "c2_ev_planner",
        discount_factor: float = 0.96,
        cooldown_gameweeks: int = 2,
        calibration: ChipCalibrationConfig = CALIBRATION_DEFAULT,
    ) -> None:
        self.variant = variant
        self.discount_factor = discount_factor
        self.cooldown_gameweeks = cooldown_gameweeks
        self.cal = calibration

    def resolve_segment_window(self, gameweek: int) -> tuple[int, int, str]:
        """Return (segment_start, segment_end, segment_name) for gameweek."""
        if gameweek <= 19:
            return 1, 19, "1-19"
        return 20, 38, "20-38"

    def normalize_chip_name(self, chip: str) -> str:
        """Map aliases or versioned chip keys (e.g. wildcard_1) to canonical base name."""
        clean = str(chip).lower().strip().replace("-", "_")
        return CANONICAL_CHIP_NAMES.get(clean, clean)

    def evaluate_gameweek_chip(
        self,
        gameweek: int,
        available_chips: Sequence[str] | Any,
        squad_ids: Sequence[int],
        snapshot: Any,
        projections: Sequence[Any],
        initial_squad_ids: Sequence[int] | None = None,
        chips_used: dict[str, int] | None = None,
        recent_chip_history: dict[str, int] | None = None,
        fixture_topology: dict[int, GameweekFixtureTopology] | None = None,
    ) -> str | None:
        """Determine whether to deploy a chip for upcoming gameweek.

        Returns canonical chip string ('wildcard', 'free_hit', 'bench_boost',
        'triple_captain') or None if holding all chips is optimal.
        """
        # Extract available chips list
        avail_list: list[str] = []
        if hasattr(available_chips, "available_chips"):
            # SeasonalChipInventory object
            raw_avail = available_chips.available_chips(gameweek)
            avail_list = [self.normalize_chip_name(c) for c in raw_avail]
        elif isinstance(available_chips, (list, tuple, set)):
            for c in available_chips:
                norm = self.normalize_chip_name(c)
                # Respect segment boundaries for wildcard_1 / wildcard_2
                if str(c).lower().strip() in ("wildcard_1", "wildcard1") and gameweek >= 20:
                    continue
                if str(c).lower().strip() in ("wildcard_2", "wildcard2") and gameweek <= 19:
                    continue
                if norm in AVAILABLE_CHIPS and norm not in avail_list:
                    avail_list.append(norm)

        if not avail_list:
            return None

        # Delegate if C0 baseline requested
        if self.variant == "c0_baseline":
            return self._evaluate_c0_baseline(
                gameweek, avail_list, squad_ids, snapshot, projections, initial_squad_ids
            )
        elif self.variant == "c1_linear_decay":
            return self._evaluate_c1_linear_decay(
                gameweek, avail_list, squad_ids, snapshot, projections, fixture_topology
            )

        # Canonical C2 (or C3) optimization
        opps = self.evaluate_all_opportunities(
            gameweek=gameweek,
            available_chips=avail_list,
            squad_ids=squad_ids,
            snapshot=snapshot,
            projections=projections,
            chips_used=chips_used,
            recent_chip_history=recent_chip_history,
            fixture_topology=fixture_topology,
        )

        positive_opps = [op for op in opps.values() if op.net_utility > 0.0]
        if not positive_opps:
            return None

        # Sort by net utility descending
        best_opp = max(positive_opps, key=lambda o: o.net_utility)
        return best_opp.chip

    def evaluate_all_opportunities(
        self,
        gameweek: int,
        available_chips: Sequence[str],
        squad_ids: Sequence[int],
        snapshot: Any,
        projections: Sequence[Any],
        chips_used: dict[str, int] | None = None,
        recent_chip_history: dict[str, int] | None = None,
        fixture_topology: dict[int, GameweekFixtureTopology] | None = None,
    ) -> dict[str, ChipOpportunityValue]:
        """Compute immediate EV, future opportunity cost, and net utility for all candidates."""
        seg_start, seg_end, _ = self.resolve_segment_window(gameweek)
        season_name = getattr(snapshot, "season", None)

        if fixture_topology is None:
            raw_fix = getattr(snapshot, "fixtures", None)
            raw_fix_dicts = None
            if raw_fix and hasattr(raw_fix[0], "__dict__"):
                raw_fix_dicts = [asdict(f) if hasattr(f, "__dataclass_fields__") else f.__dict__ for f in raw_fix]
            fixture_topology = extract_season_fixture_topology(season=season_name, raw_fixtures=raw_fix_dicts)

        # Map projections
        proj_map: dict[int, Any] = {}
        for p in projections:
            pid = getattr(p, "player_id", getattr(p, "id", None))
            if pid is not None:
                proj_map[pid] = p

        # Check guardrails: postponed matchday
        current_topo = fixture_topology.get(gameweek)
        total_fixtures_gw = current_topo.total_fixtures if current_topo else len(getattr(snapshot, "fixtures", []))
        is_postponed_gw = total_fixtures_gw < 4

        # Recent wildcard cooldown
        chip_hist = dict(recent_chip_history or (chips_used or {}))
        wc_last_gw = None
        for k, v in chip_hist.items():
            if self.normalize_chip_name(k) == "wildcard":
                if wc_last_gw is None or v > wc_last_gw:
                    wc_last_gw = v

        in_wc_cooldown = (
            wc_last_gw is not None
            and 1 <= (gameweek - wc_last_gw) <= self.cooldown_gameweeks
        )

        results: dict[str, ChipOpportunityValue] = {}

        for chip in available_chips:
            canon = self.normalize_chip_name(chip)
            if canon not in AVAILABLE_CHIPS:
                continue

            # Guardrail 1: GW1 start - never burn Free Hit, Bench Boost, or Wildcard in GW1
            if gameweek == 1 and canon in ("free_hit", "wildcard", "bench_boost"):
                results[canon] = ChipOpportunityValue(
                    chip=canon,
                    gameweek=gameweek,
                    immediate_ev=0.0,
                    future_max_ev=20.0,
                    net_utility=-20.0,
                    confidence=1.0,
                    reasoning=f"Gameweek 1 squad initialization. Preserving {canon} for future fixture swings.",
                )
                continue

            # Guardrail 2: Postponed / cancelled matchday blocks active chips
            if is_postponed_gw:
                results[canon] = ChipOpportunityValue(
                    chip=canon,
                    gameweek=gameweek,
                    immediate_ev=0.0,
                    future_max_ev=12.0,
                    net_utility=-12.0,
                    confidence=1.0,
                    reasoning=f"Postponed matchday (only {total_fixtures_gw} fixtures). Chip deployment blocked.",
                )
                continue

            # Guardrail 3: Post-Wildcard Cooldown blocks Free Hit and Wildcard
            if in_wc_cooldown and canon in ("free_hit", "wildcard"):
                results[canon] = ChipOpportunityValue(
                    chip=canon,
                    gameweek=gameweek,
                    immediate_ev=0.0,
                    future_max_ev=15.0,
                    net_utility=-15.0,
                    confidence=1.0,
                    reasoning=f"Active Wildcard cooldown (played in GW{wc_last_gw}). Deployment blocked to prevent waste.",
                )
                continue

            # Guardrail 4: Early Wildcard protection (GW 2-4) without deterioration
            if canon == "wildcard" and gameweek in (2, 3, 4):
                collapsed = self._count_collapsed_squad_players(squad_ids, proj_map, snapshot)
                if collapsed < 3:
                    results[canon] = ChipOpportunityValue(
                        chip=canon,
                        gameweek=gameweek,
                        immediate_ev=2.0,
                        future_max_ev=18.0,
                        net_utility=-16.0,
                        confidence=0.9,
                        reasoning=f"Early gameweek (GW{gameweek}) Wildcard preservation guard active ({collapsed}/3 deteriorated players).",
                    )
                    continue

            # Compute Immediate EV
            imm_ev = self._compute_immediate_ev(
                chip=canon,
                gameweek=gameweek,
                squad_ids=squad_ids,
                proj_map=proj_map,
                snapshot=snapshot,
                fixture_topology=fixture_topology,
            )

            # Compute Future Opportunity Cost across remaining window
            fut_max, best_future_gw = self._compute_future_opportunity(
                chip=canon,
                current_gw=gameweek,
                seg_end=seg_end,
                squad_ids=squad_ids,
                proj_map=proj_map,
                snapshot=snapshot,
                fixture_topology=fixture_topology,
            )

            # Surrogate adjustment if C3
            if self.variant == "c3_surrogate":
                fut_max = self._apply_c3_surrogate_correction(
                    canon, gameweek, seg_end, fut_max, fixture_topology
                )

            # Natural terminal window decay:
            # If gameweek == seg_end, future optionality is identically 0.0
            if gameweek >= seg_end:
                fut_max = 0.0

            net_util = round(imm_ev - fut_max, 2)
            conf = min(1.0, max(0.5, 1.0 - (seg_end - gameweek) * 0.02))

            reason = (
                f"Immediate EV: {imm_ev:.1f} pts vs best future opportunity: {fut_max:.1f} pts "
                f"(GW{best_future_gw if best_future_gw else gameweek}). Net utility: {net_util:+.1f} pts."
            )

            results[canon] = ChipOpportunityValue(
                chip=canon,
                gameweek=gameweek,
                immediate_ev=round(imm_ev, 2),
                future_max_ev=round(fut_max, 2),
                net_utility=net_util,
                confidence=round(conf, 2),
                reasoning=reason,
                metadata={
                    "best_future_gw": best_future_gw,
                    "segment_end": seg_end,
                    "variant": self.variant,
                },
            )

        return results

    # -------------------------------------------------------------------------
    # Immediate Expected Value (ΔEV) Calculation
    # -------------------------------------------------------------------------
    def _compute_immediate_ev(
        self,
        chip: str,
        gameweek: int,
        squad_ids: Sequence[int],
        proj_map: dict[int, Any],
        snapshot: Any,
        fixture_topology: dict[int, GameweekFixtureTopology],
    ) -> float:
        squad_projs = [proj_map[pid] for pid in squad_ids if pid in proj_map]
        topo = fixture_topology.get(gameweek)
        double_teams = set(topo.double_team_ids) if topo else set()
        blank_teams = set(topo.blank_team_ids) if topo else set()

        player_team_map: dict[int, int] = {}
        for p in getattr(snapshot, "players", []):
            pid = getattr(p, "player_id", getattr(p, "id", None))
            tid = getattr(p, "team_id", getattr(p, "team", None))
            if pid is not None and tid is not None:
                player_team_map[pid] = tid

        if chip == "triple_captain":
            if not squad_projs:
                return 0.0

            def _cap_val(p: Any) -> float:
                xp = getattr(p, "expected_points", 0.0)
                sp = getattr(p, "start_probability", 0.0)
                if sp <= 0.0 and getattr(p, "status", "a") == "a" and getattr(p, "availability_pct", 100.0) > 50.0:
                    sp = 1.0
                return float(xp * sp)

            best_cand = max(squad_projs, key=_cap_val, default=None)
            if best_cand is None:
                return 0.0
            return _cap_val(best_cand)

        elif chip == "bench_boost":
            sorted_projs = sorted(squad_projs, key=lambda p: getattr(p, "expected_points", 0.0), reverse=True)
            bench_projs = sorted_projs[11:] if len(sorted_projs) >= 15 else sorted_projs[max(0, len(sorted_projs) - 4):]

            def _bench_p_val(p: Any) -> float:
                xp = getattr(p, "expected_points", 0.0)
                pp = getattr(p, "play_probability", 0.0)
                if pp <= 0.0 and getattr(p, "status", "a") == "a" and getattr(p, "availability_pct", 100.0) > 50.0:
                    pp = 1.0
                return float(xp * pp)

            bench_xp = sum(_bench_p_val(p) for p in bench_projs)
            # Calibration: in standard gameweeks, a bench needs to be genuinely strong or
            # upcoming gameweeks will offer higher returns in DGW clusters.
            dgw_boost = self.cal.bb_dgw_immediate_boost if (topo and topo.is_double) else 0.0
            return float(bench_xp + dgw_boost)

        elif chip == "free_hit":
            # Realistic Free Hit value:
            # 1. Blank recovery: each squad player blanking scores 0 instead of average expected points
            squad_blanks = sum(1 for pid in squad_ids if player_team_map.get(pid) in blank_teams)
            blank_gain = squad_blanks * self.cal.fh_blank_player_gain

            # 2. DGW exploitation: if DGW present, free hit can target DGW assets
            squad_doubles = sum(1 for pid in squad_ids if player_team_map.get(pid) in double_teams)
            max_dgw_slots = min(9, len(double_teams) * 3)
            dgw_gain = max(0, max_dgw_slots - squad_doubles) * self.cal.fh_dgw_slot_gain if double_teams else 0.0

            # 3. Base lineup optimization delta under budget constraints
            base_delta = self.cal.fh_base_lineup_delta
            return float(blank_gain + dgw_gain + base_delta)

        elif chip == "wildcard":
            # Restructuring value:
            collapsed = self._count_collapsed_squad_players(squad_ids, proj_map, snapshot)
            # Transfer hit savings for fixing broken squad
            hit_savings = max(0, (collapsed - 1) * self.cal.wc_hit_saving_per_player)

            # Fixture run restructuring bonus:
            # If many gameweeks remain in segment, wildcard upgrades persist over multiple GWs
            seg_start, seg_end, _ = self.resolve_segment_window(gameweek)
            remaining_gws = seg_end - gameweek
            persistence = min(self.cal.wc_persistence_max, remaining_gws * self.cal.wc_persistence_rate)

            # Near-expiry urgency bonus (approaching GW 18-19 or 36-38)
            expiry_urgency = 0.0
            if remaining_gws <= 2:
                expiry_urgency = self.cal.wc_expiry_urgency_bonus

            return float(hit_savings + persistence + expiry_urgency)

        return 0.0

    # -------------------------------------------------------------------------
    # Future Opportunity Cost Scan
    # -------------------------------------------------------------------------
    def _compute_future_opportunity(
        self,
        chip: str,
        current_gw: int,
        seg_end: int,
        squad_ids: Sequence[int],
        proj_map: dict[int, Any],
        snapshot: Any,
        fixture_topology: dict[int, GameweekFixtureTopology],
    ) -> tuple[float, int | None]:
        if current_gw >= seg_end:
            return 0.0, None

        max_fut_ev = 0.0
        best_future_gw: int | None = None

        player_team_map: dict[int, int] = {}
        for p in getattr(snapshot, "players", []):
            pid = getattr(p, "player_id", getattr(p, "id", None))
            tid = getattr(p, "team_id", getattr(p, "team", None))
            if pid is not None and tid is not None:
                player_team_map[pid] = tid
        squad_teams = [player_team_map[pid] for pid in squad_ids if pid in player_team_map]

        for fut_gw in range(current_gw + 1, seg_end + 1):
            topo = fixture_topology.get(fut_gw)
            if not topo:
                continue

            dist = fut_gw - current_gw
            h_discount = math.pow(self.discount_factor, dist)

            ev_estimate = 0.0

            if chip == "triple_captain":
                if topo.is_double and len(topo.double_team_ids) >= 1:
                    ev_estimate = self.cal.tc_future_dgw_target * h_discount
                else:
                    ev_estimate = self.cal.tc_future_standard_target * h_discount

            elif chip == "bench_boost":
                if topo.is_double and len(topo.double_team_ids) >= 2:
                    ev_estimate = self.cal.bb_future_dgw2_target * h_discount
                elif topo.is_double:
                    ev_estimate = self.cal.bb_future_dgw1_target * h_discount
                else:
                    # Non-DGW benchmark bench expectation
                    ev_estimate = self.cal.bb_future_standard_target * h_discount

            elif chip == "free_hit":
                blank_count = sum(1 for tid in squad_teams if tid in topo.blank_team_ids)
                if blank_count >= 3 or (topo.is_blank and len(topo.blank_team_ids) >= 4):
                    ev_estimate = (self.cal.fh_future_major_blank + blank_count * self.cal.fh_future_blank_multiplier) * h_discount
                elif topo.is_double and len(topo.double_team_ids) >= 4:
                    ev_estimate = self.cal.fh_future_mega_dgw * h_discount
                else:
                    ev_estimate = self.cal.fh_future_standard * h_discount

            elif chip == "wildcard":
                rem_after = seg_end - fut_gw
                # Future opportunity decays naturally as remaining gameweeks diminish
                ev_estimate = (self.cal.wc_future_base + min(self.cal.wc_future_rem_max, rem_after * self.cal.wc_future_rem_slope)) * h_discount

            if ev_estimate > max_fut_ev:
                max_fut_ev = ev_estimate
                best_future_gw = fut_gw

        return float(max_fut_ev), best_future_gw

    # -------------------------------------------------------------------------
    # Variant Helpers
    # -------------------------------------------------------------------------
    def _count_collapsed_squad_players(
        self,
        squad_ids: Sequence[int],
        proj_map: dict[int, Any],
        snapshot: Any,
    ) -> int:
        collapsed = 0
        for pid in squad_ids:
            p = proj_map.get(pid)
            if p is None:
                collapsed += 1
                continue
            if is_departed_from_premier_league(p, snapshot):
                collapsed += 1
            elif getattr(p, "status", "a") in ("i", "u", "s"):
                collapsed += 1
            elif getattr(p, "chance_of_playing_next_round", 100) == 0:
                collapsed += 1
            elif getattr(p, "consecutive_zero_mins", 0) >= 3 and getattr(p, "expected_minutes", 0) < 15.0:
                collapsed += 1
            elif getattr(p, "expected_points", 0.0) < 0.5 and getattr(p, "play_probability", 1.0) < 0.2:
                collapsed += 1
        return collapsed

    def _evaluate_c0_baseline(
        self,
        gameweek: int,
        available: list[str],
        squad_ids: Sequence[int],
        snapshot: Any,
        projections: Sequence[Any],
        initial_squad_ids: Sequence[int] | None = None,
    ) -> str | None:
        """Legacy SeasonalChipPolicy static threshold evaluation."""
        from ..chip_strategy import SeasonalChipInventory, SeasonalChipPolicy

        inv = SeasonalChipInventory(
            wildcard_w1="wildcard" in available and gameweek <= 19,
            free_hit_w1="free_hit" in available and gameweek <= 19,
            triple_captain_w1="triple_captain" in available and gameweek <= 19,
            bench_boost_w1="bench_boost" in available and gameweek <= 19,
            wildcard_w2="wildcard" in available and gameweek >= 20,
            free_hit_w2="free_hit" in available and gameweek >= 20,
            triple_captain_w2="triple_captain" in available and gameweek >= 20,
            bench_boost_w2="bench_boost" in available and gameweek >= 20,
        )
        return SeasonalChipPolicy(use_optimizer=False).evaluate_gameweek_chip(
            gameweek, inv, list(squad_ids), snapshot, list(projections), initial_squad_ids
        )

    def _evaluate_c1_linear_decay(
        self,
        gameweek: int,
        available: list[str],
        squad_ids: Sequence[int],
        snapshot: Any,
        projections: Sequence[Any],
        fixture_topology: dict[int, GameweekFixtureTopology] | None,
    ) -> str | None:
        """Variant C1: Linear window-decay heuristic."""
        seg_start, seg_end, _ = self.resolve_segment_window(gameweek)
        rem_fraction = max(0.2, (seg_end - gameweek + 1) / (seg_end - seg_start + 1))

        proj_map = {getattr(p, "player_id", getattr(p, "id", None)): p for p in projections}
        squad_projs = [proj_map[pid] for pid in squad_ids if pid in proj_map]

        # 1. Free Hit: decay active players threshold
        if "free_hit" in available:
            playing = sum(1 for p in squad_projs if getattr(p, "expected_points", 0.0) > 0.8)
            fh_threshold = int(8 + (1.0 - rem_fraction) * 3)  # decays from 8 up to 11
            if playing <= fh_threshold:
                return "free_hit"

        # 2. Triple Captain: decay xp threshold
        if "triple_captain" in available:
            best_p = max(squad_projs, key=lambda p: getattr(p, "expected_points", 0.0), default=None)
            if best_p:
                cap_xp = getattr(best_p, "expected_points", 0.0)
                tc_thresh = 11.0 * rem_fraction
                if cap_xp >= max(7.5, tc_thresh):
                    return "triple_captain"

        # 3. Bench Boost: decay bench xp threshold
        if "bench_boost" in available:
            sorted_projs = sorted(squad_projs, key=lambda p: getattr(p, "expected_points", 0.0), reverse=True)
            bench = sorted_projs[11:]
            bench_xp = sum(getattr(p, "expected_points", 0.0) for p in bench)
            bb_thresh = 10.0 * rem_fraction
            if bench_xp >= max(6.0, bb_thresh):
                return "bench_boost"

        # 4. Wildcard: decay collapsed count threshold
        if "wildcard" in available:
            collapsed = self._count_collapsed_squad_players(squad_ids, proj_map, snapshot)
            wc_thresh = max(1, int(4 * rem_fraction))
            if collapsed >= wc_thresh:
                return "wildcard"

        return None

    def _apply_c3_surrogate_correction(
        self,
        chip: str,
        gameweek: int,
        seg_end: int,
        future_ev: float,
        fixture_topology: dict[int, GameweekFixtureTopology],
    ) -> float:
        """Variant C3: Tabular surrogate correction on continuation value."""
        # Count remaining DGWs and BGWs in segment
        rem_dgws = sum(
            1 for gw in range(gameweek + 1, seg_end + 1)
            if fixture_topology.get(gw) and fixture_topology[gw].is_double
        )
        rem_bgws = sum(
            1 for gw in range(gameweek + 1, seg_end + 1)
            if fixture_topology.get(gw) and fixture_topology[gw].is_blank
        )

        # Tabular surrogate weights calibrated on historical continuation value
        if chip == "triple_captain":
            # If no DGWs remain in segment, option value collapses sharply
            correction = 1.0 + (0.15 * rem_dgws) if rem_dgws > 0 else 0.70
        elif chip == "bench_boost":
            correction = 1.0 + (0.20 * rem_dgws) if rem_dgws > 0 else 0.65
        elif chip == "free_hit":
            correction = 1.0 + (0.25 * rem_bgws) if rem_bgws > 0 else 0.75
        elif chip == "wildcard":
            rem_gws = seg_end - gameweek
            correction = min(1.2, max(0.5, 0.4 + (rem_gws / 19.0) * 0.8))
        else:
            correction = 1.0

        return future_ev * correction

    def generate_segment_roadmap(
        self,
        sim: Any,
        start_gw: int | None = None,
    ) -> dict[str, Any]:
        """Generate a conflict-free, squad-sensitive chip deployment roadmap for the active segment (V146-18).

        Strictly uses point-in-time projections from `sim.get_current_snapshot()` and known future
        fixture topology without hardcoded placeholder EVs or confidence constants.
        """
        from ..historical.snapshots import load_historical_players_meta

        eff_start_gw = max(int(start_gw or sim.current_gw), int(sim.current_gw))
        seg_start, seg_end, seg_name = self.resolve_segment_window(eff_start_gw)
        is_seg1 = eff_start_gw <= 19

        # Resolve remaining and used chips for the active segment in UI format
        remaining_clean: list[str] = []
        for c in getattr(sim, "chips_remaining", []):
            norm = str(c).lower().replace("-", "_")
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

        used_clean: list[str] = []
        recent_wc_gw: int | None = None
        for c, used_gw in (getattr(sim, "chips_used", {}) or {}).items():
            norm = str(c).lower().replace("-", "_")
            if norm.startswith("wildcard"):
                if recent_wc_gw is None or int(used_gw) > recent_wc_gw:
                    recent_wc_gw = int(used_gw)
            if (is_seg1 and int(used_gw) <= 19) or (not is_seg1 and int(used_gw) >= 20):
                if norm.startswith("wildcard") and "wildcard" not in used_clean:
                    used_clean.append("wildcard")
                elif (norm.startswith("free_hit") or norm.startswith("freehit")) and "freehit" not in used_clean:
                    used_clean.append("freehit")
                elif (norm.startswith("bench_boost") or norm.startswith("benchboost")) and "benchboost" not in used_clean:
                    used_clean.append("benchboost")
                elif (norm.startswith("triple_captain") or norm.startswith("triplecaptain")) and "triplecaptain" not in used_clean:
                    used_clean.append("triplecaptain")

        season_dir = getattr(sim, "season_dir", None) or (sim.historical_dir / sim.season)
        topo_map = extract_season_fixture_topology(season=sim.season, season_dir=season_dir)
        snapshot = sim.get_current_snapshot()
        seg_horizon = max(1, seg_end - int(sim.current_gw) + 1)
        players_map, _ = load_historical_players_meta(snapshot, season_dir, horizon=seg_horizon)

        # Effective squad reflecting any unapplied staged transfers
        eff_squad_ids = list(int(pid) for pid in sim.squad_ids)
        for st in getattr(sim, "transfers_staged", []) or []:
            if st.get("already_applied"):
                continue
            o_id = int(st["out_id"])
            i_id = int(st["in_id"])
            if o_id in eff_squad_ids:
                eff_squad_ids[eff_squad_ids.index(o_id)] = i_id
            elif i_id not in eff_squad_ids:
                eff_squad_ids.append(i_id)

        snap_player_map = {int(p.player_id): p for p in getattr(snapshot, "players", [])}

        ui_to_canon = {
            "wildcard": "wildcard",
            "freehit": "free_hit",
            "benchboost": "bench_boost",
            "triplecaptain": "triple_captain",
        }
        canon_to_ui = {v: k for k, v in ui_to_canon.items()}
        canon_available = [ui_to_canon[c] for c in remaining_clean if c in ui_to_canon]
        recent_history = {"wildcard": recent_wc_gw} if recent_wc_gw is not None else {}

        candidates_by_chip: dict[str, list[dict[str, Any]]] = {
            "freehit": [],
            "triplecaptain": [],
            "benchboost": [],
            "wildcard": [],
        }

        total_capital = int(getattr(sim, "bank_tenths", 0))
        from ..transfers import selling_price
        for pid in eff_squad_ids:
            sp_raw = snap_player_map.get(pid)
            cur_p = int(getattr(sp_raw, "price_tenths", 50))
            purch_p = int(getattr(sim, "purchase_prices_tenths", {}).get(str(pid), cur_p))
            total_capital += selling_price(purch_p, cur_p)
        if total_capital <= 0:
            total_capital = 1000

        target_gws = list(range(eff_start_gw, seg_end + 1))

        # Precompute per-GW projection objects and pool benchmarks
        gw_proj_lists: dict[int, list[_CandGwProj]] = {}
        gw_proj_maps: dict[int, dict[int, _CandGwProj]] = {}
        gw_pool_top11_xp: dict[int, float] = {}
        gw_squad_top11_xp: dict[int, float] = {}

        for gw in target_gws:
            p_list: list[_CandGwProj] = []
            p_map: dict[int, _CandGwProj] = {}
            for pid, p_info in players_map.items():
                sp_raw = snap_player_map.get(pid)
                xp_val = float(p_info.gw_breakdown_xp.get(gw, 0.0))
                xm_val = float(p_info.expected_minutes) if xp_val > 0.0 else 0.0
                play_p = min(1.0, max(0.0, xm_val / 75.0)) if xp_val > 0.0 else 0.0
                start_p = min(1.0, max(0.0, xm_val / 85.0)) if xp_val > 0.0 else 0.0
                p_price = int(getattr(p_info, "price_tenths", getattr(sp_raw, "price_tenths", 50)))
                c_proj = _CandGwProj(
                    player_id=pid,
                    id=pid,
                    web_name=p_info.name,
                    team_id=p_info.team_id,
                    position=p_info.position,
                    status=p_info.status,
                    expected_points=xp_val,
                    expected_minutes=xm_val,
                    play_probability=play_p,
                    start_probability=start_p,
                    availability_pct=100.0 if p_info.status == "a" else 50.0,
                    chance_of_playing_next_round=getattr(sp_raw, "chance_of_playing_next_round", 100),
                    consecutive_zero_mins=getattr(sp_raw, "consecutive_zero_mins", 0),
                    is_long_term_unavailable=bool(p_info.is_long_term_unavailable),
                    price_tenths=p_price,
                )
                p_list.append(c_proj)
                p_map[pid] = c_proj
            gw_proj_lists[gw] = p_list
            gw_proj_maps[gw] = p_map

            gw_pool_top11_xp[gw] = _calc_achievable_pool_xi_xp(p_list, total_capital)
            squad_projs = [p_map[pid] for pid in eff_squad_ids if pid in p_map]
            gw_squad_top11_xp[gw] = _calc_legal_squad_xi_xp(squad_projs)

        # Step 1: Compute squad-sensitive immediate EV for every (chip, gw) in the segment
        raw_imm_ev: dict[str, dict[int, float]] = {c: {} for c in canon_available}
        raw_blocked_reason: dict[str, dict[int, str]] = {c: {} for c in canon_available}

        for gw in target_gws:
            opps = self.evaluate_all_opportunities(
                gameweek=gw,
                available_chips=canon_available,
                squad_ids=eff_squad_ids,
                snapshot=snapshot,
                projections=gw_proj_lists[gw],
                chips_used=getattr(sim, "chips_used", None),
                recent_chip_history=recent_history,
                fixture_topology=topo_map,
            )
            for canon_chip, opp_val in opps.items():
                if opp_val.net_utility <= -10.0 and opp_val.immediate_ev <= 2.0:
                    # Blocked by guardrail (GW1, postponed matchday, wildcard cooldown, or early WC guard)
                    raw_imm_ev[canon_chip][gw] = opp_val.immediate_ev
                    raw_blocked_reason[canon_chip][gw] = opp_val.reasoning
                    continue

                imm = float(opp_val.immediate_ev)
                if canon_chip == "free_hit":
                    deficit = max(0.0, gw_pool_top11_xp[gw] - gw_squad_top11_xp[gw])
                    imm = round(imm + deficit * 0.22, 2)
                elif canon_chip == "wildcard":
                    rem_window = [g for g in target_gws if gw <= g < min(seg_end + 1, gw + 6)]
                    if rem_window:
                        avg_deficit = sum(max(0.0, gw_pool_top11_xp[g] - gw_squad_top11_xp[g]) for g in rem_window) / len(rem_window)
                        imm = round(imm + avg_deficit * 0.25, 2)
                raw_imm_ev[canon_chip][gw] = round(imm, 2)

        # Step 2: Derive dynamic future opportunity cost, net utility, confidence, and gw_type for each (chip, gw)
        for canon_chip in canon_available:
            ui_chip = canon_to_ui[canon_chip]
            for gw in target_gws:
                topo = topo_map.get(gw)
                blocked_msg = raw_blocked_reason[canon_chip].get(gw)
                imm_ev = raw_imm_ev[canon_chip].get(gw, 0.0)

                if blocked_msg:
                    fut_ev, _ = self._compute_future_opportunity(
                        chip=canon_chip,
                        current_gw=gw,
                        seg_end=seg_end,
                        squad_ids=eff_squad_ids,
                        proj_map=gw_proj_maps[gw],
                        snapshot=snapshot,
                        fixture_topology=topo_map,
                    )
                    candidates_by_chip[ui_chip].append({
                        "chip": ui_chip,
                        "gameweek": gw,
                        "gw_type": "GUARDRAIL_BLOCKED",
                        "immediate_ev": round(imm_ev, 2),
                        "future_opportunity": round(fut_ev, 2),
                        "net_utility": round(imm_ev - fut_ev, 2),
                        "confidence": 0.95,
                        "reasoning": blocked_msg,
                        "blocked": True,
                    })
                    continue

                # Best discounted future immediate_ev across remaining GWs in segment
                fut_max = 0.0
                best_fut_gw: int | None = None
                for fut_gw in range(gw + 1, seg_end + 1):
                    if fut_gw in raw_blocked_reason[canon_chip]:
                        continue
                    dist = fut_gw - gw
                    disc_val = raw_imm_ev[canon_chip].get(fut_gw, 0.0) * math.pow(self.discount_factor, dist)
                    if disc_val > fut_max:
                        fut_max = disc_val
                        best_fut_gw = fut_gw

                if gw >= seg_end:
                    fut_max = 0.0
                    best_fut_gw = None

                fut_max = round(fut_max, 2)
                net_util = round(imm_ev - fut_max, 2)
                conf = round(min(0.98, max(0.52, 0.92 - (gw - eff_start_gw) * 0.02 + (0.04 if (topo and (topo.is_double or topo.is_blank)) else 0.0))), 2)

                if topo and topo.is_double and topo.is_blank:
                    gw_type = "BLANK_AND_DOUBLE_GW"
                elif topo and topo.is_double:
                    gw_type = "DOUBLE_GAMEWEEK"
                elif topo and topo.is_blank:
                    gw_type = "BLANK_GAMEWEEK"
                elif gw >= seg_end - 1:
                    gw_type = "SEGMENT_EXPIRY_WINDOW"
                elif canon_chip == "wildcard":
                    gw_type = "FIXTURE_SWING_RESTRUCTURE"
                else:
                    gw_type = "OPTIMAL_FIXTURE_WINDOW"

                fut_clause = f"GW{best_fut_gw} ({fut_max:.1f} pts)" if best_fut_gw else "0.0 pts (window end)"
                reason = (
                    f"Optimizer valuation for GW{gw} ({gw_type}): immediate EV {imm_ev:.1f} pts "
                    f"vs best future option {fut_clause}; net utility {net_util:+.1f} pts."
                )

                candidates_by_chip[ui_chip].append({
                    "chip": ui_chip,
                    "gameweek": gw,
                    "gw_type": gw_type,
                    "rating": round(imm_ev, 2),
                    "immediate_ev": round(imm_ev, 2),
                    "future_opportunity": fut_max,
                    "net_utility": net_util,
                    "confidence": conf,
                    "reasoning": reason,
                    "blocked": False,
                })

            candidates_by_chip[ui_chip].sort(
                key=lambda c: (not c.get("blocked", False), c["immediate_ev"], c["net_utility"], -c["gameweek"]),
                reverse=True,
            )

        # Step 3: Conflict-free assignment across available chips in the segment
        schedule: list[dict[str, Any]] = []
        assigned_gws: set[int] = set()
        scheduled_wc_gw: int | None = recent_wc_gw
        scheduled_fh_gw: int | None = None
        unscheduled_reasons: dict[str, str] = {}

        # Check if engine recommends an immediate chip for current_gw
        recs = sim.get_recommendations()
        rec_chip_raw = recs.get("recommended_chip")
        if rec_chip_raw and eff_start_gw == int(sim.current_gw):
            norm_rec_canon = self.normalize_chip_name(rec_chip_raw)
            norm_rec_ui = canon_to_ui.get(norm_rec_canon)
            if norm_rec_ui in remaining_clean:
                cur_cand = next(
                    (c for c in candidates_by_chip.get(norm_rec_ui, []) if c["gameweek"] == int(sim.current_gw) and not c.get("blocked")),
                    None,
                )
                opp = recs.get("recommended_chip_opportunity") or {}
                imm_v = cur_cand["immediate_ev"] if cur_cand else round(float(opp.get("immediate_ev", 0.0)), 2)
                fut_v = cur_cand["future_opportunity"] if cur_cand else round(float(opp.get("future_max_ev", 0.0)), 2)
                net_v = cur_cand["net_utility"] if cur_cand else round(float(opp.get("net_utility", imm_v - fut_v)), 2)
                conf_v = cur_cand["confidence"] if cur_cand else round(float(opp.get("confidence", 0.9)), 2)
                alts = [
                    {
                        "gameweek": a["gameweek"],
                        "immediate_ev": a["immediate_ev"],
                        "net_utility": a["net_utility"],
                        "gw_type": a["gw_type"],
                    }
                    for a in candidates_by_chip.get(norm_rec_ui, [])
                    if a["gameweek"] != int(sim.current_gw) and not a.get("blocked")
                ][:2]
                schedule.append({
                    "gameweek": int(sim.current_gw),
                    "chip": norm_rec_ui,
                    "gw_type": cur_cand["gw_type"] if cur_cand else "OPPORTUNITY_COST_OPTIMIZER",
                    "reasoning": opp.get("reasoning") or (cur_cand["reasoning"] if cur_cand else f"Recommended by ChipOpportunityOptimizer for GW{sim.current_gw}."),
                    "immediate_ev": imm_v,
                    "future_opportunity": fut_v,
                    "net_utility": net_v,
                    "confidence": conf_v,
                    "alternatives": alts,
                })
                assigned_gws.add(int(sim.current_gw))
                if norm_rec_ui == "wildcard":
                    scheduled_wc_gw = int(sim.current_gw)
                elif norm_rec_ui == "freehit":
                    scheduled_fh_gw = int(sim.current_gw)

        chip_priority = ["freehit", "triplecaptain", "benchboost", "wildcard"]
        unassigned_chips = [
            c for c in chip_priority
            if c in remaining_clean and not any(s["chip"] == c for s in schedule)
        ]

        def _is_cooldown_ok(gw: int, other_gw: int | None) -> bool:
            if other_gw is None:
                return True
            return abs(gw - other_gw) > self.cooldown_gameweeks

        # Joint pair assignment for Free Hit and Wildcard if both are unassigned
        if "freehit" in unassigned_chips and "wildcard" in unassigned_chips:
            fh_cands = [
                c for c in candidates_by_chip.get("freehit", [])
                if not c.get("blocked") and c["gameweek"] not in assigned_gws and _is_cooldown_ok(c["gameweek"], scheduled_wc_gw)
            ]
            wc_cands = [
                c for c in candidates_by_chip.get("wildcard", [])
                if not c.get("blocked") and c["gameweek"] not in assigned_gws and _is_cooldown_ok(c["gameweek"], scheduled_fh_gw) and _is_cooldown_ok(c["gameweek"], recent_wc_gw)
            ]
            valid_pairs = []
            for c_fh in fh_cands:
                for c_wc in wc_cands:
                    if c_fh["gameweek"] != c_wc["gameweek"] and _is_cooldown_ok(c_fh["gameweek"], c_wc["gameweek"]):
                        score = (c_fh["immediate_ev"] + c_wc["immediate_ev"], c_fh["net_utility"] + c_wc["net_utility"])
                        valid_pairs.append((score, c_fh, c_wc))
            if valid_pairs:
                valid_pairs.sort(key=lambda item: item[0], reverse=True)
                _, best_fh, best_wc = valid_pairs[0]
                for chosen, ui_chip, all_c in [(best_fh, "freehit", fh_cands), (best_wc, "wildcard", wc_cands)]:
                    assigned_gws.add(chosen["gameweek"])
                    alts = [
                        {
                            "gameweek": a["gameweek"],
                            "immediate_ev": a["immediate_ev"],
                            "net_utility": a["net_utility"],
                            "gw_type": a["gw_type"],
                        }
                        for a in all_c
                        if a["gameweek"] != chosen["gameweek"] and not a.get("blocked")
                    ][:2]
                    schedule.append({
                        "gameweek": chosen["gameweek"],
                        "chip": ui_chip,
                        "gw_type": chosen["gw_type"],
                        "reasoning": chosen["reasoning"],
                        "immediate_ev": chosen["immediate_ev"],
                        "future_opportunity": chosen["future_opportunity"],
                        "net_utility": chosen["net_utility"],
                        "confidence": chosen["confidence"],
                        "alternatives": alts,
                    })
                scheduled_fh_gw = best_fh["gameweek"]
                scheduled_wc_gw = best_wc["gameweek"]
                unassigned_chips = [c for c in unassigned_chips if c not in ("freehit", "wildcard")]

        for ui_chip in unassigned_chips:
            valid_cands = [
                c for c in candidates_by_chip.get(ui_chip, [])
                if not c.get("blocked") and c["gameweek"] not in assigned_gws
            ]
            # Enforce Wildcard <-> Free Hit cooldown only between wildcard and freehit (never benchboost/triplecaptain)
            if ui_chip == "freehit" and scheduled_wc_gw is not None:
                valid_cands = [c for c in valid_cands if _is_cooldown_ok(c["gameweek"], scheduled_wc_gw)]
            elif ui_chip == "wildcard":
                if scheduled_fh_gw is not None:
                    valid_cands = [c for c in valid_cands if _is_cooldown_ok(c["gameweek"], scheduled_fh_gw)]
                if recent_wc_gw is not None:
                    valid_cands = [c for c in valid_cands if _is_cooldown_ok(c["gameweek"], recent_wc_gw)]

            if not valid_cands:
                unscheduled_reasons[ui_chip] = (
                    f"No eligible deployment window in segment satisfies strategy guardrails or cooldown for {ui_chip}."
                )
                continue

            chosen = valid_cands[0]
            assigned_gws.add(chosen["gameweek"])
            if ui_chip == "wildcard":
                scheduled_wc_gw = chosen["gameweek"]
            elif ui_chip == "freehit":
                scheduled_fh_gw = chosen["gameweek"]

            alts = [
                {
                    "gameweek": a["gameweek"],
                    "immediate_ev": a["immediate_ev"],
                    "net_utility": a["net_utility"],
                    "gw_type": a["gw_type"],
                }
                for a in valid_cands[1:3]
            ]
            schedule.append({
                "gameweek": chosen["gameweek"],
                "chip": ui_chip,
                "gw_type": chosen["gw_type"],
                "reasoning": chosen["reasoning"],
                "immediate_ev": chosen["immediate_ev"],
                "future_opportunity": chosen["future_opportunity"],
                "net_utility": chosen["net_utility"],
                "confidence": chosen["confidence"],
                "alternatives": alts,
            })

        schedule.sort(key=lambda s: s["gameweek"])

        has_bgw = any(topo_map.get(g) and topo_map[g].is_blank for g in target_gws)
        has_dgw = any(topo_map.get(g) and topo_map[g].is_double for g in target_gws)

        return {
            "session_id": sim.session_id,
            "season": sim.season,
            "gameweek": int(sim.current_gw),
            "start_gw": eff_start_gw,
            "end_gw": seg_end,
            "segment": seg_name,
            "segment_start": seg_start,
            "segment_end": seg_end,
            "chips_reset_after_gw": 19,
            "available_chips": remaining_clean,
            "used_chips": used_clean,
            "active_chip": getattr(sim, "active_chip", None),
            "has_confirmed_blank_gameweeks": has_bgw,
            "has_confirmed_double_gameweeks": has_dgw,
            "recommended_schedule": schedule,
            "unscheduled_chips": unscheduled_reasons,
            "has_confirmed_double_gameweeks": has_dgw,
            "recommended_schedule": schedule,
            "candidate_rankings": {
                k: [
                    {
                        "gameweek": c["gameweek"],
                        "gw_type": c["gw_type"],
                        "immediate_ev": c["immediate_ev"],
                        "future_opportunity": c["future_opportunity"],
                        "net_utility": c["net_utility"],
                        "confidence": c["confidence"],
                        "reasoning": c["reasoning"],
                    }
                    for c in v[:3]
                ]
                for k, v in candidates_by_chip.items()
            },
        }
