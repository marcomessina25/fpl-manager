"""Unit and regression tests for V1.2.5 Transfer Evaluation Refinements.

Pillar 1: Candidate Pool Expansion & Direct Lineup Ranking
Pillar 2: Goalkeeper Churn Suppression & Role-Specific Transfer Hurdles
Pillar 3: Multi-Gameweek Discounted Lineup Horizon (H=3, gamma=0.75)
"""

import pytest
from fpl_manager.backtest.decision_engine import (
    DecisionEngineV12,
    DecisionEngineV125,
)
from fpl_manager.expected_points import ExpectedPointsProjection
from fpl_manager.historical.models import HistoricalGameweekSnapshot
from fpl_manager.models import Position


class TestCandidatePoolExpansion:
    """Validate that expanding max_results surfaces Starting XI upgrades ranked outside top-5 flat squad sum."""

    def test_expanded_candidate_pool_surfaces_starter_upgrade_ranked_outside_top5(self) -> None:
        """Construct a scenario where:
        - 7 bench upgrade candidates offer flat squad delta +2.0 (ranks 1-7 in flat sum),
          but only +0.30 lineup delta (0.15 * 2.0).
        - 1 starter upgrade offers flat squad delta +1.5 (ranks 8th in flat sum),
          but +1.50 lineup delta (1.0 * 1.5).
        
        V1.2 (max_results=5) only sees the top 5 flat moves, rejecting them (net gain < 0.50).
        V1.2.5 (max_results=50) surfaces the 8th move and executes the Starter upgrade.
        """
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
                gameweek=15,
                fixtures=(),
                expected_points=xp,
                expected_minutes=90.0,
                play_probability=1.0,
            )

        # Baseline 15-player squad
        # Starting XI has 1 GKP, 3 DEF, 5 MID, 2 FWD
        # Bench has 1 GKP, 2 DEF, 1 FWD
        squad_projs = [
            # GKPs: 1 starter (4.5), 1 bench (1.0)
            _make_proj(1, "GK_Start", Position.GOALKEEPER, 1, 50, 4.5),
            _make_proj(2, "GK_Bench", Position.GOALKEEPER, 2, 40, 1.0),
            # DEFs: 3 starters (5.0, 5.0, 5.0), 2 bench (1.5, 1.0)
            _make_proj(11, "DEF_Start1", Position.DEFENDER, 3, 55, 5.0),
            _make_proj(12, "DEF_Start2", Position.DEFENDER, 4, 55, 5.0),
            _make_proj(13, "DEF_Start3", Position.DEFENDER, 5, 55, 5.0),
            _make_proj(14, "DEF_Bench1", Position.DEFENDER, 6, 40, 1.5),
            _make_proj(15, "DEF_Bench2", Position.DEFENDER, 7, 40, 1.0),
            # MIDs: 4 high starters, 1 mid starter (PID 25, 6.0 xP)
            _make_proj(21, "MID_Star1", Position.MIDFIELDER, 8, 125, 10.0),
            _make_proj(22, "MID_Star2", Position.MIDFIELDER, 9, 85, 7.5),
            _make_proj(23, "MID_Star3", Position.MIDFIELDER, 10, 80, 7.0),
            _make_proj(24, "MID_Star4", Position.MIDFIELDER, 11, 75, 6.5),
            _make_proj(25, "MID_TargetStarter", Position.MIDFIELDER, 12, 65, 6.0),
            # FWDs: 2 starters (11.0, 7.0), 1 bench (PID 33, 1.5 xP)
            _make_proj(31, "FWD_Star1", Position.FORWARD, 13, 140, 11.0),
            _make_proj(32, "FWD_Star2", Position.FORWARD, 14, 80, 7.0),
            _make_proj(33, "FWD_Bench", Position.FORWARD, 15, 45, 1.5),
        ]

        # Candidates:
        # 7 FWD bench upgrades (cost 45, xP 3.5 each; replacing FWD_Bench at 1.5 gives delta = +2.0 in flat squad sum)
        # In flat ranking, these 7 moves take ranks 1 to 7.
        bench_candidates = [
            _make_proj(101 + i, f"CAND_FWD_BENCH_{i}", Position.FORWARD, (i % 5) + 16, 45, 3.5)
            for i in range(7)
        ]

        # 1 MID starter upgrade (cost 75, xP 7.5; replacing MID_TargetStarter at 65/6.0 gives flat delta = +1.5)
        # Ranks 8th in flat squad sum delta (+1.5 < +2.0).
        starter_upgrade = _make_proj(200, "CAND_MID_PREMIUM", Position.MIDFIELDER, 20, 75, 7.5)

        all_cands = squad_projs + bench_candidates + [starter_upgrade]

        snap = HistoricalGameweekSnapshot(
            season="2023-24",
            gameweek=15,
            deadline_time="2023-12-05T18:00:00Z",
            finished_gameweeks=14,
            players=(),
            teams=(),
            fixtures=(),
        )

        curr_squad_ids = [p.player_id for p in squad_projs]
        purchase_prices = {p.player_id: p.price_tenths for p in squad_projs}
        # Provide bank = 10 tenths (£1.0m), enough to fund the MID upgrade (65 -> 75)
        bank_tenths = 10

        eng_v12 = DecisionEngineV12(bench_weight=0.15)
        moves_v12 = eng_v12.decide_transfers(
            strategy_name="production",
            current_squad_ids=curr_squad_ids,
            purchase_prices=purchase_prices,
            free_transfers=1,
            bank_tenths=bank_tenths,
            snapshot=snap,
            projections=all_cands,
            allow_hits=False,
            min_net_gain=0.50,
        )

        eng_v125 = DecisionEngineV125(bench_weight=0.15)
        moves_v125 = eng_v125.decide_transfers(
            strategy_name="production",
            current_squad_ids=curr_squad_ids,
            purchase_prices=purchase_prices,
            free_transfers=1,
            bank_tenths=bank_tenths,
            snapshot=snap,
            projections=all_cands,
            allow_hits=False,
            min_net_gain=0.50,
        )

        # Discriminating assertions:
        # V1.2 misses the starter upgrade because max_results=5 cut off moves 6-8.
        # Top 5 moves were bench moves offering only 0.15 * 2.0 = 0.30 net gain, below min_net_gain (0.50).
        assert moves_v12 == [], f"V1.2 should have found no viable moves above hurdle, got {moves_v12}"

        # V1.2.5 with expanded candidate pool finds the 8th move and executes the starting XI upgrade
        assert moves_v125 == [(25, 200)], f"V1.2.5 should have executed starter upgrade (25 -> 200), got {moves_v125}"
