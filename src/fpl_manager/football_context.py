"""Structured football context and qualitative evidence layer for V0.8.7.

Implements Phase 15 & 22 of the V0.8 Roadmap (docs/v08/v08.md):
- Structured external observations with explicit provenance and confidence.
- Distinct taxonomies: FACT, INFERENCE, RUMOUR, MODEL_ASSUMPTION.
- Traceable modifiers for participation and tactical role estimation.
- Local persistence in data/football_context.json.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from typing import Any

from .participation import ParticipationPrediction

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DEFAULT_CONTEXT_PATH = DATA_DIRECTORY / "football_context.json"


class ObservationType(str, Enum):
    """Epistemic classification of external football information."""
    FACT = "FACT"                     # Confirmed official facts (surgery, red card, FA suspension)
    INFERENCE = "INFERENCE"           # Probable deduction (e.g. fully rested in cup -> likely starter)
    RUMOUR = "RUMOUR"                 # Unverified reporting or leaked training lineup
    MODEL_ASSUMPTION = "MODEL_ASSUMPTION"  # Baseline prior or rule heuristic


class ObservationCategory(str, Enum):
    """Functional domain of the football observation."""
    INJURY = "INJURY"
    SUSPENSION = "SUSPENSION"
    ROTATION_REST = "ROTATION_REST"
    TACTICAL = "TACTICAL"
    PRESS_CONFERENCE = "PRESS_CONFERENCE"
    SET_PIECES = "SET_PIECES"
    TRANSFER = "TRANSFER"


@dataclass(frozen=True, slots=True)
class FootballObservation:
    """Individual structured contextual fact or qualitative observation."""
    observation_id: str
    obs_type: ObservationType
    category: ObservationCategory
    source: str
    timestamp: str
    confidence: float
    headline: str
    detail: str
    player_id: int | None = None
    player_name: str | None = None
    team_id: int | None = None
    team_short: str | None = None
    effective_gameweek: int | None = None
    expiry_gameweek: int | None = None
    p_start_modifier: float = 0.0
    minutes_cap: float | None = None
    status_override: str | None = None


class FootballContextStore:
    """Persistent storage and query engine for structured football context."""

    def __init__(self, file_path: Path = DEFAULT_CONTEXT_PATH):
        self.file_path = file_path

    def _load_raw(self) -> list[dict[str, Any]]:
        if not self.file_path.exists():
            return []
        try:
            return json.loads(self.file_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_raw(self, items: list[dict[str, Any]]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")

    def list_observations(
        self,
        player_id: int | None = None,
        team_id: int | None = None,
        gameweek: int | None = None,
    ) -> list[FootballObservation]:
        """Query observations filtered by player, team, or target gameweek."""
        raw = self._load_raw()
        results: list[FootballObservation] = []

        for r in raw:
            # Gameweek filtering
            eff_gw = r.get("effective_gameweek")
            exp_gw = r.get("expiry_gameweek")
            if gameweek is not None:
                if eff_gw is not None and gameweek < eff_gw:
                    continue
                if exp_gw is not None and gameweek > exp_gw:
                    continue

            # Player / team filtering
            if player_id is not None and r.get("player_id") != player_id:
                continue
            if team_id is not None and r.get("team_id") != team_id:
                continue

            obs = FootballObservation(
                observation_id=r["observation_id"],
                obs_type=ObservationType(r["obs_type"]),
                category=ObservationCategory(r["category"]),
                source=r.get("source", "Unknown"),
                timestamp=r.get("timestamp", ""),
                confidence=float(r.get("confidence", 1.0)),
                headline=r.get("headline", ""),
                detail=r.get("detail", ""),
                player_id=r.get("player_id"),
                player_name=r.get("player_name"),
                team_id=r.get("team_id"),
                team_short=r.get("team_short"),
                effective_gameweek=eff_gw,
                expiry_gameweek=exp_gw,
                p_start_modifier=float(r.get("p_start_modifier", 0.0)),
                minutes_cap=float(r["minutes_cap"]) if r.get("minutes_cap") is not None else None,
                status_override=r.get("status_override"),
            )
            results.append(obs)

        return results

    def add_observation(self, obs: FootballObservation) -> None:
        """Add and persist a new football observation."""
        raw = self._load_raw()
        # Remove any existing with identical id
        raw = [r for r in raw if r.get("observation_id") != obs.observation_id]
        raw.append({
            "observation_id": obs.observation_id,
            "obs_type": obs.obs_type.value,
            "category": obs.category.value,
            "source": obs.source,
            "timestamp": obs.timestamp,
            "confidence": obs.confidence,
            "headline": obs.headline,
            "detail": obs.detail,
            "player_id": obs.player_id,
            "player_name": obs.player_name,
            "team_id": obs.team_id,
            "team_short": obs.team_short,
            "effective_gameweek": obs.effective_gameweek,
            "expiry_gameweek": obs.expiry_gameweek,
            "p_start_modifier": obs.p_start_modifier,
            "minutes_cap": obs.minutes_cap,
            "status_override": obs.status_override,
        })
        self._save_raw(raw)

    def apply_context_to_participation(
        self,
        player_id: int,
        gameweek: int,
        base_pred: ParticipationPrediction,
    ) -> ParticipationPrediction:
        """Apply active structured observations to modify player participation projection traceably."""
        active_obs = self.list_observations(player_id=player_id, gameweek=gameweek)
        if not active_obs:
            return base_pred

        p_start = base_pred.p_start
        expected_mins = base_pred.expected_minutes
        prob_60 = base_pred.prob_60_plus
        role = base_pred.role_category
        min_effective_cap: float | None = None

        for obs in active_obs:
            # FACT observations carry 100% weight; RUMOUR or INFERENCE scale with confidence
            weight = obs.confidence if obs.obs_type != ObservationType.FACT else 1.0

            if obs.status_override in ("i", "s", "u"):
                return ParticipationPrediction(
                    p_start=0.0,
                    p_sub=0.0,
                    p_play=0.0,
                    prob_60_plus=0.0,
                    mins_if_start=0.0,
                    mins_if_sub=0.0,
                    expected_minutes=0.0,
                    role_category="unavailable",
                    congestion_discount_applied=base_pred.congestion_discount_applied,
                    consecutive_zero_discount_applied=base_pred.consecutive_zero_discount_applied,
                )

            if obs.p_start_modifier != 0.0:
                delta = obs.p_start_modifier * weight
                p_start = round(max(0.0, min(1.0, p_start + delta)), 3)

            if obs.minutes_cap is not None:
                effective_cap = obs.minutes_cap * weight + 90.0 * (1.0 - weight)
                if min_effective_cap is None or effective_cap < min_effective_cap:
                    min_effective_cap = effective_cap

        # Recompute conditional minutes given modified start probability
        if p_start == 0.0:
            expected_mins = round(base_pred.p_sub * base_pred.mins_if_sub, 1)
            prob_60 = 0.0
            role = "rotation" if expected_mins > 0 else "unavailable"
        else:
            expected_mins = round(min(90.0, p_start * base_pred.mins_if_start + base_pred.p_sub * base_pred.mins_if_sub), 1)

        if min_effective_cap is not None:
            expected_mins = round(min(expected_mins, min_effective_cap), 1)
            if expected_mins < 60.0:
                prob_60 = round(min(prob_60, 0.20), 3)

        return ParticipationPrediction(
            p_start=p_start,
            p_sub=base_pred.p_sub,
            p_play=round(min(1.0, p_start + base_pred.p_sub), 3),
            prob_60_plus=prob_60,
            mins_if_start=base_pred.mins_if_start,
            mins_if_sub=base_pred.mins_if_sub,
            expected_minutes=expected_mins,
            role_category=role,
            congestion_discount_applied=base_pred.congestion_discount_applied,
            consecutive_zero_discount_applied=base_pred.consecutive_zero_discount_applied,
        )
