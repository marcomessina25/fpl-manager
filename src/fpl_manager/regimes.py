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
                start_probability_adjustment=+0.25,
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
