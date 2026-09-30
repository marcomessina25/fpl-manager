"""Tests for V1.2 Long-Term Unavailability Modeling and DecisionEngineV12 (Pillars 2 & 3).

Verifies:
1. Point-in-time unavailability registry lookups across historical seasons.
2. Distinct semantics: Premier League departure vs Long-term unavailability.
3. Strict exclusion from buy-side candidate pools (transfers, initial squad, wildcard).
4. Priority offloading via dead capital penalty.
5. DecisionEngineV12 integration and Lineup-Aware Transfer Evaluation.
6. Issue 1 regression guard: the precomputed `is_long_term_unavailable` verdict survives the
   full snapshot -> ExpectedPointsProjection -> PlayerInfo -> PlayerOptInfo chain.
7. Issue 3 regression guard: objects carrying a precomputed verdict are immune to wall-clock
   ("now") drift - the verdict is point-in-time-correct and reproducible.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from fpl_manager import models as models_module
from fpl_manager.backtest.decision_engine import (
    DecisionEngineV12,
    resolve_decision_engine,
)
from fpl_manager.backtest.strategic_analysis import load_historical_strategic_players
from fpl_manager.historical.models import (
    HistoricalGameweekSnapshot,
    HistoricalPlayerState,
)
from fpl_manager.historical.reconstruction import reconstruct_features_and_project
from fpl_manager.historical.snapshots import build_historical_snapshot
from fpl_manager.models import (
    Player,
    PlayerEligibilityStatus,
    Position,
    evaluate_long_term_unavailable,
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
        snap_gw1 = build_historical_snapshot(season_dir, 1, apply_unavailability=True)
        toney_gw1 = next(p for p in snap_gw1.players if p.player_id == 117)
        assert toney_gw1.status == "s"
        assert toney_gw1.chance_of_playing_next_round == 0
        assert "FA suspension" in toney_gw1.news
        assert is_long_term_unavailable(toney_gw1, snap_gw1) is True
        # He did NOT leave the Premier League, so is_departed is False
        assert is_departed_from_premier_league(toney_gw1, snap_gw1) is False

        # GW20: Still suspended
        snap_gw20 = build_historical_snapshot(season_dir, 20, apply_unavailability=True)
        toney_gw20 = next(p for p in snap_gw20.players if p.player_id == 117)
        assert is_long_term_unavailable(toney_gw20, snap_gw20) is True

        # GW21: Ban ended, eligible to play
        snap_gw21 = build_historical_snapshot(season_dir, 21, apply_unavailability=True)
        toney_gw21 = next(p for p in snap_gw21.players if p.player_id == 117)
        assert is_long_term_unavailable(toney_gw21, snap_gw21) is False

    def test_sandro_tonali_2023_24_ban(self) -> None:
        """Tonali was banned starting GW10 until season end in 2023-24."""
        season_dir = Path("data/historical/2023-24")
        if not season_dir.exists():
            pytest.skip("Historical data directory not found")

        # GW9: Active before ban
        snap_gw9 = build_historical_snapshot(season_dir, 9, apply_unavailability=True)
        tonali_gw9 = next(p for p in snap_gw9.players if p.player_id == 429)
        assert is_long_term_unavailable(tonali_gw9, snap_gw9) is False

        # GW10: Banned
        snap_gw10 = build_historical_snapshot(season_dir, 10, apply_unavailability=True)
        tonali_gw10 = next(p for p in snap_gw10.players if p.player_id == 429)
        assert tonali_gw10.status == "s"
        assert is_long_term_unavailable(tonali_gw10, snap_gw10) is True

    def test_greenwood_2021_22_no_future_leakage(self) -> None:
        """Greenwood was suspended by his club on 30 Jan 2022, after the GW23 deadline
        (2022-01-21) and after he played in GW23. He must NOT be long-term-unavailable
        at the GW23 snapshot, and must be flagged from GW24 onward (start_gw fixed to 24).
        """
        season_dir = Path("data/historical/2021-22")
        if not season_dir.exists():
            pytest.skip("Historical data directory not found")

        snap_gw23 = build_historical_snapshot(season_dir, 23, apply_unavailability=True)
        greenwood_gw23 = next(p for p in snap_gw23.players if p.player_id == 289)
        assert is_long_term_unavailable(greenwood_gw23, snap_gw23) is False

        snap_gw24 = build_historical_snapshot(season_dir, 24, apply_unavailability=True)
        greenwood_gw24 = next(p for p in snap_gw24.players if p.player_id == 289)
        assert is_long_term_unavailable(greenwood_gw24, snap_gw24) is True

    def test_timber_and_mings_2023_24_no_future_leakage(self) -> None:
        """Timber and Mings both suffered their injuries on 12 Aug 2023, after the GW1
        deadline (2023-08-11), and both played in GW1. Neither must be long-term-unavailable
        at the GW1 snapshot; both must be flagged from GW2 onward (start_gw fixed to 2).
        """
        season_dir = Path("data/historical/2023-24")
        if not season_dir.exists():
            pytest.skip("Historical data directory not found")

        snap_gw1 = build_historical_snapshot(season_dir, 1, apply_unavailability=True)
        for pid in (585, 51):
            p_gw1 = next(p for p in snap_gw1.players if p.player_id == pid)
            assert is_long_term_unavailable(p_gw1, snap_gw1) is False

        snap_gw2 = build_historical_snapshot(season_dir, 2, apply_unavailability=True)
        for pid in (585, 51):
            p_gw2 = next(p for p in snap_gw2.players if p.player_id == pid)
            assert is_long_term_unavailable(p_gw2, snap_gw2) is True

    def test_acl_injuries_in_2023_24(self) -> None:
        """Verify season-ending ACL injuries (Timber, Mings, Buendia, Fofana) are flagged."""
        season_dir = Path("data/historical/2023-24")
        if not season_dir.exists():
            pytest.skip("Historical data directory not found")

        snap = build_historical_snapshot(season_dir, 5, apply_unavailability=True)
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

    def test_one_match_suspension_with_near_return_date_is_not_long_term(self) -> None:
        """A one-match ban with a return date within 35 days must NOT be long-term."""
        reference = datetime(2024, 1, 10, tzinfo=timezone.utc)
        return_date = reference + timedelta(days=7)
        news = f"Suspended until {return_date.day} {return_date.strftime('%b')}"
        p = Player(
            id=401,
            name="One Match Ban",
            position=Position.MIDFIELDER,
            team_id=2,
            price_tenths=60,
            status="s",
            chance_of_playing_this_round=0,
            news=news,
        )
        snap = HistoricalGameweekSnapshot(
            season="2023-24",
            gameweek=20,
            deadline_time=reference.isoformat().replace("+00:00", "Z"),
            finished_gameweeks=19,
            players=(),
            teams=(),
            fixtures=(),
        )
        assert is_long_term_unavailable(p, snap) is False

    def test_long_suspension_with_distant_return_date_is_long_term(self) -> None:
        """A ban with a return date more than 35 days away must be long-term."""
        reference = datetime(2024, 1, 10, tzinfo=timezone.utc)
        return_date = reference + timedelta(days=120)
        news = f"Suspended until {return_date.day} {return_date.strftime('%B')} {return_date.year}"
        p = Player(
            id=402,
            name="Long Ban",
            position=Position.MIDFIELDER,
            team_id=2,
            price_tenths=60,
            status="s",
            chance_of_playing_this_round=0,
            news=news,
        )
        snap = HistoricalGameweekSnapshot(
            season="2023-24",
            gameweek=20,
            deadline_time=reference.isoformat().replace("+00:00", "Z"),
            finished_gameweeks=19,
            players=(),
            teams=(),
            fixtures=(),
        )
        assert is_long_term_unavailable(p, snap) is True

    def test_suspended_status_with_no_news_is_not_long_term(self) -> None:
        """A bare 's' status with no news and no other signal is NOT long-term."""
        p = Player(
            id=403,
            name="Bare Suspension",
            position=Position.DEFENDER,
            team_id=3,
            price_tenths=45,
            status="s",
            chance_of_playing_this_round=0,
            news="",
        )
        assert is_long_term_unavailable(p) is False

    def test_acl_news_with_status_i_and_zero_chance_is_long_term(self) -> None:
        """Injury status with ACL keyword and zero chance of playing is long-term,
        even without a parseable return date."""
        p = Player(
            id=404,
            name="ACL Case",
            position=Position.DEFENDER,
            team_id=4,
            price_tenths=55,
            status="i",
            chance_of_playing_this_round=0,
            news="Ruptured ACL - surgery required",
        )
        assert is_long_term_unavailable(p) is True

    def test_long_ban_months_phrasing_is_long_term(self) -> None:
        """A disciplinary suspension described in months (without a parseable date) is long-term."""
        p = Player(
            id=405,
            name="Months Ban",
            position=Position.FORWARD,
            team_id=5,
            price_tenths=70,
            status="s",
            chance_of_playing_this_round=0,
            news="Handed an 8-month suspension by the FA",
        )
        assert is_long_term_unavailable(p) is True


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
        # 15th player has ruptured ACL. `is_long_term_unavailable` is set explicitly here because
        # PlayerOptInfo is a derived/opt-in object: since the V1.2 fix, its `news` text is no
        # longer the transport mechanism for this signal (see `is_long_term_unavailable` in
        # models.py) - production code computes this flag once at snapshot-build time and
        # carries it through explicitly, exactly as done here.
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
                is_long_term_unavailable=True,
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
        assert recs[0]["outgoing"][0]["is_unavailable"] is True
        assert recs[0]["dead_capital_bonus"] > 0, "Dead capital bonus must actually apply (Issue 1 regression guard)"

    def test_solve_transfers_short_suspension_gets_no_dead_capital_bonus(self) -> None:
        """A squad player serving a short (1-match) suspension is not dead capital:
        offloading them must NOT receive the dead capital bonus."""
        squad = [
            PlayerOptInfo(id=i, name=f"P{i}", position=Position.DEFENDER, team_id=1, team_short="T1", price_tenths=50, status="a", total_points=20, expected_points=3.0)
            for i in range(1, 15)
        ]
        # 15th player is serving a single-match disciplinary suspension (not long-term)
        squad.append(
            PlayerOptInfo(
                id=15,
                name="One Match Ban",
                position=Position.DEFENDER,
                team_id=2,
                team_short="T2",
                price_tenths=80,
                status="s",
                total_points=30,
                expected_points=0.0,
                news="One match violent conduct suspension",
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
        assert out_id == 15
        assert recs[0]["dead_capital_bonus"] == 0


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


class TestIssue1SignalWiringRegression:
    """Permanent regression guard for Issue 1: the long-term-unavailability verdict computed by
    `build_historical_snapshot` for a registry-flagged player must survive every hop of the
    production pipeline (raw snapshot -> ExpectedPointsProjection -> PlayerInfo -> PlayerOptInfo)
    without being silently dropped, so `DecisionEngineV12.decide_transfers`'s dead-capital gate
    (and `solve_transfers(dead_capital_weight=...)`) actually see it.
    """

    SEASON_DIR = Path("data/historical/2023-24")
    GAMEWEEK = 12
    # Registry player_ids active at GW12 in data/historical/unavailability_registry.json["2023-24"].
    REGISTRY_PLAYER_IDS = (117, 429, 585, 51, 35, 201)

    def test_flag_survives_snapshot_to_projection_to_player_info_to_opt_info(self) -> None:
        if not self.SEASON_DIR.exists():
            pytest.skip("Historical data directory not found")

        snapshot = build_historical_snapshot(self.SEASON_DIR, self.GAMEWEEK, apply_unavailability=True)
        raw_by_id = {p.player_id: p for p in snapshot.players}

        projections = reconstruct_features_and_project(snapshot, predictor_version="v1.0.1")
        proj_by_id = {p.player_id: p for p in projections}

        player_infos, _team_map = load_historical_strategic_players(
            self.SEASON_DIR, self.GAMEWEEK, apply_unavailability=True
        )
        info_by_id = {p.id: p for p in player_infos}

        for pid in self.REGISTRY_PLAYER_IDS:
            raw = raw_by_id[pid]
            proj = proj_by_id[pid]
            info = info_by_id[pid]

            # 1. Raw snapshot player carries the precomputed verdict.
            assert raw.is_long_term_unavailable is True, f"player {pid}: raw snapshot flag not set"

            # 2. ExpectedPointsProjection (historical/reconstruction.py) preserves it.
            assert proj.is_long_term_unavailable is True, f"player {pid}: projection dropped the flag"

            # 3. PlayerInfo (backtest/strategic_analysis.py) preserves it.
            assert info.is_long_term_unavailable is True, f"player {pid}: PlayerInfo dropped the flag"

            # 4. PlayerOptInfo, built exactly as DecisionEngineV12.decide_transfers builds it
            #    (backtest/decision_engine.py opt_map construction), preserves it.
            opt = PlayerOptInfo(
                id=proj.player_id,
                name=proj.web_name,
                position=proj.position,
                team_id=proj.team_id,
                team_short=proj.team_short,
                price_tenths=proj.price_tenths,
                status=proj.status,
                total_points=0,
                expected_points=proj.expected_points,
                expected_minutes=proj.expected_minutes,
                xp_floor=proj.xp_floor,
                xp_ceiling=proj.xp_ceiling,
                standard_deviation=proj.standard_deviation,
                is_long_term_unavailable=getattr(proj, "is_long_term_unavailable", False),
            )
            assert opt.is_long_term_unavailable is True, f"player {pid}: PlayerOptInfo dropped the flag"

            # 5. The module-level predicate, and DecisionEngineV12's dead-capital gate, both see it.
            assert is_long_term_unavailable(opt, snapshot) is True, f"player {pid}: is_long_term_unavailable() lost the signal"
            engine = DecisionEngineV12()
            assert engine._is_dead_capital(opt, snapshot) is True, f"player {pid}: DecisionEngineV12 does not flag as dead capital"


class TestIssue3DeterminismRegression:
    """Permanent regression guard for Issue 3: an object carrying a precomputed
    `is_long_term_unavailable` boolean must return that same verdict regardless of what
    wall-clock "now" happens to be, because `is_long_term_unavailable()` short-circuits on the
    precomputed flag before ever calling `_reference_datetime`.
    """

    def test_precomputed_flag_is_immune_to_reference_datetime_drift(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A precomputed True verdict, carried on a plain object with no `news`/status signal at
        # all: if the short-circuit were bypassed, the heuristic fallback would have nothing to
        # go on and could not possibly reproduce True, so this also proves the short-circuit -
        # not the heuristic - is what's firing.
        flagged_true = HistoricalPlayerState(
            player_id=1,
            web_name="Flagged True",
            position=Position.DEFENDER,
            team_id=1,
            price_tenths=50,
            status="a",
            chance_of_playing_next_round=None,
            chance_of_playing_this_round=None,
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
            is_long_term_unavailable=True,
        )
        flagged_false = HistoricalPlayerState(
            player_id=2,
            web_name="Flagged False",
            position=Position.DEFENDER,
            team_id=1,
            price_tenths=50,
            status="i",
            chance_of_playing_next_round=0,
            chance_of_playing_this_round=0,
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
            # Status/chance signals that WOULD heuristically resolve True (severe injury keyword,
            # zero chance of playing) if the short-circuit were bypassed.
            news="Ruptured ACL - out for the season",
            is_long_term_unavailable=False,
        )

        candidate_dates = [
            datetime(2020, 1, 1, tzinfo=timezone.utc),
            datetime(2023, 6, 15, tzinfo=timezone.utc),
            datetime(2026, 9, 30, tzinfo=timezone.utc),
            datetime(2030, 12, 31, tzinfo=timezone.utc),
        ]
        for fake_now in candidate_dates:
            monkeypatch.setattr(models_module, "_reference_datetime", lambda snapshot=None, _dt=fake_now: _dt)
            assert is_long_term_unavailable(flagged_true) is True, (
                f"Precomputed True verdict changed when _reference_datetime()={fake_now}"
            )
            assert is_long_term_unavailable(flagged_false) is False, (
                f"Precomputed False verdict changed when _reference_datetime()={fake_now}"
            )

    def test_raw_object_without_precomputed_flag_still_uses_reference_datetime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sanity check: the heuristic fallback path (for objects with no precomputed flag, e.g.
        raw live-API `Player` objects) is NOT immune to `_reference_datetime` - this is expected
        and confirms the short-circuit in the previous test is what provides the immunity, not
        some accidental removal of date-sensitivity everywhere.
        """
        reference = datetime(2024, 1, 10, tzinfo=timezone.utc)
        return_date = reference + timedelta(days=60)
        news = f"Suspended until {return_date.day} {return_date.strftime('%B')} {return_date.year}"
        p = Player(
            id=999,
            name="Wall Clock Sensitive",
            position=Position.MIDFIELDER,
            team_id=1,
            price_tenths=60,
            status="s",
            chance_of_playing_this_round=0,
            news=news,
        )

        # "Now" is far before the return date: > 35 days away -> long-term.
        monkeypatch.setattr(models_module, "_reference_datetime", lambda snapshot=None: reference)
        assert is_long_term_unavailable(p) is True

        # "Now" is only 10 days before the return date: <= 35 days away -> NOT long-term.
        monkeypatch.setattr(models_module, "_reference_datetime", lambda snapshot=None: return_date - timedelta(days=10))
        assert is_long_term_unavailable(p) is False

    def test_evaluate_long_term_unavailable_used_by_snapshot_builder_is_reference_dt_driven(self) -> None:
        """Direct unit test of the shared heuristic helper: identical status/news/chance inputs
        yield different verdicts purely as a function of the explicit `reference_dt` argument,
        proving `build_historical_snapshot` can compute a reproducible, point-in-time-correct
        verdict using the gameweek deadline instead of wall-clock "now".
        """
        news = "Expected back 15 October"
        near_reference = datetime(2026, 10, 1, tzinfo=timezone.utc)
        far_reference = datetime(2026, 6, 1, tzinfo=timezone.utc)

        near_verdict = evaluate_long_term_unavailable("i", news, 0, 0, near_reference)
        far_verdict = evaluate_long_term_unavailable("i", news, 0, 0, far_reference)

        assert near_verdict is False, "15 Oct is <=35 days after 1 Oct reference -> not long-term"
        assert far_verdict is True, "15 Oct is >35 days after 1 Jun reference -> long-term"


