from fpl_manager.expected_points import calculate_component_xp, project_player_gameweek
from fpl_manager.models import Position


def test_v09_goalkeeper_save_points_calibration() -> None:
    # Under V0.8, goalkeepers got 0 save points
    comp_v08 = calculate_component_xp(
        position=Position.GOALKEEPER,
        price_tenths=50,
        fdr=3,
        is_home=True,
        expected_minutes=90.0,
        prob_60_plus=1.0,
        prob_sub=0.0,
        expected_goals_conceded_per_90=1.4,
        clean_sheets_per_90=0.3,
        finished_matches=10,
        predictor_version="v0.8",
    )

    # Under V0.9, goalkeepers earn save points (~0.75 + 0.25 * team_xgc)
    comp_v09 = calculate_component_xp(
        position=Position.GOALKEEPER,
        price_tenths=50,
        fdr=3,
        is_home=True,
        expected_minutes=90.0,
        prob_60_plus=1.0,
        prob_sub=0.0,
        expected_goals_conceded_per_90=1.4,
        clean_sheets_per_90=0.3,
        finished_matches=10,
        predictor_version="v0.9",
    )

    assert comp_v09["def"] > comp_v08["def"]
    assert comp_v09["total"] > comp_v08["total"]


def test_v09_clean_sheet_empirical_shrinkage() -> None:
    # High clean sheet rate team (e.g. 50% clean sheets)
    comp_high_cs = calculate_component_xp(
        position=Position.DEFENDER,
        price_tenths=60,
        fdr=3,
        is_home=True,
        expected_minutes=90.0,
        prob_60_plus=1.0,
        prob_sub=0.0,
        expected_goals_conceded_per_90=0.8,
        clean_sheets_per_90=0.55,
        finished_matches=10,
        predictor_version="v0.9",
    )

    # Low clean sheet rate team (e.g. 10% clean sheets)
    comp_low_cs = calculate_component_xp(
        position=Position.DEFENDER,
        price_tenths=60,
        fdr=3,
        is_home=True,
        expected_minutes=90.0,
        prob_60_plus=1.0,
        prob_sub=0.0,
        expected_goals_conceded_per_90=2.0,
        clean_sheets_per_90=0.10,
        finished_matches=10,
        predictor_version="v0.9",
    )

    assert comp_high_cs["def"] > comp_low_cs["def"]
    assert comp_high_cs["total"] > comp_low_cs["total"]


def test_v09_attacking_conversion_calibration() -> None:
    # Forward vs Midfielder with identical xG
    comp_fwd = calculate_component_xp(
        position=Position.FORWARD,
        price_tenths=100,
        fdr=3,
        is_home=True,
        expected_minutes=90.0,
        prob_60_plus=1.0,
        prob_sub=0.0,
        expected_goals_per_90=0.60,
        expected_assists_per_90=0.20,
        finished_matches=10,
        predictor_version="v0.9",
    )

    comp_mid = calculate_component_xp(
        position=Position.MIDFIELDER,
        price_tenths=100,
        fdr=3,
        is_home=True,
        expected_minutes=90.0,
        prob_60_plus=1.0,
        prob_sub=0.0,
        expected_goals_per_90=0.60,
        expected_assists_per_90=0.20,
        finished_matches=10,
        predictor_version="v0.9",
    )

    assert comp_fwd["att"] > 0.0
    assert comp_mid["att"] > 0.0
    assert comp_fwd["bon"] > 0.0


def test_v09_project_player_gameweek_passes_predictor_version() -> None:
    fixtures = [{
        "opponent_id": 2,
        "opponent_short": "CHE",
        "is_home": True,
        "fdr": 3,
    }]

    proj_v09 = project_player_gameweek(
        player_id=1,
        web_name="Raya",
        position=Position.GOALKEEPER,
        team_id=1,
        team_short="ARS",
        price_tenths=55,
        status="a",
        total_points=40,
        finished_matches=10,
        gameweek=11,
        team_fixtures_in_gw=fixtures,
        starts=10,
        minutes=900,
        starts_last_3=3,
        starts_last_5=5,
        minutes_last_3=270,
        minutes_last_5=450,
        clean_sheets_per_90=0.5,
        expected_goals_conceded_per_90=0.9,
        predictor_version="v0.9",
    )

    proj_v08 = project_player_gameweek(
        player_id=1,
        web_name="Raya",
        position=Position.GOALKEEPER,
        team_id=1,
        team_short="ARS",
        price_tenths=55,
        status="a",
        total_points=40,
        finished_matches=10,
        gameweek=11,
        team_fixtures_in_gw=fixtures,
        starts=10,
        minutes=900,
        starts_last_3=3,
        starts_last_5=5,
        minutes_last_3=270,
        minutes_last_5=450,
        clean_sheets_per_90=0.5,
        expected_goals_conceded_per_90=0.9,
        predictor_version="v0.8",
    )

    # Under V0.9 Raya receives save points and enhanced CS probability
    assert proj_v09.expected_points > proj_v08.expected_points
