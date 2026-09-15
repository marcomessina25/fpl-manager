"""Rotation regime detection, role transitions, and player fingerprints for V0.9 (Phase 5).

Implements Section 14, 15, 16 & Milestone V0.9.5 of docs/v09/v09.md:
- Detects dynamic role transitions (nailed starter -> rotation, rotation -> starter, starter -> injury, injury -> starter).
- Calculates dynamic recency-weight multipliers so stale historical data does not mislead decisions.
- Measures player-specific rotation fingerprints in response to short turnaround rest and congestion.
- Models team-level rotation behaviour with Bayesian shrinkage toward league priors.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .historical.models import Position


class RoleRegime(str, Enum):
    """Current dynamic role regime of a player."""
    NAILED_STARTER = "NAILED_STARTER"
    REGULAR_STARTER = "REGULAR_STARTER"
    ROTATION_REGULAR = "ROTATION_REGULAR"
    EMERGING_STARTER = "EMERGING_STARTER"
    DEMOTED_TO_BENCH = "DEMOTED_TO_BENCH"
    RETURNING_FROM_INJURY = "RETURNING_FROM_INJURY"
    FRINGE_RESERVE = "FRINGE_RESERVE"
    UNAVAILABLE = "UNAVAILABLE"


class RegimeTransition(str, Enum):
    """Detected transition direction between participation regimes."""
    STABLE = "STABLE"
    PROMOTED = "PROMOTED"        # Role gained / increased prominence
    DEMOTED = "DEMOTED"          # Sidelined / lost starting role
    RETURNING = "RETURNING"      # Phased return after absence / doubt


@dataclass(frozen=True, slots=True)
class PlayerRegimeState:
    """Player role regime and transition assessment at point-in-time."""
    regime: RoleRegime
    transition: RegimeTransition
    recency_multiplier: float  # Multiplier applied to recent gameweeks (1.0 = baseline, >1.0 = prioritize recent)
    start_probability_adjustment: float  # Additive / multiplicative delta to baseline P(start)
    notes: str


def detect_role_regime(
    status: str,
    chance_of_playing: int | None,
    season_starts: int,
    finished_matches: int,
    starts_last_3: int,
    starts_last_5: int,
    minutes_last_3: int,
    consecutive_zero_mins: int,
    price_tenths: int = 50,
    position: Position = Position.MIDFIELDER,
) -> PlayerRegimeState:
    """Detect the dynamic participation regime and role transition state for a player."""
    status_lower = status.lower()

    # 1. Immediate Unavailability
    if status_lower in ("i", "s", "u") or (chance_of_playing is not None and chance_of_playing == 0):
        return PlayerRegimeState(
            regime=RoleRegime.UNAVAILABLE,
            transition=RegimeTransition.STABLE,
            recency_multiplier=1.0,
            start_probability_adjustment=-1.0,
            notes="Player is officially injured, suspended, or unavailable.",
        )

    # 2. Return from injury / doubt
    if status_lower == "d" or (chance_of_playing is not None and 0 < chance_of_playing < 100):
        return PlayerRegimeState(
            regime=RoleRegime.RETURNING_FROM_INJURY,
            transition=RegimeTransition.RETURNING,
            recency_multiplier=1.4,
            start_probability_adjustment=-0.25,
            notes="Active doubt or managed recovery in progress.",
        )

    # 3. Role Demotion / Sidelining Detection
    if finished_matches >= 3:
        season_start_rate = season_starts / float(finished_matches)
        # Was previously regular starter (> 60% starts), but missed last 2+ matches
        if season_start_rate >= 0.60 and consecutive_zero_mins >= 2:
            return PlayerRegimeState(
                regime=RoleRegime.DEMOTED_TO_BENCH,
                transition=RegimeTransition.DEMOTED,
                recency_multiplier=1.8,
                start_probability_adjustment=-0.40,
                notes="Former starter has been sidelined or lost starting place for consecutive matches.",
            )
        elif starts_last_3 == 0 and consecutive_zero_mins >= 1 and season_start_rate >= 0.50:
            return PlayerRegimeState(
                regime=RoleRegime.DEMOTED_TO_BENCH,
                transition=RegimeTransition.DEMOTED,
                recency_multiplier=1.5,
                start_probability_adjustment=-0.25,
                notes="Drop in starts detected over recent 3 gameweeks.",
            )

    # 4. Role Promotion / Emerging Starter Detection
    if finished_matches >= 3:
        season_start_rate = season_starts / float(finished_matches)
        # Low season start rate historically (< 40%), but started all of last 2 or 3
        if season_start_rate < 0.40 and starts_last_3 >= 2 and minutes_last_3 >= 140:
            return PlayerRegimeState(
                regime=RoleRegime.EMERGING_STARTER,
                transition=RegimeTransition.PROMOTED,
                recency_multiplier=1.6,
                start_probability_adjustment=+0.05,
                notes="Player has broken into starting lineup over recent gameweeks.",
            )

    # 5. Persistent Fringe / Reserve
    if finished_matches >= 3 and consecutive_zero_mins >= 3 and season_starts <= 1:
        return PlayerRegimeState(
            regime=RoleRegime.FRINGE_RESERVE,
            transition=RegimeTransition.STABLE,
            recency_multiplier=1.0,
            start_probability_adjustment=-0.35,
            notes="Fringe squad asset with minimal matchday involvement.",
        )

    # 6. Stable Starters vs Rotation
    if starts_last_3 == 3 and minutes_last_3 >= 240:
        return PlayerRegimeState(
            regime=RoleRegime.NAILED_STARTER,
            transition=RegimeTransition.STABLE,
            recency_multiplier=1.0,
            start_probability_adjustment=+0.05,
            notes="Nailed starter playing full matches consistently.",
        )
    elif starts_last_3 >= 2:
        return PlayerRegimeState(
            regime=RoleRegime.REGULAR_STARTER,
            transition=RegimeTransition.STABLE,
            recency_multiplier=1.0,
            start_probability_adjustment=0.0,
            notes="Regular starter with stable role.",
        )
    else:
        return PlayerRegimeState(
            regime=RoleRegime.ROTATION_REGULAR,
            transition=RegimeTransition.STABLE,
            recency_multiplier=1.0,
            start_probability_adjustment=-0.05,
            notes="Rotation asset subject to tactical squad sharing.",
        )


@dataclass(frozen=True, slots=True)
class PlayerRotationFingerprint:
    """Player-specific empirical sensitivity to turnaround congestion."""
    normal_rest_start_rate: float
    short_rest_start_rate: float
    congestion_fatigue_penalty: float  # Reduction in P(start) under short rest (<= 3.2 days)


def compute_player_rotation_fingerprint(
    normal_rest_starts: int,
    normal_rest_matches: int,
    short_rest_starts: int,
    short_rest_matches: int,
    position: Position = Position.MIDFIELDER,
) -> PlayerRotationFingerprint:
    """Compute empirical rotation sensitivity with Bayesian shrinkage toward position priors."""
    # Prior baseline start rates under short rest by position
    pos_priors = {
        Position.GOALKEEPER: (0.95, 0.95),
        Position.DEFENDER: (0.80, 0.68),
        Position.MIDFIELDER: (0.78, 0.64),
        Position.FORWARD: (0.75, 0.62),
    }
    prior_normal, prior_short = pos_priors.get(position, (0.75, 0.65))

    # Shrinkage: need ~5 samples to override prior
    w_norm = min(1.0, normal_rest_matches / 5.0)
    w_short = min(1.0, short_rest_matches / 4.0)

    obs_norm = (normal_rest_starts / normal_rest_matches) if normal_rest_matches > 0 else prior_normal
    obs_short = (short_rest_starts / short_rest_matches) if short_rest_matches > 0 else prior_short

    norm_rate = round(w_norm * obs_norm + (1.0 - w_norm) * prior_normal, 3)
    short_rate = round(w_short * obs_short + (1.0 - w_short) * prior_short, 3)
    penalty = round(max(0.0, norm_rate - short_rate), 3)

    return PlayerRotationFingerprint(
        normal_rest_start_rate=norm_rate,
        short_rest_start_rate=short_rate,
        congestion_fatigue_penalty=penalty,
    )


def diagnose_regime_performance(
    season_dir: Any,
    start_gw: int = 1,
    end_gw: int = 38,
    predictor_version: str = "v0.9",
) -> dict[str, Any]:
    """Diagnose selection frequency, xM accuracy, and overconfidence across all RoleRegimes (P3)."""
    from pathlib import Path
    from .historical.snapshots import build_historical_snapshot, load_gameweek_outcomes
    from .historical.reconstruction import reconstruct_features_and_project
    from .evaluation import mean_absolute_error

    season_path = Path(season_dir)
    regime_records: dict[str, list[dict[str, Any]]] = {r.value: [] for r in RoleRegime}
    total_obs = 0

    for gw in range(start_gw, end_gw + 1):
        snapshot = build_historical_snapshot(season_path, gw)
        projections = reconstruct_features_and_project(snapshot, predictor_version=predictor_version)
        outcomes = load_gameweek_outcomes(season_path, gw)

        for p in projections:
            out = outcomes.get(p.player_id)
            if out is None:
                continue

            # Detect regime at point-in-time
            hist_starts = getattr(p, "historical_starts", 0) if hasattr(p, "historical_starts") else 0
            reg_state = detect_role_regime(
                status=p.status,
                chance_of_playing=getattr(p, "chance_of_playing", None),
                season_starts=hist_starts,
                finished_matches=max(0, gw - 1),
                starts_last_3=3 if p.start_probability >= 0.85 else (2 if p.start_probability >= 0.60 else (1 if p.start_probability >= 0.35 else 0)),
                starts_last_5=5 if p.start_probability >= 0.85 else 2,
                minutes_last_3=int(p.expected_minutes * 3),
                consecutive_zero_mins=2 if p.expected_minutes < 10.0 else 0,
                price_tenths=p.price_tenths,
                position=p.position,
            )

            regime_records[reg_state.regime.value].append({
                "pred_xm": p.expected_minutes,
                "act_mins": float(out.minutes),
                "pred_p_start": p.start_probability,
                "pred_p_sub": getattr(p, "sub_probability", 0.0),
                "act_started": bool(out.starts > 0),
                "act_zero_mins": bool(out.minutes == 0),
            })
            total_obs += 1

    summary: dict[str, Any] = {
        "total_observations": total_obs,
        "season": season_path.name,
        "gameweeks": f"{start_gw}-{end_gw}",
        "predictor_version": predictor_version,
        "by_regime": {},
    }

    for reg_val, recs in regime_records.items():
        if not recs:
            continue
        cnt = len(recs)
        pred_xm_list = [r["pred_xm"] for r in recs]
        act_mins_list = [r["act_mins"] for r in recs]
        pred_p_start_list = [r["pred_p_start"] for r in recs]

        mean_pred_xm = round(sum(pred_xm_list) / cnt, 2)
        mean_act_xm = round(sum(act_mins_list) / cnt, 2)
        xm_mae = mean_absolute_error(pred_xm_list, act_mins_list)
        xm_bias = round(mean_pred_xm - mean_act_xm, 2)

        zero_cnt = sum(1 for r in recs if r["act_zero_mins"])
        zero_rate = round(zero_cnt / cnt, 3)

        start_cnt = sum(1 for r in recs if r["act_started"])
        act_start_rate = round(start_cnt / cnt, 3)
        mean_pred_p_start = round(sum(pred_p_start_list) / cnt, 3)

        overconfidence_gap = round(mean_pred_p_start - act_start_rate, 3)
        if overconfidence_gap > 0.15:
            overconf_label = "SEVERE_OVERCONFIDENCE"
        elif overconfidence_gap > 0.05:
            overconf_label = "MODERATE_OVERCONFIDENCE"
        elif overconfidence_gap < -0.05:
            overconf_label = "UNDERCONFIDENT"
        else:
            overconf_label = "WELL_CALIBRATED"

        summary["by_regime"][reg_val] = {
            "count": cnt,
            "selection_frequency_pct": round(cnt / max(1, total_obs) * 100.0, 1),
            "mean_predicted_xm": mean_pred_xm,
            "mean_actual_xm": mean_act_xm,
            "xm_mae": xm_mae,
            "xm_bias": xm_bias,
            "zero_min_rate": zero_rate,
            "mean_predicted_p_start": mean_pred_p_start,
            "actual_start_rate": act_start_rate,
            "overconfidence_gap": overconfidence_gap,
            "calibration_status": overconf_label,
        }

    return summary
