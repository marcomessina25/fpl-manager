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
