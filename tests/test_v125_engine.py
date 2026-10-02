"""Tests for V1.2.5 DecisionEngineV125 scaffolding and V1.2 behavioral parity.

Verifies:
1. Alias resolution for DecisionEngineV125 across all supported aliases.
2. Identical behavioral parity between DecisionEngineV12 and DecisionEngineV125 on initial squad selection.
3. Identical transfer recommendations between DecisionEngineV12 and DecisionEngineV125 on fixed snapshot scenarios.
"""

from pathlib import Path
import pytest

from fpl_manager.backtest.decision_engine import (
    DecisionEngineV12,
    DecisionEngineV125,
    resolve_decision_engine,
)
from fpl_manager.expected_points import ExpectedPointsProjection
from fpl_manager.historical.models import HistoricalGameweekSnapshot
from fpl_manager.models import Position


class TestDecisionEngineV125Scaffolding:
    """Validate DecisionEngineV125 alias resolution, metadata, and configuration."""

    def test_v125_resolves_from_all_aliases(self) -> None:
        aliases = ("v1.2.5", "v125", "v1.2.5.0", "balanced_v125")
        for alias in aliases:
            eng = resolve_decision_engine(alias)
            assert isinstance(eng, DecisionEngineV125), f"Failed for alias: {alias}"
            assert eng.version == "v1.2.5"
            assert eng.bench_weight == 0.15
            assert eng.dead_capital_weight == 3.0

    def test_v125_resolves_strategy_and_weight_variants(self) -> None:
        eng_strat = resolve_decision_engine("v1.2.5_aggressive")
        assert isinstance(eng_strat, DecisionEngineV125)
        assert eng_strat.initial_strategy == "aggressive"

        eng_w = resolve_decision_engine("v125_w0.75")
        assert isinstance(eng_w, DecisionEngineV125)
        assert eng_w.lineup_penalty_weight == 0.75

    def test_v125_matches_v12_decisions_on_fixed_snapshot(self) -> None:
        """On a fixed snapshot and set of candidate projections, V1.2 and V1.25 produce identical transfers."""
        eng_v12 = DecisionEngineV12(bench_weight=0.15, dead_capital_weight=3.0)
        eng_v125 = DecisionEngineV125(bench_weight=0.15, dead_capital_weight=3.0)

        def _make_proj(pid: int, name: str, pos: Position, tid: int, cost: int, xp: float) -> ExpectedPointsProjection:
            return ExpectedPointsProjection(
                player_id=pid,
                web_name=name,
                position=pos,
                team_id=tid,
                team_short=f"T{tid}",
                price_tenths=cost,
                status="a",
                availability_pct=100.0,
                base_xp_per_match=xp,
                gameweek=10,
                fixtures=(),
                expected_points=xp,
                expected_minutes=90.0,
                play_probability=1.0,
            )

        projs = [
            # GKPs
            _make_proj(1, "GK1", Position.GOALKEEPER, 1, 50, 4.5),
            _make_proj(2, "GK2", Position.GOALKEEPER, 2, 40, 1.0),
            # DEFs
            _make_proj(3, "DEF1", Position.DEFENDER, 3, 60, 5.5),
            _make_proj(4, "DEF2", Position.DEFENDER, 4, 55, 4.8),
            _make_proj(5, "DEF3", Position.DEFENDER, 5, 50, 4.2),
            _make_proj(6, "DEF4", Position.DEFENDER, 6, 45, 3.0),
            _make_proj(7, "DEF5", Position.DEFENDER, 7, 40, 1.5),
            # MIDs
            _make_proj(8, "MID1", Position.MIDFIELDER, 8, 125, 9.5),
            _make_proj(9, "MID2", Position.MIDFIELDER, 9, 85, 7.0),
            _make_proj(10, "MID3", Position.MIDFIELDER, 10, 80, 6.5),
            _make_proj(11, "MID4", Position.MIDFIELDER, 11, 65, 5.0),
            _make_proj(12, "MID5", Position.MIDFIELDER, 12, 45, 2.0),
            # FWDs
            _make_proj(13, "FWD1", Position.FORWARD, 13, 140, 10.0),
            _make_proj(14, "FWD2", Position.FORWARD, 14, 75, 5.8),
            _make_proj(15, "FWD3", Position.FORWARD, 15, 45, 1.8),
        ]

        # Candidate targets for transfer
        cand_projs = projs + [
            _make_proj(16, "CAND_MID", Position.MIDFIELDER, 16, 75, 8.2),
            _make_proj(17, "CAND_FWD", Position.FORWARD, 17, 80, 7.5),
            _make_proj(18, "CAND_DEF", Position.DEFENDER, 18, 50, 5.2),
        ]

        snap = HistoricalGameweekSnapshot(
            season="2023-24",
            gameweek=10,
            deadline_time="2023-10-28T10:00:00Z",
            finished_gameweeks=9,
            players=(),
            teams=(),
            fixtures=(),
        )

        curr_squad_ids = [p.player_id for p in projs]
        purchase_prices = {p.player_id: p.price_tenths for p in projs}

        moves_v12 = eng_v12.decide_transfers(
            strategy_name="production",
            current_squad_ids=curr_squad_ids,
            purchase_prices=purchase_prices,
            free_transfers=1,
            bank_tenths=15,
            snapshot=snap,
            projections=cand_projs,
            allow_hits=False,
        )

        moves_v125 = eng_v125.decide_transfers(
            strategy_name="production",
            current_squad_ids=curr_squad_ids,
            purchase_prices=purchase_prices,
            free_transfers=1,
            bank_tenths=15,
            snapshot=snap,
            projections=cand_projs,
            allow_hits=False,
        )

        assert moves_v12 == moves_v125, f"Discrepancy: V1.2={moves_v12} vs V1.2.5={moves_v125}"
        assert len(moves_v125) > 0, "Transfer should have been recommended"

    def test_v125_matches_v12_initial_squad(self) -> None:
        """On a fixed snapshot and set of projections, V1.2 and V1.25 select identical initial squads."""
        eng_v12 = DecisionEngineV12(bench_weight=0.15, dead_capital_weight=3.0)
        eng_v125 = DecisionEngineV125(bench_weight=0.15, dead_capital_weight=3.0)

        def _make_proj(pid: int, name: str, pos: Position, tid: int, cost: int, xp: float) -> ExpectedPointsProjection:
            return ExpectedPointsProjection(
                player_id=pid,
                web_name=name,
                position=pos,
                team_id=tid,
                team_short=f"T{tid}",
                price_tenths=cost,
                status="a",
                availability_pct=100.0,
                base_xp_per_match=xp,
                gameweek=1,
                fixtures=(),
                expected_points=xp,
                expected_minutes=90.0,
                play_probability=1.0,
            )

        # 2 GKPs, 5 DEFs, 5 MIDs, 3 FWDs + alternates
        projs = [
            _make_proj(1, "GK1", Position.GOALKEEPER, 1, 50, 4.5),
            _make_proj(2, "GK2", Position.GOALKEEPER, 2, 40, 1.0),
            _make_proj(3, "DEF1", Position.DEFENDER, 3, 60, 5.5),
            _make_proj(4, "DEF2", Position.DEFENDER, 4, 55, 4.8),
            _make_proj(5, "DEF3", Position.DEFENDER, 5, 50, 4.2),
            _make_proj(6, "DEF4", Position.DEFENDER, 6, 45, 3.0),
            _make_proj(7, "DEF5", Position.DEFENDER, 7, 40, 1.5),
            _make_proj(8, "MID1", Position.MIDFIELDER, 8, 125, 9.5),
            _make_proj(9, "MID2", Position.MIDFIELDER, 9, 85, 7.0),
            _make_proj(10, "MID3", Position.MIDFIELDER, 10, 80, 6.5),
            _make_proj(11, "MID4", Position.MIDFIELDER, 11, 65, 5.0),
            _make_proj(12, "MID5", Position.MIDFIELDER, 12, 45, 2.0),
            _make_proj(13, "FWD1", Position.FORWARD, 13, 140, 10.0),
            _make_proj(14, "FWD2", Position.FORWARD, 14, 75, 5.8),
            _make_proj(15, "FWD3", Position.FORWARD, 15, 45, 1.8),
            # Extra alternatives for solver
            _make_proj(16, "ALT_GK", Position.GOALKEEPER, 3, 45, 3.5),
            _make_proj(17, "ALT_DEF", Position.DEFENDER, 8, 45, 3.8),
            _make_proj(18, "ALT_MID", Position.MIDFIELDER, 14, 70, 6.0),
            _make_proj(19, "ALT_FWD", Position.FORWARD, 15, 60, 4.5),
        ]

        from fpl_manager.historical.models import HistoricalPlayerState
        players_state = tuple(
            HistoricalPlayerState(
                player_id=p.player_id,
                web_name=p.web_name,
                position=p.position,
                team_id=p.team_id,
                price_tenths=p.price_tenths,
                status=p.status,
                chance_of_playing_next_round=100,
                chance_of_playing_this_round=100,
                total_points=0,
                minutes=0,
                starts=0,
                expected_goals=0.0,
                expected_assists=0.0,
                expected_goal_involvements=0.0,
                expected_goals_conceded=0.0,
                expected_goals_per_90=0.0,
                expected_assists_per_90=0.0,
                expected_goals_conceded_per_90=0.0,
                clean_sheets_per_90=0.0,
                bps=0,
                ict_index=0.0,
                form=0.0,
                points_per_game=0.0,
                selected_by_percent=0.0,
                news="",
            )
            for p in projs
        )
        snap = HistoricalGameweekSnapshot(
            season="2023-24",
            gameweek=1,
            deadline_time="2023-08-11T18:00:00Z",
            finished_gameweeks=0,
            players=players_state,
            teams=(),
            fixtures=(),
        )

        squad_v12, prices_v12, bank_v12 = eng_v12.initialize_squad(snap, projs, budget_tenths=1000)
        squad_v125, prices_v125, bank_v125 = eng_v125.initialize_squad(snap, projs, budget_tenths=1000)

        assert squad_v12 == squad_v125
        assert prices_v12 == prices_v125
        assert bank_v12 == bank_v125

