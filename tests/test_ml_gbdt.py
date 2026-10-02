"""Unit tests for V1.3 GBDT ML models, feature pipeline, and DecisionEngineV13."""

from __future__ import annotations

import math
import unittest

from fpl_manager.backtest.decision_engine import DecisionEngineV13, resolve_decision_engine
from fpl_manager.expected_points import calculate_component_xp, project_player_gameweek
from fpl_manager.historical.models import (
    HistoricalFixture,
    HistoricalGameweekSnapshot,
    HistoricalPlayerState,
)
from fpl_manager.ml.features import (
    FEATURE_NAMES,
    build_feature_vector,
    extract_player_feature_vector,
)
from fpl_manager.ml.models import GBDTPredictor
from fpl_manager.models import Position


class TestGBDTFeatures(unittest.TestCase):
    """Test feature vector extraction and consistency."""

    def test_feature_names_length(self):
        self.assertEqual(len(FEATURE_NAMES), 25)

    def test_build_feature_vector_finite(self):
        vec = build_feature_vector(
            position=Position.MIDFIELDER,
            price_tenths=85,
            status="a",
            chance_of_playing_next_round=100,
            starts=4,
            minutes=350,
            starts_last_3=3,
            starts_last_5=5,
            minutes_last_3=260,
            minutes_last_5=430,
            consecutive_zero_mins=0,
            finished_matches=4,
            days_since_prev_fixture=7.0,
            matches_last_7_days=1,
            matches_last_14_days=2,
            fdr=3,
            is_home=True,
            opp_strength=3,
            team_strength=4,
            expected_goals_per_90=0.35,
            expected_assists_per_90=0.25,
            expected_goals_conceded_per_90=0.9,
            form=6.5,
            points_per_game=8.0,
            selected_by_percent=25.0,
        )
        self.assertEqual(len(vec), 25)
        for val in vec:
            self.assertIsInstance(val, float)
            self.assertFalse(math.isnan(val))
            self.assertFalse(math.isinf(val))

    def test_extract_player_feature_vector_with_snapshot(self):
        player = HistoricalPlayerState(
            player_id=10,
            web_name="Saka",
            position=Position.MIDFIELDER,
            team_id=1,
            price_tenths=85,
            status="a",
            chance_of_playing_next_round=100,
            chance_of_playing_this_round=100,
            total_points=32,
            minutes=350,
            starts=4,
            expected_goals=1.2,
            expected_assists=0.9,
            expected_goal_involvements=2.1,
            expected_goals_conceded=3.5,
            expected_goals_per_90=0.31,
            expected_assists_per_90=0.23,
            expected_goals_conceded_per_90=0.9,
            clean_sheets_per_90=0.25,
            bps=85,
            ict_index=45.0,
            form=6.5,
            points_per_game=8.0,
            selected_by_percent=25.0,
            news="",
            starts_last_3=3,
            starts_last_5=4,
            minutes_last_3=265,
            minutes_last_5=350,
            consecutive_zero_mins=0,
        )
        fixture = HistoricalFixture(
            fixture_id=101,
            event=5,
            team_h=1,
            team_a=2,
            team_h_difficulty=3,
            team_a_difficulty=4,
            kickoff_time="2023-09-17T15:30:00Z",
            days_since_prev_h=7.0,
            matches_7d_h=1,
            matches_14d_h=2,
        )
        teams_map = {
            1: {"strength": 4},
            2: {"strength": 3},
        }

        vec = extract_player_feature_vector(
            player=player,
            fixture=fixture,
            finished_gameweeks=4,
            teams_map=teams_map,
        )
        self.assertEqual(len(vec), 25)
        # Position is MID -> pos_code 3.0
        self.assertEqual(vec[0], 3.0)
        # Cost is 85.0
        self.assertEqual(vec[1], 85.0)
        # starts_last_3 ratio: 3/3 = 1.0
        self.assertEqual(vec[7], 1.0)


class TestGBDTPredictor(unittest.TestCase):
    """Test GBDTPredictor prediction, serialization, and canonical loading."""

    def setUp(self):
        self.predictor = GBDTPredictor.load_canonical()

    def test_canonical_model_loaded(self):
        self.assertIsNotNone(self.predictor)
        self.assertTrue(self.predictor.is_fitted)

    def test_predict_participation(self):
        vec = build_feature_vector(
            position=Position.MIDFIELDER,
            price_tenths=125,
            status="a",
            chance_of_playing_next_round=100,
            starts=5,
            minutes=450,
            starts_last_3=3,
            starts_last_5=5,
            minutes_last_3=270,
            minutes_last_5=450,
            consecutive_zero_mins=0,
            finished_matches=5,
            days_since_prev_fixture=7.0,
            matches_last_7_days=1,
            matches_last_14_days=2,
            fdr=2,
            is_home=True,
            opp_strength=2,
            team_strength=5,
            expected_goals_per_90=0.5,
            expected_assists_per_90=0.4,
            expected_goals_conceded_per_90=0.6,
            form=7.5,
            points_per_game=8.5,
            selected_by_percent=45.0,
        )
        res = self.predictor.predict_participation_from_vector(vec, status="a", chance_val=1.0)
        self.assertGreaterEqual(res.p_start, 0.0)
        self.assertLessEqual(res.p_start, 1.0)
        self.assertGreaterEqual(res.p_sub, 0.0)
        self.assertLessEqual(res.p_sub, 1.0)
        self.assertGreaterEqual(res.expected_minutes, 0.0)
        self.assertLessEqual(res.expected_minutes, 90.0)
        # Premium starter should have high prob_start and high expected minutes
        self.assertGreater(res.p_start, 0.70)
        self.assertGreater(res.expected_minutes, 60.0)

    def test_predict_threat(self):
        vec = build_feature_vector(
            position=Position.FORWARD,
            price_tenths=140,
            status="a",
            chance_of_playing_next_round=100,
            starts=5,
            minutes=450,
            starts_last_3=3,
            starts_last_5=5,
            minutes_last_3=270,
            minutes_last_5=450,
            consecutive_zero_mins=0,
            finished_matches=5,
            days_since_prev_fixture=7.0,
            matches_last_7_days=1,
            matches_last_14_days=2,
            fdr=2,
            is_home=True,
            opp_strength=2,
            team_strength=5,
            expected_goals_per_90=0.9,
            expected_assists_per_90=0.2,
            expected_goals_conceded_per_90=0.5,
            form=8.0,
            points_per_game=9.0,
            selected_by_percent=60.0,
        )
        xg, xa, cs_prob = self.predictor.predict_threat(vec, expected_minutes=85.0)
        self.assertGreater(xg, 0.2)
        self.assertGreaterEqual(cs_prob, 0.0)
        self.assertLessEqual(cs_prob, 1.0)


class TestExpectedPointsV13(unittest.TestCase):
    """Test project_player_gameweek with predictor_version='v1.3'."""

    def test_project_player_gameweek_v13(self):
        team_fixtures = [{
            "opponent_id": 2,
            "opponent_short": "LUT",
            "is_home": True,
            "fdr": 2,
        }]

        proj = project_player_gameweek(
            player_id=1,
            web_name="Haaland",
            position=Position.FORWARD,
            team_id=1,
            team_short="MCI",
            price_tenths=140,
            status="a",
            total_points=35,
            finished_matches=4,
            gameweek=5,
            team_fixtures_in_gw=team_fixtures,
            minutes=360,
            starts=4,
            chance_of_playing_next_round=100,
            expected_goals_per_90=0.95,
            expected_assists_per_90=0.15,
            starts_last_3=3,
            starts_last_5=4,
            minutes_last_3=270,
            minutes_last_5=360,
            predictor_version="v1.3",
        )
        self.assertGreater(proj.expected_points, 4.0)
        self.assertGreater(proj.expected_minutes, 60.0)
        self.assertEqual(len(proj.fixtures), 1)
        self.assertGreater(proj.fixtures[0].xp_attack, 1.0)
        self.assertGreater(proj.fixtures[0].xp_appearance, 1.5)

    def test_calculate_component_xp_with_gbdt_values(self):
        breakdown = calculate_component_xp(
            position=Position.MIDFIELDER,
            price_tenths=85,
            fdr=2,
            is_home=True,
            expected_minutes=85.0,
            prob_60_plus=0.9,
            prob_sub=0.05,
            predictor_version="v1.3",
            gbdt_xg=0.55,
            gbdt_xa=0.35,
            gbdt_cs_prob=0.45,
        )
        self.assertGreater(breakdown["total"], 4.0)
        self.assertGreater(breakdown["att"], 2.0)
        self.assertAlmostEqual(breakdown["def"], 0.45 * 0.9 * 1.0, places=2)


class TestDecisionEngineV13(unittest.TestCase):
    """Test DecisionEngineV13 instantiation and registration."""

    def test_resolve_v13_engine(self):
        engine = resolve_decision_engine("v1.3")
        self.assertIsInstance(engine, DecisionEngineV13)
        self.assertEqual(engine.version, "v1.3")
        self.assertEqual(engine.horizon, 3)
        self.assertEqual(engine.gamma, 0.75)
        self.assertEqual(engine.dead_capital_weight, 3.0)
        self.assertEqual(engine.bench_weight, 0.15)


if __name__ == "__main__":
    unittest.main()
