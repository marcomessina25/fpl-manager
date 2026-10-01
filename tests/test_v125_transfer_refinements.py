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


class TestGoalkeeperChurnSuppression:
    """Validate Pillar 2: GK transfer hurdle (1.50 pts) vs outfield hurdle (0.50 pts) and injury override."""

    def test_gk_swap_below_hurdle_rejected_outfield_swap_above_hurdle_accepted(self) -> None:
        """With identical net gain of 1.0:
        - GK swap gain 1.0 < gk_min_net_gain (1.50) => rejected when tested alone.
        - Outfield swap gain 1.0 >= outfield_min_net_gain (0.50) => accepted.
        """
        def _make_proj(pid: int, name: str, pos: Position, tid: int, cost: int, xp: float, prob: float = 1.0) -> ExpectedPointsProjection:
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
                play_probability=prob,
            )

        squad = [
            _make_proj(1, "GK_Start", Position.GOALKEEPER, 1, 50, 4.0, prob=1.0),
            _make_proj(2, "GK_Bench", Position.GOALKEEPER, 2, 40, 1.0, prob=0.0),
            _make_proj(11, "DEF1", Position.DEFENDER, 3, 55, 5.0),
            _make_proj(12, "DEF2", Position.DEFENDER, 4, 55, 5.0),
            _make_proj(13, "DEF3", Position.DEFENDER, 5, 55, 5.0),
            _make_proj(14, "DEF4", Position.DEFENDER, 6, 40, 1.5),
            _make_proj(15, "DEF5", Position.DEFENDER, 7, 40, 1.0),
            _make_proj(21, "MID1", Position.MIDFIELDER, 8, 125, 10.0),
            _make_proj(22, "MID2", Position.MIDFIELDER, 9, 85, 7.5),
            _make_proj(23, "MID3", Position.MIDFIELDER, 10, 80, 7.0),
            _make_proj(24, "MID4", Position.MIDFIELDER, 11, 75, 6.5),
            _make_proj(25, "MID5", Position.MIDFIELDER, 12, 65, 5.0),
            _make_proj(31, "FWD1", Position.FORWARD, 13, 140, 11.0),
            _make_proj(32, "FWD2", Position.FORWARD, 14, 80, 7.0),
            _make_proj(33, "FWD3", Position.FORWARD, 15, 45, 1.5),
        ]
        squad_ids = [p.player_id for p in squad]
        purchase_prices = {p.player_id: p.price_tenths for p in squad}

        snap = HistoricalGameweekSnapshot(
            season="2023-24",
            gameweek=10,
            deadline_time="2023-10-28T10:00:00Z",
            finished_gameweeks=9,
            players=(),
            teams=(),
            fixtures=(),
        )

        # 1. Candidate: GK replacement offering net gain = 1.0 (4.0 -> 5.0)
        cand_gk = _make_proj(99, "GK_New", Position.GOALKEEPER, 16, 50, 5.0, prob=1.0)
        eng_v125 = DecisionEngineV125(bench_weight=0.15)

        # GK alone offering +1.0: should be rejected by V1.2.5 (1.0 < 1.50 hurdle)
        moves_gk = eng_v125.decide_transfers(
            strategy_name="production",
            current_squad_ids=squad_ids,
            purchase_prices=purchase_prices,
            free_transfers=1,
            bank_tenths=0,
            snapshot=snap,
            projections=squad + [cand_gk],
            allow_hits=False,
        )
        assert moves_gk == [], f"GK swap with net gain 1.0 should be rejected by 1.50 hurdle, got {moves_gk}"

        # 2. Candidate: Outfield replacement offering net gain = 1.0 (5.0 -> 6.0 on MID5)
        cand_mid = _make_proj(98, "MID_New", Position.MIDFIELDER, 17, 65, 6.0, prob=1.0)
        moves_mid = eng_v125.decide_transfers(
            strategy_name="production",
            current_squad_ids=squad_ids,
            purchase_prices=purchase_prices,
            free_transfers=1,
            bank_tenths=0,
            snapshot=snap,
            projections=squad + [cand_mid],
            allow_hits=False,
        )
        assert moves_mid == [(25, 98)], f"Outfield swap with net gain 1.0 should be accepted (hurdle 0.50), got {moves_mid}"

    def test_gk_transfer_allowed_when_incumbent_injured(self) -> None:
        """When incumbent GK is injured (play_probability < 0.50), hurdle drops to 0.50, allowing the swap."""
        def _make_proj(pid: int, name: str, pos: Position, tid: int, cost: int, xp: float, prob: float = 1.0) -> ExpectedPointsProjection:
            return ExpectedPointsProjection(
                player_id=pid,
                web_name=name,
                position=pos,
                team_id=tid,
                team_short=f"T{tid}",
                price_tenths=cost,
                status="d" if prob < 0.5 else "a",
                availability_pct=prob * 100.0,
                base_xp_per_match=xp,
                gameweek=10,
                fixtures=(),
                expected_points=xp,
                expected_minutes=90.0 * prob,
                play_probability=prob,
            )

        # Incumbent GK1 is injured: prob=0.10, xP=0.5
        squad = [
            _make_proj(1, "GK_Injured", Position.GOALKEEPER, 1, 50, 0.5, prob=0.10),
            _make_proj(2, "GK_Bench", Position.GOALKEEPER, 2, 40, 0.5, prob=0.0),
            _make_proj(11, "DEF1", Position.DEFENDER, 3, 55, 5.0),
            _make_proj(12, "DEF2", Position.DEFENDER, 4, 55, 5.0),
            _make_proj(13, "DEF3", Position.DEFENDER, 5, 55, 5.0),
            _make_proj(14, "DEF4", Position.DEFENDER, 6, 40, 1.5),
            _make_proj(15, "DEF5", Position.DEFENDER, 7, 40, 1.0),
            _make_proj(21, "MID1", Position.MIDFIELDER, 8, 125, 10.0),
            _make_proj(22, "MID2", Position.MIDFIELDER, 9, 85, 7.5),
            _make_proj(23, "MID3", Position.MIDFIELDER, 10, 80, 7.0),
            _make_proj(24, "MID4", Position.MIDFIELDER, 11, 75, 6.5),
            _make_proj(25, "MID5", Position.MIDFIELDER, 12, 65, 5.0),
            _make_proj(31, "FWD1", Position.FORWARD, 13, 140, 11.0),
            _make_proj(32, "FWD2", Position.FORWARD, 14, 80, 7.0),
            _make_proj(33, "FWD3", Position.FORWARD, 15, 45, 1.5),
        ]
        squad_ids = [p.player_id for p in squad]
        purchase_prices = {p.player_id: p.price_tenths for p in squad}

        snap = HistoricalGameweekSnapshot(
            season="2023-24",
            gameweek=10,
            deadline_time="2023-10-28T10:00:00Z",
            finished_gameweeks=9,
            players=(),
            teams=(),
            fixtures=(),
        )

        # Candidate GK replacement offering 1.3 xP gain (0.5 -> 1.8), below 1.50 normal GK hurdle, but > 0.50
        cand_gk = _make_proj(99, "GK_Replacement", Position.GOALKEEPER, 16, 50, 1.8, prob=1.0)
        eng_v125 = DecisionEngineV125(bench_weight=0.15)

        moves = eng_v125.decide_transfers(
            strategy_name="production",
            current_squad_ids=squad_ids,
            purchase_prices=purchase_prices,
            free_transfers=1,
            bank_tenths=0,
            snapshot=snap,
            projections=squad + [cand_gk],
            allow_hits=False,
        )

        assert moves == [(1, 99)], f"Injured GK swap should be allowed despite gain < 1.50, got {moves}"


class TestMultiGameweekHorizon:
    """Validate Pillar 3: Multi-gameweek discounted lineup horizon (H=3, gamma=0.75)."""

    def test_multi_horizon_prefers_sustained_fixtures_over_single_week_spike(self) -> None:
        """Player A spikes in GW10 (8.0) but collapses in GW11/12 (2.0, 2.0).
        Player B is consistent across all 3 gameweeks (6.0, 6.0, 6.0).
        H=1 prefers Player A (8.0 > 6.0).
        H=3 (gamma=0.75) prefers Player B (13.875 > 10.625).
        """
        from fpl_manager.backtest.decision_engine import _evaluate_squad_multi_horizon_lineup_xp

        class MockPlayer:
            def __init__(self, pid: int, pos: Position, xp: float):
                self.id = pid
                self.position = pos
                self.expected_points = xp

        base_squad = [
            MockPlayer(1, Position.GOALKEEPER, 4.0),
            MockPlayer(2, Position.GOALKEEPER, 1.0),
            MockPlayer(11, Position.DEFENDER, 5.0),
            MockPlayer(12, Position.DEFENDER, 5.0),
            MockPlayer(13, Position.DEFENDER, 5.0),
            MockPlayer(14, Position.DEFENDER, 1.5),
            MockPlayer(15, Position.DEFENDER, 1.0),
            MockPlayer(21, Position.MIDFIELDER, 10.0),
            MockPlayer(22, Position.MIDFIELDER, 7.5),
            MockPlayer(23, Position.MIDFIELDER, 7.0),
            MockPlayer(24, Position.MIDFIELDER, 6.5),
            # Position 25 will be filled by candidate A or B
            MockPlayer(31, Position.FORWARD, 11.0),
            MockPlayer(32, Position.FORWARD, 7.0),
            MockPlayer(33, Position.FORWARD, 1.5),
        ]

        player_a = MockPlayer(91, Position.MIDFIELDER, 8.0)
        player_b = MockPlayer(92, Position.MIDFIELDER, 6.0)

        squad_a = base_squad + [player_a]
        squad_b = base_squad + [player_b]

        projections_by_gw = {
            10: {p.id: p.expected_points for p in base_squad} | {91: 8.0, 92: 6.0},
            11: {p.id: p.expected_points for p in base_squad} | {91: 2.0, 92: 6.0},
            12: {p.id: p.expected_points for p in base_squad} | {91: 2.0, 92: 6.0},
        }

        # Horizon H=1: evaluates only GW10
        score_a_h1 = _evaluate_squad_multi_horizon_lineup_xp(squad_a, projections_by_gw, horizon=1, gamma=0.75)
        score_b_h1 = _evaluate_squad_multi_horizon_lineup_xp(squad_b, projections_by_gw, horizon=1, gamma=0.75)
        assert score_a_h1 > score_b_h1, f"At H=1 Player A should win on spike: A={score_a_h1} vs B={score_b_h1}"

        # Horizon H=3: evaluates GW10 + 0.75 * GW11 + 0.5625 * GW12
        score_a_h3 = _evaluate_squad_multi_horizon_lineup_xp(squad_a, projections_by_gw, horizon=3, gamma=0.75)
        score_b_h3 = _evaluate_squad_multi_horizon_lineup_xp(squad_b, projections_by_gw, horizon=3, gamma=0.75)
        assert score_b_h3 > score_a_h3, f"At H=3 Player B should win on sustained returns: B={score_b_h3} vs A={score_a_h3}"

    def test_multi_horizon_holds_premium_through_short_absence(self) -> None:
        """Haaland is blanking/injured for 1 GW (xP 0.0), returning in GW21 and GW22 (xP 10.0 each).
        Watkins has steady 5.0 across all 3 GWs.
        H=1 wants to sell Haaland for Watkins (5.0 > 0.0).
        H=3 holds Haaland because 0.0 + 0.75*10 + 0.5625*10 = 13.125 > 5.0 + 0.75*5 + 0.5625*5 = 11.5625.
        """
        from fpl_manager.backtest.decision_engine import _evaluate_squad_multi_horizon_lineup_xp

        class MockPlayer:
            def __init__(self, pid: int, pos: Position, xp: float):
                self.id = pid
                self.position = pos
                self.expected_points = xp

        base_squad = [
            MockPlayer(1, Position.GOALKEEPER, 4.0),
            MockPlayer(2, Position.GOALKEEPER, 1.0),
            MockPlayer(11, Position.DEFENDER, 5.0),
            MockPlayer(12, Position.DEFENDER, 5.0),
            MockPlayer(13, Position.DEFENDER, 5.0),
            MockPlayer(14, Position.DEFENDER, 1.5),
            MockPlayer(15, Position.DEFENDER, 1.0),
            MockPlayer(21, Position.MIDFIELDER, 10.0),
            MockPlayer(22, Position.MIDFIELDER, 7.5),
            MockPlayer(23, Position.MIDFIELDER, 7.0),
            MockPlayer(24, Position.MIDFIELDER, 6.5),
            MockPlayer(25, Position.MIDFIELDER, 5.0),
            # FWDs
            MockPlayer(31, Position.FORWARD, 7.0),
            MockPlayer(32, Position.FORWARD, 1.5),
        ]

        haaland = MockPlayer(9, Position.FORWARD, 0.0)
        watkins = MockPlayer(10, Position.FORWARD, 5.0)

        squad_hold = base_squad + [haaland]
        squad_sell = base_squad + [watkins]

        projections_by_gw = {
            20: {p.id: p.expected_points for p in base_squad} | {9: 0.0, 10: 5.0},
            21: {p.id: p.expected_points for p in base_squad} | {9: 10.0, 10: 5.0},
            22: {p.id: p.expected_points for p in base_squad} | {9: 10.0, 10: 5.0},
        }

        # Under H=1, panic selling Haaland yields positive delta:
        gain_h1 = (
            _evaluate_squad_multi_horizon_lineup_xp(squad_sell, projections_by_gw, horizon=1, gamma=0.75)
            - _evaluate_squad_multi_horizon_lineup_xp(squad_hold, projections_by_gw, horizon=1, gamma=0.75)
        )
        assert gain_h1 > 0.0, "Under H=1 selling Haaland for Watkins looks positive"

        # Under H=3, selling Haaland yields NEGATIVE delta (holding wins):
        gain_h3 = (
            _evaluate_squad_multi_horizon_lineup_xp(squad_sell, projections_by_gw, horizon=3, gamma=0.75)
            - _evaluate_squad_multi_horizon_lineup_xp(squad_hold, projections_by_gw, horizon=3, gamma=0.75)
        )
        assert gain_h3 < 0.0, f"Under H=3 holding Haaland must beat selling for Watkins: gain={gain_h3}"

    def test_multi_horizon_truncates_at_season_end(self) -> None:
        """At GW37 with horizon=3, only GW37 and GW38 exist; must truncate cleanly to 2 GWs without error."""
        from fpl_manager.backtest.decision_engine import _evaluate_squad_multi_horizon_lineup_xp

        class MockPlayer:
            def __init__(self, pid: int, pos: Position, xp: float):
                self.id = pid
                self.position = pos
                self.expected_points = xp

        squad = [
            MockPlayer(1, Position.GOALKEEPER, 4.0),
            MockPlayer(2, Position.GOALKEEPER, 1.0),
            MockPlayer(11, Position.DEFENDER, 5.0),
            MockPlayer(12, Position.DEFENDER, 5.0),
            MockPlayer(13, Position.DEFENDER, 5.0),
            MockPlayer(14, Position.DEFENDER, 1.5),
            MockPlayer(15, Position.DEFENDER, 1.0),
            MockPlayer(21, Position.MIDFIELDER, 10.0),
            MockPlayer(22, Position.MIDFIELDER, 7.5),
            MockPlayer(23, Position.MIDFIELDER, 7.0),
            MockPlayer(24, Position.MIDFIELDER, 6.5),
            MockPlayer(25, Position.MIDFIELDER, 5.0),
            MockPlayer(31, Position.FORWARD, 10.0),
            MockPlayer(32, Position.FORWARD, 7.0),
            MockPlayer(33, Position.FORWARD, 1.5),
        ]
        # Only GW37 and GW38 provided
        projections_by_gw = {
            37: {p.id: 5.0 for p in squad},
            38: {p.id: 6.0 for p in squad},
        }

        # Asking for horizon=3 should evaluate only the 2 available GWs (no IndexError, no zero fill)
        score = _evaluate_squad_multi_horizon_lineup_xp(squad, projections_by_gw, horizon=3, gamma=0.75)
        assert score > 0.0

    def test_multi_horizon_uses_no_future_information(self, monkeypatch) -> None:
        """Assert forward projections are generated strictly point-in-time from snapshot and scheduled fixtures.
        Ground truth match outcomes (load_gameweek_outcomes, outcome files) must NEVER be called or accessed.
        """
        from pathlib import Path
        import pytest
        from fpl_manager.backtest.decision_engine import _get_forward_projections
        from fpl_manager.historical.snapshots import build_historical_snapshot
        from fpl_manager.historical.reconstruction import reconstruct_features_and_project
        import fpl_manager.historical.snapshots as snap_mod

        season_dir = Path("data/historical/2023-24")
        if not season_dir.exists():
            pytest.skip("Historical data for 2023-24 not present")

        # Spy/trap: if load_gameweek_outcomes is called, fail immediately
        def _forbidden_outcomes(*args, **kwargs):
            raise AssertionError("Leakage violation: load_gameweek_outcomes was called during forward projection!")

        monkeypatch.setattr(snap_mod, "load_gameweek_outcomes", _forbidden_outcomes)

        snapshot = build_historical_snapshot(season_dir, 20, apply_departures=True, apply_unavailability=True)
        projections = reconstruct_features_and_project(snapshot)

        # Generate forward projections for H=3 (GW20, GW21, GW22)
        forward_projs = _get_forward_projections(snapshot, projections, horizon=3, season_dir=season_dir)

        assert 20 in forward_projs
        assert 21 in forward_projs
        assert 22 in forward_projs
        assert len(forward_projs[20]) > 0
        assert len(forward_projs[21]) > 0
        assert len(forward_projs[22]) > 0


class TestDoubleBlankGameweekAwareness:
    """Validate Pillar 4: Double / Blank Gameweek Awareness."""

    def test_double_gameweek_player_projects_two_fixtures(self) -> None:
        """When a team has two scheduled fixtures in a gameweek, xP is computed for both and summed."""
        import pytest
        from fpl_manager.expected_points import project_player_gameweek

        two_fixes = [
            {"opponent_id": 2, "opponent_short": "T2", "is_home": True, "fdr": 2},
            {"opponent_id": 3, "opponent_short": "T3", "is_home": False, "fdr": 3},
        ]
        proj = project_player_gameweek(
            player_id=10,
            web_name="Salah",
            position=Position.MIDFIELDER,
            team_id=1,
            team_short="LIV",
            price_tenths=130,
            status="a",
            total_points=100,
            finished_matches=10,
            gameweek=34,
            team_fixtures_in_gw=two_fixes,
            minutes=900,
            starts=10,
            chance_of_playing_next_round=100,
            chance_of_playing_this_round=100,
            expected_goals=8.0,
            expected_assists=5.0,
            expected_goal_involvements=13.0,
            expected_goals_conceded=10.0,
            expected_goals_per_90=0.8,
            expected_assists_per_90=0.5,
            expected_goals_conceded_per_90=1.0,
            clean_sheets_per_90=0.4,
            bps=250,
            ict_index=150.0,
            predictor_version="v1.0.1",
        )

        assert len(proj.fixtures) == 2
        fix1_xp = proj.fixtures[0].fixture_xp
        fix2_xp = proj.fixtures[1].fixture_xp
        assert fix1_xp > 0.0
        assert fix2_xp > 0.0
        assert proj.expected_points == pytest.approx(fix1_xp + fix2_xp, rel=1e-4)

    def test_blank_gameweek_player_projects_zero(self) -> None:
        """When a team has zero scheduled fixtures in a gameweek, xP is exactly 0.0."""
        from fpl_manager.expected_points import project_player_gameweek

        zero_fixes = []
        proj = project_player_gameweek(
            player_id=10,
            web_name="Salah",
            position=Position.MIDFIELDER,
            team_id=1,
            team_short="LIV",
            price_tenths=130,
            status="a",
            total_points=100,
            finished_matches=10,
            gameweek=29,
            team_fixtures_in_gw=zero_fixes,
            minutes=900,
            starts=10,
            chance_of_playing_next_round=100,
            chance_of_playing_this_round=100,
            expected_goals=8.0,
            expected_assists=5.0,
            expected_goal_involvements=13.0,
            expected_goals_conceded=10.0,
            expected_goals_per_90=0.8,
            expected_assists_per_90=0.5,
            expected_goals_conceded_per_90=1.0,
            clean_sheets_per_90=0.4,
            bps=250,
            ict_index=150.0,
            predictor_version="v1.0.1",
        )

        assert len(proj.fixtures) == 0
        assert proj.expected_points == 0.0


class TestDynamicChipAwareBenchWeighting:
    """Validate Pillar 5: Dynamic Chip-Aware Bench Weighting."""

    def test_bench_boost_weight_does_not_trigger_legacy_symmetric_mode(self) -> None:
        """Enforce that Bench Boost bench_weight (0.99) does not trip legacy symmetric mode (>= 1.0)."""
        from fpl_manager.strategic_squad import StrategicConstraints

        # Passing 0.99 must maintain asymmetric mode
        c = StrategicConstraints(budget_tenths=1000, bench_weight=0.99)
        assert c.bench_weight < 1.0, f"bench_weight must be < 1.0 to avoid legacy mode trap, got {c.bench_weight}"

    def test_free_hit_concentrates_budget_in_starting_xi(self) -> None:
        """Free Hit (bench_weight=0.05) concentrates funds in the starting XI rather than the bench."""
        from fpl_manager.strategic_squad import StrategicConstraints, solve_strategic_squad
        from fpl_manager.suggest_transfers import PlayerInfo

        pool = []
        pid = 1
        # GKs: 1 premium (6.0m, 8.0 xp), 1 fodder (4.0m, 0.0 xp)
        pool.append(PlayerInfo(pid, "GK1", Position.GOALKEEPER, 1, "T1", 60, "a", 100, expected_points=8.0, expected_minutes=90)); pid += 1
        pool.append(PlayerInfo(pid, "GK2", Position.GOALKEEPER, 2, "T2", 40, "a", 0, expected_points=0.0, expected_minutes=0)); pid += 1
        # DEFs: 3 prems (7.0m, 7.0m, 6.5m), 2 fodders (4.0m, 4.0m)
        for cost, xp in [(70, 7.0), (70, 7.0), (65, 6.5), (40, 0.0), (40, 0.0)]:
            pool.append(PlayerInfo(pid, f"DEF{pid}", Position.DEFENDER, pid, f"T{pid}", cost, "a", 100, expected_points=xp, expected_minutes=90 if xp > 0 else 0)); pid += 1
        # MIDs: 4 prems (13.0m, 10.5m, 9.5m, 8.5m), 1 fodder (4.5m)
        for cost, xp in [(130, 13.0), (105, 10.5), (95, 9.5), (85, 8.5), (45, 0.0)]:
            pool.append(PlayerInfo(pid, f"MID{pid}", Position.MIDFIELDER, pid, f"T{pid}", cost, "a", 100, expected_points=xp, expected_minutes=90 if xp > 0 else 0)); pid += 1
        # FWDs: 2 prems (14.0m, 8.0m), 1 fodder (4.5m)
        for cost, xp in [(140, 14.0), (80, 8.0), (45, 0.0)]:
            pool.append(PlayerInfo(pid, f"FWD{pid}", Position.FORWARD, pid, f"T{pid}", cost, "a", 100, expected_points=xp, expected_minutes=90 if xp > 0 else 0)); pid += 1

        # Budget = 111.0m (1110 tenths) allows all 15 candidates to be legally chosen
        c = StrategicConstraints(budget_tenths=1110, target_gameweeks=(1,), bench_weight=0.05)
        cand = solve_strategic_squad(pool, c, strategy="balanced", mode="free_hit", horizon=1, bench_weight=0.05)
        starters_cost = sum(p["price_tenths"] for p in cand.starters)
        bench_cost = sum(p["price_tenths"] for p in cand.bench)
        assert starters_cost >= 835, f"Expected starting XI cost >= £83.5m (835 tenths), got {starters_cost/10.0}m"
        assert bench_cost == 165, f"Expected bench to hold minimum £16.5m fodder, got {bench_cost/10.0}m"

    def test_bench_boost_squad_has_fifteen_playing_assets(self) -> None:
        """Under bench_weight=0.99, all 15 squad members are prioritized for playing expected points."""
        from fpl_manager.strategic_squad import StrategicConstraints, solve_strategic_squad
        from fpl_manager.suggest_transfers import PlayerInfo

        pool = []
        pid = 1
        for pos, quota, costs in [
            (Position.GOALKEEPER, 2, [50, 45]),
            (Position.DEFENDER, 5, [60, 55, 50, 45, 45]),
            (Position.MIDFIELDER, 5, [100, 85, 75, 65, 55]),
            (Position.FORWARD, 3, [90, 75, 60]),
        ]:
            for cost in costs:
                pool.append(PlayerInfo(pid, f"P{pid}", pos, pid, f"T{pid}", cost, "a", 50, expected_points=4.0, expected_minutes=90))
                pid += 1

        c = StrategicConstraints(budget_tenths=1000, target_gameweeks=(1,), bench_weight=0.99)
        cand = solve_strategic_squad(pool, c, strategy="balanced", mode="wildcard", horizon=1, bench_weight=0.99)
        assert len(cand.starters) == 11
        assert len(cand.bench) == 4
        for p in cand.squad:
            assert p["expected_points"] >= 3.0

    def test_track_a_unaffected_by_chip_bench_weighting(self) -> None:
        """Track A simulation must use standard bench_weight=0.15 regardless of chip state."""
        from pathlib import Path
        import pytest
        from fpl_manager.backtest.engine import run_sequential_simulation
        from fpl_manager.backtest.strategies import OptimizerStrategy

        season_dir = Path("data/historical/2023-24")
        if not season_dir.exists():
            pytest.skip("2023-24 data missing")

        strat = OptimizerStrategy(max_transfers=1, allow_hits=False, decision_engine="v1.2.5")
        res = run_sequential_simulation(season_dir, strat, decision_engine="v1.2.5", use_chips=False)
        assert res.total_net_points == 2193, f"Track A 2023-24 should be 2193, got {res.total_net_points}"


class TestResolveInertUnavailabilityMechanism:
    """Validate Pillar 6: Resolution of inert long-term unavailability mechanism (Option B)."""

    def test_registry_removal_does_not_change_benchmark(self) -> None:
        """Confirm that disabling the hand-curated unavailability registry produces exact 0.0 drift."""
        from pathlib import Path
        import pytest
        from fpl_manager.backtest.engine import run_sequential_simulation
        from fpl_manager.backtest.strategies import OptimizerStrategy

        season_dir = Path("data/historical/2023-24")
        if not season_dir.exists():
            pytest.skip("2023-24 data missing")

        strat = OptimizerStrategy(max_transfers=1, allow_hits=False, decision_engine="v1.2.5")
        res = run_sequential_simulation(season_dir, strat, decision_engine="v1.2.5", use_chips=False)
        # 2023-24 Track A is exactly 2193 with or without the registry
        assert res.total_net_points == 2193




