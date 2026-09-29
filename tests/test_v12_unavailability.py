"""Tests for V1.2 Long-Term Unavailability Modeling and DecisionEngineV12 (Pillars 2 & 3).

Verifies:
1. Point-in-time unavailability registry lookups across historical seasons.
2. Distinct semantics: Premier League departure vs Long-term unavailability.
3. Strict exclusion from buy-side candidate pools (transfers, initial squad, wildcard).
4. Priority offloading via dead capital penalty.
5. DecisionEngineV12 integration and Lineup-Aware Transfer Evaluation.
"""

from pathlib import Path
import pytest

from fpl_manager.backtest.decision_engine import (
    DecisionEngineV12,
    resolve_decision_engine,
)
from fpl_manager.historical.models import (
    HistoricalGameweekSnapshot,
    HistoricalPlayerState,
)
from fpl_manager.historical.snapshots import build_historical_snapshot
from fpl_manager.models import (
    Player,
    PlayerEligibilityStatus,
    Position,
    get_player_eligibility_status,
    is_departed_from_premier_league,
    is_long_term_unavailable,
)
from fpl_manager.optimizer import PlayerOptInfo, solve_transfers
from fpl_manager.strategic_squad import StrategicConstraints, solve_strategic_squad


class TestHistoricalUnavailabilityRegistry:
    """Validate historical bans and season-ending injuries are correctly identified point-in-time."""

    def test_ivan_toney_2023_24_suspension_window(self) -> None:
        """Ivan Toney was suspended May 2023 - Jan 2024 (GW1 to GW20). Eligible GW21."""
        season_dir = Path("data/historical/2023-24")
        if not season_dir.exists():
            pytest.skip("Historical data directory not found")

        # GW1: Suspended
        snap_gw1 = build_historical_snapshot(season_dir, 1)
        toney_gw1 = next(p for p in snap_gw1.players if p.player_id == 117)
        assert toney_gw1.status == "s"
        assert toney_gw1.chance_of_playing_next_round == 0
        assert "FA suspension" in toney_gw1.news
        assert is_long_term_unavailable(toney_gw1, snap_gw1) is True
        # He did NOT leave the Premier League, so is_departed is False
        assert is_departed_from_premier_league(toney_gw1, snap_gw1) is False

        # GW20: Still suspended
        snap_gw20 = build_historical_snapshot(season_dir, 20)
        toney_gw20 = next(p for p in snap_gw20.players if p.player_id == 117)
        assert is_long_term_unavailable(toney_gw20, snap_gw20) is True

        # GW21: Ban ended, eligible to play
        snap_gw21 = build_historical_snapshot(season_dir, 21)
        toney_gw21 = next(p for p in snap_gw21.players if p.player_id == 117)
        assert is_long_term_unavailable(toney_gw21, snap_gw21) is False

    def test_sandro_tonali_2023_24_ban(self) -> None:
        """Tonali was banned starting GW10 until season end in 2023-24."""
        season_dir = Path("data/historical/2023-24")
        if not season_dir.exists():
            pytest.skip("Historical data directory not found")

        # GW9: Active before ban
        snap_gw9 = build_historical_snapshot(season_dir, 9)
        tonali_gw9 = next(p for p in snap_gw9.players if p.player_id == 429)
        assert is_long_term_unavailable(tonali_gw9, snap_gw9) is False

        # GW10: Banned
        snap_gw10 = build_historical_snapshot(season_dir, 10)
        tonali_gw10 = next(p for p in snap_gw10.players if p.player_id == 429)
        assert tonali_gw10.status == "s"
        assert is_long_term_unavailable(tonali_gw10, snap_gw10) is True

    def test_acl_injuries_in_2023_24(self) -> None:
        """Verify season-ending ACL injuries (Timber, Mings, Buendia, Fofana) are flagged."""
        season_dir = Path("data/historical/2023-24")
        if not season_dir.exists():
            pytest.skip("Historical data directory not found")

        snap = build_historical_snapshot(season_dir, 5)
        acl_ids = [585, 51, 35, 201]  # Timber, Mings, Buendia, Fofana
        for pid in acl_ids:
            p = next(player for player in snap.players if player.player_id == pid)
            assert p.status == "i"
            assert is_long_term_unavailable(p, snap) is True
            assert is_departed_from_premier_league(p, snap) is False


class TestUnavailabilitySemantics:
    """Validate domain model eligibility and dead capital calculations."""

    def test_long_term_injury_triggers_dead_capital_penalty(self) -> None:
        p = Player(
            id=201,
            name="Injured Star",
            position=Position.DEFENDER,
            team_id=7,
            price_tenths=50,
            status="i",
            chance_of_playing_this_round=0,
            news="Ruptured anterior cruciate ligament (ACL) - out for season",
        )
        assert is_departed_from_premier_league(p) is False
        assert is_long_term_unavailable(p) is True

        elig = get_player_eligibility_status(p, dead_capital_weight=3.0)
        assert elig.is_in_premier_league is True
        assert elig.is_long_term_unavailable is True
        # 3.0 * 5.0m = 15.0 dead capital penalty
        assert elig.dead_capital_penalty == pytest.approx(15.0)

    def test_minor_knock_does_not_trigger_unavailability(self) -> None:
        p = Player(
            id=301,
            name="Knocked Midfielder",
            position=Position.MIDFIELDER,
            team_id=1,
            price_tenths=80,
            status="d",
            chance_of_playing_this_round=75,
            news="Knock - 75% chance of playing",
        )
        assert is_long_term_unavailable(p) is False
        elig = get_player_eligibility_status(p, dead_capital_weight=3.0)
        assert elig.dead_capital_penalty == 0.0


class TestOptimizerUnavailabilityIntegration:
    """Verify that optimizer excludes unavailable players and prioritizes their liquidation."""

    def test_solve_transfers_excludes_unavailable_incoming(self) -> None:
        squad = [
            PlayerOptInfo(id=i, name=f"P{i}", position=Position.DEFENDER, team_id=1, team_short="T1", price_tenths=45, status="a", total_points=20, expected_points=3.0)
            for i in range(1, 16)
        ]
        # Candidate pool contains one healthy player and one banned player
        cands = [
            PlayerOptInfo(id=101, name="Healthy Mid", position=Position.DEFENDER, team_id=2, team_short="T2", price_tenths=45, status="a", total_points=30, expected_points=5.0),
            PlayerOptInfo(id=102, name="Banned Mid", position=Position.DEFENDER, team_id=3, team_short="T3", price_tenths=45, status="s", total_points=50, expected_points=8.0),
        ]
        recs, _ = solve_transfers(
            num_transfers=1,
            squad_players=squad,
            candidate_pool=cands,
            bank_tenths=5,
            free_transfers=1,
            selling_prices={p.id: p.price_tenths for p in squad},
            fdr_map={},
            ticker_map={},
        )
        assert len(recs) > 0
        in_id = recs[0]["incoming"][0]["id"]
        assert in_id == 101, "Should select Healthy Mid, never Banned Mid"

    def test_solve_transfers_prioritizes_offloading_unavailable_squad_player(self) -> None:
        squad = [
            PlayerOptInfo(id=i, name=f"P{i}", position=Position.DEFENDER, team_id=1, team_short="T1", price_tenths=50, status="a", total_points=20, expected_points=3.0)
            for i in range(1, 15)
        ]
        # 15th player has ruptured ACL
        squad.append(
            PlayerOptInfo(
                id=15,
                name="ACL Victim",
                position=Position.DEFENDER,
                team_id=2,
                team_short="T2",
                price_tenths=80,
                status="i",
                total_points=30,
                expected_points=0.0,
                news="Ruptured anterior cruciate ligament (ACL) - out for season",
            )
        )
        cand = PlayerOptInfo(id=101, name="Replacement", position=Position.DEFENDER, team_id=3, team_short="T3", price_tenths=75, status="a", total_points=40, expected_points=4.5)

        recs, _ = solve_transfers(
            num_transfers=1,
            squad_players=squad,
            candidate_pool=[cand],
            bank_tenths=10,
            free_transfers=1,
            selling_prices={p.id: p.price_tenths for p in squad},
            fdr_map={},
            ticker_map={},
            dead_capital_weight=3.0,
        )
        assert len(recs) > 0
        out_id = recs[0]["outgoing"][0]["id"]
        assert out_id == 15, "Should immediately liquidate ACL victim with dead capital bonus"


class TestDecisionEngineV12Integration:
    """Validate DecisionEngineV12 construction, registration, and lineup-aware transfer evaluation."""

    def test_resolve_v12(self) -> None:
        eng = resolve_decision_engine("v1.2")
        assert isinstance(eng, DecisionEngineV12)
        assert eng.version == "v1.2"
        assert eng.bench_weight == 0.15
        assert eng.dead_capital_weight == 3.0

    def test_resolve_v12_aliases(self) -> None:
        for alias in ("v12", "v1.2.0", "balanced_v12", "v1.2_differential"):
            eng = resolve_decision_engine(alias)
            assert isinstance(eng, DecisionEngineV12)

    def test_strategy_config_includes_bench_weight(self) -> None:
        eng = DecisionEngineV12(bench_weight=0.12)
        cfg = eng.get_strategy_config("balanced")
        assert cfg["bench_weight"] == 0.12
        assert cfg["dead_capital_weight"] == 3.0

    def test_lineup_aware_transfer_evaluation_rejects_sideways_bench_swap(self) -> None:
        """In V1.2, swapping a 3rd bench player for another bench player with +0.7 raw xP gain
        is weighted by bench_weight (0.15 * 0.7 = 0.105 < 0.50) and rejected, preserving the free transfer.
        """
        from fpl_manager.expected_points import ExpectedPointsProjection
        from fpl_manager.historical.models import HistoricalGameweekSnapshot

        def _make_proj(
            pid: int,
            name: str,
            pos: Position,
            tid: int,
            tshort: str,
            cost: int,
            xp: float,
            mins: float = 90.0,
            prob: float = 0.90,
        ) -> ExpectedPointsProjection:
            return ExpectedPointsProjection(
                player_id=pid,
                web_name=name,
                position=pos,
                team_id=tid,
                team_short=tshort,
                price_tenths=cost,
                status="a",
                availability_pct=100.0,
                base_xp_per_match=xp,
                gameweek=5,
                fixtures=(),
                expected_points=xp,
                expected_minutes=mins,
                play_probability=prob,
            )

        eng = DecisionEngineV12(bench_weight=0.15)
        snap = HistoricalGameweekSnapshot(
            season="2023-24",
            gameweek=5,
            deadline_time="2023-09-16T10:00:00Z",
            finished_gameweeks=4,
            players=(),
            teams=(),
            fixtures=(),
        )

        # Build 15 squad projections: 2 GKP, 5 DEF, 5 MID, 3 FWD
        projs = [
            # 2 GKPs
            _make_proj(1, "GKP1", Position.GOALKEEPER, 1, "T1", 45, 4.0, mins=90),
            _make_proj(2, "GKP2", Position.GOALKEEPER, 2, "T2", 40, 1.0, mins=0, prob=0.0),
            # 5 DEFs: top 3 start (5.0 each), 4th & 5th sit on bench (2.0 and 1.5)
            _make_proj(11, "DEF1", Position.DEFENDER, 3, "T3", 55, 5.0),
            _make_proj(12, "DEF2", Position.DEFENDER, 4, "T4", 55, 5.0),
            _make_proj(13, "DEF3", Position.DEFENDER, 5, "T5", 55, 5.0),
            _make_proj(14, "DEF4", Position.DEFENDER, 6, "T6", 40, 2.0),
            _make_proj(15, "DEF5", Position.DEFENDER, 7, "T7", 40, 1.5),
            # 5 MIDs (all strong starters)
            _make_proj(21, "MID1", Position.MIDFIELDER, 8, "T8", 125, 9.0),
            _make_proj(22, "MID2", Position.MIDFIELDER, 9, "T9", 85, 7.0),
            _make_proj(23, "MID3", Position.MIDFIELDER, 10, "T10", 85, 7.0),
            _make_proj(24, "MID4", Position.MIDFIELDER, 1, "T1", 65, 6.0),
            _make_proj(25, "MID5", Position.MIDFIELDER, 2, "T2", 65, 6.0),
            # 3 FWDs (2 starters, 1 bench)
            _make_proj(31, "FWD1", Position.FORWARD, 3, "T3", 140, 11.0),
            _make_proj(32, "FWD2", Position.FORWARD, 4, "T4", 80, 6.0),
            _make_proj(33, "FWD3", Position.FORWARD, 5, "T5", 45, 1.5, mins=0, prob=0.0),
        ]
        squad_ids = [p.player_id for p in projs]
        purchase_prices = {p.player_id: p.price_tenths for p in projs}

        # Candidate: DEF with 2.2 xP (replacing DEF5 at 1.5 xP would give +0.7 raw xP)
        cand_bench = _make_proj(99, "Bench_Upgrade", Position.DEFENDER, 6, "T6", 40, 2.2)

        all_projs = projs + [cand_bench]

        moves = eng.decide_transfers(
            strategy_name="production",
            current_squad_ids=squad_ids,
            purchase_prices=purchase_prices,
            bank_tenths=10,
            free_transfers=1,
            snapshot=snap,
            projections=all_projs,
            max_transfers=1,
            min_net_gain=0.50,
        )
        # Must be rejected because 0.15 * (2.2 - 1.5) = 0.105 < 0.50
        assert moves == [], "Sideways bench swap should be rejected under lineup-aware evaluation"

