"""Historical feature reconstruction connecting snapshots to the production xP engine.

Implements Section 10 of V0.7 Plan:
Ensures point-in-time historical snapshots are passed directly into the production
`project_player_gameweek` feature pipeline without duplicate or divergent logic.
"""

from pathlib import Path
from typing import Any

from ..expected_points import ExpectedPointsProjection, project_player_gameweek
from .models import HistoricalGameweekSnapshot, Position


def reconstruct_features_and_project(
    snapshot: HistoricalGameweekSnapshot,
    player_ids: list[int] | None = None,
    predictor_version: str = "v0.8",
) -> list[ExpectedPointsProjection]:
    """Reconstruct feature inputs from historical snapshot and run production projection engine."""
    team_map = {t["team_id"]: t.get("short_name", f"T{t['team_id']}") for t in snapshot.teams}

    # Map fixtures by team_id and extract schedule metrics
    team_fixtures: dict[int, list[dict[str, Any]]] = {t_id: [] for t_id in team_map}
    team_turnaround: dict[int, float | None] = {}
    team_m7: dict[int, int] = {}

    for fix in snapshot.fixtures:
        team_h = fix.team_h
        team_a = fix.team_a
        h_fdr = fix.team_h_difficulty
        a_fdr = fix.team_a_difficulty

        if team_h in team_fixtures:
            team_fixtures[team_h].append({
                "opponent_id": team_a,
                "opponent_short": team_map.get(team_a, f"T{team_a}"),
                "is_home": True,
                "fdr": h_fdr,
            })
            team_turnaround[team_h] = fix.days_since_prev_h
            team_m7[team_h] = fix.matches_7d_h

        if team_a in team_fixtures:
            team_fixtures[team_a].append({
                "opponent_id": team_h,
                "opponent_short": team_map.get(team_h, f"T{team_h}"),
                "is_home": False,
                "fdr": a_fdr,
            })
            team_turnaround[team_a] = fix.days_since_prev_a
            team_m7[team_a] = fix.matches_7d_a

    target_players = snapshot.players
    if player_ids is not None:
        target_set = set(player_ids)
        target_players = tuple(p for p in snapshot.players if p.player_id in target_set)

    projections: list[ExpectedPointsProjection] = []
    for p in target_players:
        t_short = team_map.get(p.team_id, f"T{p.team_id}")
        t_fixs = team_fixtures.get(p.team_id, [])
        days_prev = team_turnaround.get(p.team_id)
        m7 = team_m7.get(p.team_id, 0)

        proj = project_player_gameweek(
            player_id=p.player_id,
            web_name=p.web_name,
            position=p.position,
            team_id=p.team_id,
            team_short=t_short,
            price_tenths=p.price_tenths,
            status=p.status,
            total_points=p.total_points,
            finished_matches=snapshot.finished_gameweeks,
            gameweek=snapshot.gameweek,
            team_fixtures_in_gw=t_fixs,
            minutes=p.minutes,
            starts=p.starts,
            chance_of_playing_next_round=p.chance_of_playing_next_round,
            chance_of_playing_this_round=p.chance_of_playing_this_round,
            expected_goals=p.expected_goals,
            expected_assists=p.expected_assists,
            expected_goal_involvements=p.expected_goal_involvements,
            expected_goals_conceded=p.expected_goals_conceded,
            expected_goals_per_90=p.expected_goals_per_90,
            expected_assists_per_90=p.expected_assists_per_90,
            expected_goals_conceded_per_90=p.expected_goals_conceded_per_90,
            clean_sheets_per_90=p.clean_sheets_per_90,
            bps=p.bps,
            ict_index=p.ict_index,
            starts_last_3=p.starts_last_3,
            starts_last_5=p.starts_last_5,
            minutes_last_3=p.minutes_last_3,
            minutes_last_5=p.minutes_last_5,
            consecutive_zero_mins=p.consecutive_zero_mins,
            days_since_prev_fixture=days_prev,
            matches_last_7_days=m7,
            predictor_version=predictor_version,
        )
        projections.append(proj)

    return projections
