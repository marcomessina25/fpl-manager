"""Unit tests for rank-aware optimization utility and football context store (V0.8.6 & V0.8.7)."""

from pathlib import Path
import pytest

from fpl_manager.football_context import (
    FootballContextStore,
    FootballObservation,
    ObservationCategory,
    ObservationType,
)
from fpl_manager.llm_advisor import generate_strategy_dossier_critique
from fpl_manager.models import Position
from fpl_manager.optimizer import PlayerOptInfo, get_player_profile_value
from fpl_manager.participation import ParticipationPrediction
from fpl_manager.squad_state import CurrentSquadState


def test_rank_aware_utility_profiles() -> None:
    # Differential player: low ownership, high variance (high ceiling, low floor)
    differential = PlayerOptInfo(
        id=1,
        name="Diff Pick",
        position=Position.MIDFIELDER,
        team_id=1,
        team_short="BHA",
        price_tenths=65,
        status="a",
        total_points=25,
        expected_points=4.5,
        expected_minutes=75.0,
        xp_floor=1.8,
        xp_ceiling=9.5,
        standard_deviation=2.8,
        selected_by_percent=3.2,
    )

    # Template player: high ownership, steady floor
    template = PlayerOptInfo(
        id=2,
        name="Template Pick",
        position=Position.MIDFIELDER,
        team_id=2,
        team_short="ARS",
        price_tenths=85,
        status="a",
        total_points=45,
        expected_points=5.2,
        expected_minutes=88.0,
        xp_floor=4.0,
        xp_ceiling=7.2,
        standard_deviation=1.2,
        selected_by_percent=55.0,
    )

    # Neutral profile prioritizes pure expected points
    assert get_player_profile_value(differential, "neutral") == 4.5
    assert get_player_profile_value(template, "neutral") == 5.2

    # Defend Lead profile prioritizes template asset with high floor & low variance
    val_defend_diff = get_player_profile_value(differential, "defend_lead")
    val_defend_tmpl = get_player_profile_value(template, "defend_lead")
    assert val_defend_tmpl > val_defend_diff

    # Chase profile rewards differential upside and variance
    val_chase_diff = get_player_profile_value(differential, "chase")
    val_chase_tmpl = get_player_profile_value(template, "chase")
    assert val_chase_diff > val_chase_tmpl


def test_football_context_store_and_participation_modifiers(tmp_path: Path) -> None:
    store_file = tmp_path / "football_context.json"
    store = FootballContextStore(file_path=store_file)

    obs1 = FootballObservation(
        observation_id="obs-1",
        obs_type=ObservationType.FACT,
        category=ObservationCategory.SUSPENSION,
        source="Official FA",
        timestamp="2026-09-12T10:00:00Z",
        confidence=1.0,
        headline="Suspended for 3 matches",
        detail="Violent conduct ban",
        player_id=10,
        effective_gameweek=5,
        expiry_gameweek=7,
        status_override="s",
    )
    store.add_observation(obs1)

    obs2 = FootballObservation(
        observation_id="obs-2",
        obs_type=ObservationType.INFERENCE,
        category=ObservationCategory.PRESS_CONFERENCE,
        source="Press Conference",
        timestamp="2026-09-12T11:00:00Z",
        confidence=0.8,
        headline="Manager says player is managing knock",
        detail="Likely 60 minute cap",
        player_id=20,
        effective_gameweek=5,
        expiry_gameweek=5,
        minutes_cap=60.0,
    )
    store.add_observation(obs2)

    # Query active observations
    gw5_obs = store.list_observations(gameweek=5)
    assert len(gw5_obs) == 2

    gw8_obs = store.list_observations(gameweek=8)
    assert len(gw8_obs) == 0

    # Apply to base participation prediction
    base_pred = ParticipationPrediction(
        p_start=0.90,
        p_sub=0.05,
        p_play=0.95,
        prob_60_plus=0.85,
        mins_if_start=85.0,
        mins_if_sub=18.5,
        expected_minutes=78.0,
        role_category="nailed_starter",
        congestion_discount_applied=0.0,
        consecutive_zero_discount_applied=0.0,
    )

    # Player 10 (suspended) -> 0 minutes
    mod_pred_10 = store.apply_context_to_participation(player_id=10, gameweek=5, base_pred=base_pred)
    assert mod_pred_10.p_start == 0.0
    assert mod_pred_10.expected_minutes == 0.0
    assert mod_pred_10.role_category == "unavailable"

    # Player 20 (minutes cap) -> minutes reduced
    mod_pred_20 = store.apply_context_to_participation(player_id=20, gameweek=5, base_pred=base_pred)
    assert mod_pred_20.expected_minutes <= 66.0


def test_strategy_dossier_critique() -> None:
    mock_squad = CurrentSquadState(
        player_ids=tuple(range(1, 16)),
        purchase_prices_tenths={i: 50 for i in range(1, 16)},
        bank_tenths=15,
        free_transfers=1,
        chips_remaining=(),
        season="2026/27",
    )

    candidate_strategies = [
        {
            "type": "1-transfer",
            "score": 5.4,
            "transfer_hits": 0,
            "outgoing": [{"id": 4, "name": "DefA", "xp": 2.5}],
            "incoming": [{"id": 101, "name": "DefB", "xp": 5.0, "expected_minutes": 88.0}],
        },
        {
            "type": "2-transfer",
            "score": 2.1,
            "transfer_hits": 1,
            "outgoing": [{"id": 4, "name": "DefA"}, {"id": 8, "name": "MidA"}],
            "incoming": [{"id": 101, "name": "DefB"}, {"id": 102, "name": "MidB", "expected_minutes": 45.0}],
        },
    ]

    critique = generate_strategy_dossier_critique(
        candidate_strategies=candidate_strategies,
        current_squad=mock_squad,
        gameweek=3,
    )

    assert critique["total_candidates_analyzed"] == 2
    assert len(critique["candidates"]) == 2
    assert critique["candidates"][0]["qualitative_verdict"] == "Strong"
    # Second candidate has hit and low minutes warning
    assert len(critique["candidates"][1]["tactical_traps"]) >= 1
