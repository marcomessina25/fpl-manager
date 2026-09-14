"""Dedicated probabilistic participation and expected-minutes prediction engine for V0.8.2.

Implements Phases 3 to 8 of the V0.8 Roadmap (docs/v08/v08.md):
- 7.1 P(start) probabilistic classifier with Bayesian recency weighting.
- 7.2 P(sub) appearance probability conditional on not starting.
- 7.3 Expected minutes conditional on start E[mins | start].
- 7.4 Expected minutes conditional on sub appearance E[mins | sub].
- 9.0 Rotation and fixture congestion feature awareness (turnaround days, matches in 7 days).
- 12.0 Role-transition and consecutive non-appearance discounting.
"""

from dataclasses import dataclass
from typing import Any

from .models import Position


@dataclass(frozen=True, slots=True)
class ParticipationPrediction:
    """Decomposed participation prediction components for a player in a gameweek."""
    p_start: float
    p_sub: float
    p_play: float
    prob_60_plus: float
    mins_if_start: float
    mins_if_sub: float
    expected_minutes: float
    role_category: str  # 'nailed_starter', 'regular_starter', 'rotation', 'fringe', 'unavailable'
    congestion_discount_applied: float
    consecutive_zero_discount_applied: float


def get_position_price_priors(position: Position, price_tenths: int) -> tuple[float, float]:
    """Return prior (p_start, mins_if_start) based on position and price tier."""
    price_m = price_tenths / 10.0

    if position == Position.GOALKEEPER:
        if price_m >= 4.5:
            return 0.94, 90.0
        else:
            return 0.06, 90.0
    elif position == Position.DEFENDER:
        if price_m >= 6.5:
            return 0.90, 87.0
        elif price_m >= 5.5:
            return 0.82, 85.0
        elif price_m >= 4.5:
            return 0.65, 83.0
        else:
            return 0.20, 80.0
    elif position == Position.MIDFIELDER:
        if price_m >= 8.5:
            return 0.92, 84.0
        elif price_m >= 6.5:
            return 0.82, 80.0
        elif price_m >= 5.0:
            return 0.62, 77.0
        else:
            return 0.20, 72.0
    else:  # FORWARD
        if price_m >= 8.5:
            return 0.90, 82.0
        elif price_m >= 6.5:
            return 0.80, 78.0
        elif price_m >= 5.0:
            return 0.58, 75.0
        else:
            return 0.20, 70.0


def predict_player_participation(
    status: str,
    chance_of_playing_next_round: int | None = None,
    season_starts: int = 0,
    season_minutes: int = 0,
    finished_matches: int = 0,
    starts_last_3: int = 0,
    starts_last_5: int = 0,
    minutes_last_3: int = 0,
    minutes_last_5: int = 0,
    consecutive_zero_mins: int = 0,
    price_tenths: int = 50,
    position: Position = Position.MIDFIELDER,
    days_since_prev_fixture: float | None = None,
    matches_last_7_days: int = 0,
    fdr: int = 3,
    is_home: bool = True,
) -> ParticipationPrediction:
    """Predict decomposed participation probabilities and conditional expected minutes.
    
    Guarantees:
    - Pure function, 100% deterministic.
    - Uses strictly pre-deadline knowledge.
    - Smoothly handles beginning of season (Bayesian shrinkage toward priors).
    - Detects role-loss and consecutive zero minutes.
    - Factors in fixture turnaround and congestion.
    """
    status_lower = status.lower()

    # 1. Base Availability Discount
    if status_lower in ("i", "s", "u"):
        return ParticipationPrediction(
            p_start=0.0,
            p_sub=0.0,
            p_play=0.0,
            prob_60_plus=0.0,
            mins_if_start=0.0,
            mins_if_sub=0.0,
            expected_minutes=0.0,
            role_category="unavailable",
            congestion_discount_applied=0.0,
            consecutive_zero_discount_applied=0.0,
        )

    if chance_of_playing_next_round is not None:
        try:
            avail_factor = max(0.0, min(100.0, float(chance_of_playing_next_round))) / 100.0
        except (ValueError, TypeError):
            avail_factor = 0.75 if status_lower == "d" else 1.0
    elif status_lower == "d":
        avail_factor = 0.50
    else:
        avail_factor = 1.0

    prior_p_start, prior_mins_start = get_position_price_priors(position, price_tenths)

    # 2. Start Probability Formulation
    if finished_matches == 0:
        base_p_start = prior_p_start
        mins_if_start = prior_mins_start
    elif finished_matches < 3:
        season_start_rate = season_starts / finished_matches
        # Heavy prior weight early in season
        w_obs = min(0.60, finished_matches * 0.25)
        base_p_start = w_obs * season_start_rate + (1.0 - w_obs) * prior_p_start

        if season_starts > 0:
            obs_mins_per_start = season_minutes / season_starts
            mins_if_start = w_obs * obs_mins_per_start + (1.0 - w_obs) * prior_mins_start
        else:
            mins_if_start = prior_mins_start
    else:
        # Full Bayesian recency blend
        season_start_rate = season_starts / finished_matches
        n_recent = min(3, finished_matches)
        recent_start_rate = starts_last_3 / float(n_recent)

        # Recency weights: 50% recent trend, 35% season track record, 15% prior
        base_p_start = 0.50 * recent_start_rate + 0.35 * season_start_rate + 0.15 * prior_p_start

        if season_starts > 0:
            obs_mins_per_start = season_minutes / season_starts
            mins_if_start = 0.70 * obs_mins_per_start + 0.30 * prior_mins_start
        else:
            mins_if_start = prior_mins_start

    mins_if_start = max(50.0, min(90.0, mins_if_start))

    # 3. Consecutive Zero-Minutes Role Loss Discount
    # Directly addresses the high-confidence false positive cohort (e.g. absent/benched regulars)
    zero_discount = 1.0
    if consecutive_zero_mins >= 3:
        zero_discount = 0.15
    elif consecutive_zero_mins == 2:
        zero_discount = 0.45
    elif consecutive_zero_mins == 1 and starts_last_3 <= 1:
        zero_discount = 0.80

    # 4. Fixture Congestion & Turnaround Discount (Phase 5)
    congestion_discount = 1.0
    if days_since_prev_fixture is not None and days_since_prev_fixture <= 2.8:
        # Extreme short turnaround (e.g. 2.5 days)
        if position == Position.GOALKEEPER:
            congestion_discount = 0.98
        elif position == Position.DEFENDER:
            congestion_discount = 0.88  # Fullbacks/wingbacks heavily rotated
        else:
            congestion_discount = 0.85
    elif matches_last_7_days >= 2:
        # Multiple matches in 7 days
        if position != Position.GOALKEEPER:
            congestion_discount = 0.90

    # Combine start probability factors
    p_start_raw = base_p_start * avail_factor * zero_discount * congestion_discount
    p_start = round(max(0.0, min(1.0, p_start_raw)), 3)

    # 5. Substitute Appearance Probability P(sub)
    if position == Position.GOALKEEPER:
        p_sub = 0.005 if p_start < 0.50 and avail_factor > 0.0 else 0.001
        mins_if_sub = 15.0
    else:
        # Outfield substitute probability conditional on not starting
        unstarted_prob = max(0.0, 1.0 - p_start)
        base_sub_rate = 0.45 if position in (Position.MIDFIELDER, Position.FORWARD) else 0.25
        # Experienced or attacking assets more likely to be used as subs
        if price_tenths >= 60:
            base_sub_rate += 0.15
        p_sub = round(min(0.65, unstarted_prob * base_sub_rate * avail_factor * zero_discount), 3)
        mins_if_sub = 18.5

    # Total appearance probability
    p_play = round(min(1.0, p_start + p_sub), 3)

    # 6. Total Expected Minutes (Two-Stage Conditional Sum)
    expected_mins = round(min(90.0, p_start * mins_if_start + p_sub * mins_if_sub), 1)

    # 7. Probability of 60+ Minutes
    prob_60_start = 0.93 if mins_if_start >= 80.0 else (0.75 if mins_if_start >= 65.0 else 0.40)
    prob_60 = round(min(1.0, p_start * prob_60_start), 3)

    # Role categorization
    if p_start >= 0.80 and expected_mins >= 65.0:
        role = "nailed_starter"
    elif p_start >= 0.60:
        role = "regular_starter"
    elif expected_mins >= 25.0 or p_play >= 0.50:
        role = "rotation"
    else:
        role = "fringe"

    return ParticipationPrediction(
        p_start=p_start,
        p_sub=p_sub,
        p_play=p_play,
        prob_60_plus=prob_60,
        mins_if_start=round(mins_if_start, 1),
        mins_if_sub=round(mins_if_sub, 1),
        expected_minutes=expected_mins,
        role_category=role,
        congestion_discount_applied=round(1.0 - congestion_discount, 3),
        consecutive_zero_discount_applied=round(1.0 - zero_discount, 3),
    )
