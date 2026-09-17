"""Unit and integration tests for V0.9 learned participation model (Phases 2 & 3)."""

import json
from pathlib import Path
import pytest

from fpl_manager.expected_points import project_player_gameweek
from fpl_manager.historical.models import Position
from fpl_manager.learned_participation import (
    HierarchicalParticipationModel,
    LogisticModel,
    get_default_v09_participation_model,
    predict_player_participation_v09,
)


def test_logistic_model_fit_and_predict() -> None:
    # Train simple 2-feature logistic regression on synthetic separable data
    feature_names = ["bias", "x1", "x2"]
    X = [
        [1.0, 0.1, 0.2],
        [1.0, 0.2, 0.1],
        [1.0, 0.9, 0.8],
        [1.0, 0.8, 0.9],
    ]
    y = [0, 0, 1, 1]

    model = LogisticModel.fit(feature_names, X, y, epochs=200, learning_rate=0.5, l2_reg=0.001)

    prob_low = model.predict_proba([1.0, 0.15, 0.15])
    prob_high = model.predict_proba([1.0, 0.85, 0.85])

    assert prob_low < 0.5
    assert prob_high > 0.5
    assert prob_high > prob_low

    # Test serialization
    data = model.to_dict()
    restored = LogisticModel.from_dict(data)
    assert restored.predict_proba([1.0, 0.85, 0.85]) == pytest.approx(prob_high, rel=1e-4)


def test_hierarchical_participation_model_defaults() -> None:
    model = get_default_v09_participation_model()
    assert len(model.model_start.weights) == len(model.model_start.feature_names)
    assert len(model.model_sub.weights) == len(model.model_sub.feature_names)

    # Check that conditional minutes distributions exist for all four positions
    for pos in (Position.GOALKEEPER, Position.DEFENDER, Position.MIDFIELDER, Position.FORWARD):
        pos_str = pos.name
        assert pos_str in model.starters_conditional_minutes
        assert pos_str in model.subs_conditional_minutes
        assert model.starters_conditional_minutes[pos_str]["mean_minutes"] >= 70.0
        assert model.subs_conditional_minutes[pos_str]["mean_minutes"] >= 15.0


def test_hierarchical_participation_model_unavailable() -> None:
    pred = predict_player_participation_v09(
        status="i",  # Injured
        chance_of_playing_next_round=0,
        starts_last_3=3,
        minutes_last_3=270,
        position=Position.FORWARD,
    )
    assert pred.p_start == 0.0
    assert pred.p_sub == 0.0
    assert pred.p_play == 0.0
    assert pred.expected_minutes == 0.0
    assert pred.role_category == "unavailable"


def test_hierarchical_participation_model_nailed_starter() -> None:
    pred = predict_player_participation_v09(
        status="a",
        chance_of_playing_next_round=None,
        starts_last_3=3,
        starts_last_5=5,
        minutes_last_3=270,
        consecutive_zero_mins=0,
        price_tenths=140,  # Premium asset
        position=Position.FORWARD,
    )
    assert pred.p_start >= 0.75
    assert pred.p_play >= pred.p_start
    assert pred.expected_minutes >= 60.0
    assert pred.prob_60_plus >= 0.70
    assert pred.role_category in ("nailed_starter", "regular_starter")


def test_hierarchical_participation_model_role_loss() -> None:
    # Player benched 3 games in a row
    pred = predict_player_participation_v09(
        status="a",
        chance_of_playing_next_round=None,
        starts_last_3=0,
        starts_last_5=0,
        minutes_last_3=0,
        consecutive_zero_mins=3,
        price_tenths=55,
        position=Position.MIDFIELDER,
    )
    assert pred.p_start < 0.25
    assert pred.expected_minutes < 25.0


def test_project_player_gameweek_v09_routing() -> None:
    fixtures = [{
        "opponent_id": 2,
        "opponent_short": "CHE",
        "is_home": True,
        "fdr": 2,
    }]

    # V0.9 Predictor
    proj_v09 = project_player_gameweek(
        player_id=1,
        web_name="Saka",
        position=Position.MIDFIELDER,
        team_id=1,
        team_short="ARS",
        price_tenths=100,
        status="a",
        total_points=50,
        finished_matches=10,
        gameweek=11,
        team_fixtures_in_gw=fixtures,
        starts=10,
        minutes=850,
        starts_last_3=3,
        starts_last_5=5,
        minutes_last_3=270,
        minutes_last_5=450,
        predictor_version="v0.9",
    )

    # V0.8 Predictor
    proj_v08 = project_player_gameweek(
        player_id=1,
        web_name="Saka",
        position=Position.MIDFIELDER,
        team_id=1,
        team_short="ARS",
        price_tenths=100,
        status="a",
        total_points=50,
        finished_matches=10,
        gameweek=11,
        team_fixtures_in_gw=fixtures,
        starts=10,
        minutes=850,
        starts_last_3=3,
        minutes_last_3=270,
        predictor_version="v0.8",
    )

    assert proj_v09.expected_minutes > 50.0
    assert proj_v09.start_probability > 0.70
    assert proj_v09.play_probability >= proj_v09.start_probability
    assert proj_v09.sub_probability >= 0.0

    # Ensure v0.8 remains unaffected and valid
    assert proj_v08.expected_minutes > 50.0
    assert proj_v08.start_probability > 0.70
