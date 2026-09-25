"""Tests for V1.1.5 Hardening: Premier League Departures, Seasonal Chips, and Benchmark Ledger.

Validates the 4 architectural pillars defined in docs/v1.1.5/v115.md:
- Pillar 1: Premier League Departure Lifecycle & Dead Capital Engine
- Pillar 2: Seasonal Chip State & Calibration Guardrails
- Pillar 3: Decision-State & Experiment Integrity (zero silent fallbacks, provenance hashing)
- Pillar 4: Multi-Version Historical Benchmark Ledger (V0.9 vs V1.0 vs V1.1 vs V1.1.5)
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from fpl_manager.chip_strategy import SeasonalChipInventory, SeasonalChipPolicy
from fpl_manager.expected_points import ExpectedPointsProjection
from fpl_manager.historical.models import (
    GameweekOutcome,
    HistoricalFixture,
    HistoricalGameweekSnapshot,
    HistoricalPlayerState,
)
from fpl_manager.models import (
    Player,
    PlayerEligibilityStatus,
    Position,
    get_player_eligibility_status,
    is_departed_from_premier_league,
)
from fpl_manager.optimizer import PlayerOptInfo, solve_transfers, solve_wildcard
from fpl_manager.strategic_squad import StrategicCandidate, StrategicConstraints, solve_strategic_squad
from fpl_manager.suggest_transfers import PlayerInfo, suggest_transfers, suggest_wildcard
from fpl_manager.backtest.decision_engine import (
    DecisionEngineV09,
    DecisionEngineV10,
    DecisionEngineV11,
    DecisionEngineV115,
    resolve_decision_engine,
)
from fpl_manager.backtest.engine import (
    GameweekDecisionResult,
    SimulationResult,
    run_sequential_simulation,
    simulate_autosubs_and_score,
)
from fpl_manager.backtest.strategic_analysis import run_version_comparison_backtest


# ==============================================================================
# Pillar 1 Tests: Departure Lifecycle & Dead Capital Engine
# ==============================================================================

class TestDepartureDetection:
    """Validate point-in-time departure classification rules."""

    def test_status_u_is_classified_as_departed(self) -> None:
        p = Player(
            id=101,
            name="Departed Star",
            position=Position.FORWARD,
            team_id=1,
            price_tenths=100,
            status="u",
            news="Transferred to Bayern Munich",
        )
        assert is_departed_from_premier_league(p) is True

    def test_zero_chance_with_transfer_news_is_departed(self) -> None:
        p = Player(
            id=102,
            name="Loan Player",
            position=Position.MIDFIELDER,
            team_id=2,
            price_tenths=75,
            status="n",
            chance_of_playing_this_round=0,
            chance_of_playing_next_round=0,
            news="Joined AS Roma on season-long loan",
        )
        assert is_departed_from_premier_league(p) is True

    def test_zero_chance_with_permanent_transfer_news_is_departed(self) -> None:
        p = Player(
            id=103,
            name="Sold Midfielder",
            position=Position.MIDFIELDER,
            team_id=3,
            price_tenths=80,
            status="i",
            chance_of_playing_this_round=0,
            news="Completed permanent transfer to Barcelona",
        )
        assert is_departed_from_premier_league(p) is True

    def test_injured_player_without_departure_news_is_not_departed(self) -> None:
        p = Player(
            id=104,
            name="Injured Striker",
            position=Position.FORWARD,
            team_id=4,
            price_tenths=90,
            status="i",
            chance_of_playing_this_round=0,
            news="Hamstring surgery, expected return in 6 weeks",
        )
        assert is_departed_from_premier_league(p) is False

    def test_doubtful_player_is_not_departed(self) -> None:
        p = Player(
            id=105,
            name="Doubtful Defender",
            position=Position.DEFENDER,
            team_id=5,
            price_tenths=50,
            status="d",
            chance_of_playing_this_round=75,
            news="Knock - 75% chance of playing",
        )
        assert is_departed_from_premier_league(p) is False

    def test_eligibility_status_dataclass(self) -> None:
        p = Player(
            id=101,
            name="Departed Star",
            position=Position.FORWARD,
            team_id=1,
            price_tenths=100,
            status="u",
            news="Transferred to Real Madrid",
        )
        elig = get_player_eligibility_status(p, dead_capital_weight=3.0)
        assert isinstance(elig, PlayerEligibilityStatus)
        assert elig.player_id == 101
        assert elig.is_in_premier_league is False
        assert elig.status_code == "u"
        assert elig.dead_capital_penalty == pytest.approx(30.0)


class TestDeadCapitalOffloadAndBuyFiltering:
    """Validate dead capital priority offloading and candidate pool exclusion."""

    @pytest.fixture
    def mock_players(self) -> list[PlayerOptInfo]:
        """Set up 15 squad players, where player 1 (price £10.0m) is departed."""
        players = []
        # Departed expensive player
        players.append(PlayerOptInfo(
            id=1,
            name="Departed Legend",
            position=Position.FORWARD,
            team_id=1,
            team_short="ARS",
            price_tenths=100,
            status="u",
            total_points=0,
            expected_points=0.0,
        ))
        # Poorly performing active forward
        players.append(PlayerOptInfo(
            id=2,
            name="Struggling Forward",
            position=Position.FORWARD,
            team_id=1,
            team_short="ARS",
            price_tenths=60,
            status="a",
            total_points=10,
            expected_points=1.0,
        ))
        # Other squad members
        for pid in range(3, 16):
            pos = Position.GOALKEEPER if pid <= 4 else (Position.DEFENDER if pid <= 9 else (Position.MIDFIELDER if pid <= 14 else Position.FORWARD))
            players.append(PlayerOptInfo(
                id=pid,
                name=f"Squad Player {pid}",
                position=pos,
                team_id=pid % 5 + 1,
                team_short=f"T{pid % 5 + 1}",
                price_tenths=50,
                status="a",
                total_points=20,
                expected_points=3.0,
            ))
        return players

    def test_transfers_prioritize_departed_player_over_active_underperformer(self, mock_players: list[PlayerOptInfo]) -> None:
        """With dead_capital_weight > 0, the solver strongly prioritizes offloading the departed player."""
        current_squad = mock_players
        candidate_pool = [
            PlayerOptInfo(
                id=101,
                name="Top In-Form Striker",
                position=Position.FORWARD,
                team_id=2,
                team_short="AVL",
                price_tenths=85,
                status="a",
                total_points=40,
                expected_points=7.0,
            ),
            PlayerOptInfo(
                id=102,
                name="Budget In-Form Striker",
                position=Position.FORWARD,
                team_id=3,
                team_short="BHA",
                price_tenths=55,
                status="a",
                total_points=30,
                expected_points=5.0,
            ),
        ]

        selling_prices = {p.id: p.price_tenths for p in current_squad}
        fdr_map = {"ARS": 3.0, "AVL": 3.0, "BHA": 3.0, "CHE": 3.0, "LIV": 3.0}
        for i in range(1, 10):
            fdr_map[f"T{i}"] = 3.0
        ticker_map = {}

        # Solve with dead_capital_weight = 3.0
        options, _ = solve_transfers(
            num_transfers=1,
            squad_players=current_squad,
            candidate_pool=candidate_pool,
            bank_tenths=10,
            free_transfers=1,
            selling_prices=selling_prices,
            fdr_map=fdr_map,
            ticker_map=ticker_map,
            dead_capital_weight=3.0,
        )

        assert len(options) > 0
        best_opt = options[0]
        # Top outgoing player must be the departed player (id=1)
        out_ids = [p["id"] for p in best_opt["outgoing"]]
        assert 1 in out_ids
        # Metadata must reflect dead capital bonus
        assert best_opt["outgoing"][0]["is_departed"] is True
        assert best_opt["dead_capital_bonus"] == pytest.approx(30.0)

    def test_departed_players_cannot_be_bought(self, mock_players: list[PlayerOptInfo]) -> None:
        """Departed players in candidate pool must be strictly rejected."""
        candidate_pool = [
            PlayerOptInfo(
                id=201,
                name="Departed Former Star",
                position=Position.FORWARD,
                team_id=4,
                team_short="CHE",
                price_tenths=90,
                status="u",
                total_points=0,
                expected_points=8.0,
            ),
            PlayerOptInfo(
                id=202,
                name="Active Great Striker",
                position=Position.FORWARD,
                team_id=5,
                team_short="LIV",
                price_tenths=90,
                status="a",
                total_points=50,
                expected_points=7.5,
            ),
        ]

        selling_prices = {p.id: p.price_tenths for p in mock_players}
        fdr_map = {"ARS": 3.0, "AVL": 3.0, "BHA": 3.0, "CHE": 3.0, "LIV": 3.0}
        for i in range(1, 10):
            fdr_map[f"T{i}"] = 3.0
        ticker_map = {}

        options, _ = solve_transfers(
            num_transfers=1,
            squad_players=mock_players,
            candidate_pool=candidate_pool,
            bank_tenths=20,
            free_transfers=1,
            selling_prices=selling_prices,
            fdr_map=fdr_map,
            ticker_map=ticker_map,
            dead_capital_weight=3.0,
        )

        for opt in options:
            for p_in in opt["incoming"]:
                assert p_in["id"] != 201
                assert p_in["status"] != "u"
                assert p_in["is_departed"] is False

    def test_strategic_constraints_rejects_departed_locked_player(self) -> None:
        """Locking a departed player must raise a ValueError during validation."""
        locked_p = PlayerInfo(
            id=999,
            name="Departed Icon",
            position=Position.MIDFIELDER,
            team_id=1,
            team_short="ARS",
            price_tenths=110,
            status="u",
            total_points=0,
            expected_points=0.0,
        )
        constraints = StrategicConstraints(locked_player_ids={999})
        errors = constraints.validate([locked_p])
        assert any("Departed player IDs cannot be locked" in err for err in errors)


# ==============================================================================
# Pillar 2 Tests: Seasonal Chip State & Calibration Guardrails
# ==============================================================================

class TestSeasonalChipInventory:
    """Validate 2-window independent quotas and strict Window 1 expiry semantics."""

    def test_initial_quotas_all_available(self) -> None:
        inv = SeasonalChipInventory()
        assert inv.available_chips(1) == {"wildcard", "free_hit", "triple_captain", "bench_boost"}
        assert inv.available_chips(19) == {"wildcard", "free_hit", "triple_captain", "bench_boost"}
        assert inv.available_chips(20) == {"wildcard", "free_hit", "triple_captain", "bench_boost"}
        assert inv.available_chips(38) == {"wildcard", "free_hit", "triple_captain", "bench_boost"}

    def test_window_1_usage_does_not_affect_window_2(self) -> None:
        inv = SeasonalChipInventory()
        # Use Wildcard in GW 5
        inv.use_chip(5, "wildcard")
        assert "wildcard" not in inv.available_chips(6)
        # Window 2 Wildcard is still fully intact!
        assert "wildcard" in inv.available_chips(20)

    def test_window_1_unconsumed_chips_expire_after_gw19(self) -> None:
        inv = SeasonalChipInventory()
        # Manager plays no chips in GW 1-19
        assert inv.wildcard_w1 is True
        # In GW 20, Window 1 is gone; only Window 2 exists
        assert inv.available_chips(20) == {"wildcard", "free_hit", "triple_captain", "bench_boost"}
        inv.use_chip(25, "wildcard")
        # In GW 26, no more wildcards exist (Window 1 expired, Window 2 consumed)
        assert "wildcard" not in inv.available_chips(26)
        with pytest.raises(ValueError, match="not available at gameweek 27"):
            inv.use_chip(27, "wildcard")

    def test_invalid_gameweek_returns_empty_and_rejects_use(self) -> None:
        inv = SeasonalChipInventory()
        assert inv.available_chips(0) == set()
        assert inv.available_chips(39) == set()
        with pytest.raises(ValueError):
            inv.use_chip(0, "wildcard")
        with pytest.raises(ValueError):
            inv.use_chip(39, "wildcard")

    def test_serialization_round_trip(self) -> None:
        inv = SeasonalChipInventory()
        inv.use_chip(8, "triple_captain")
        inv.use_chip(24, "free_hit")
        d = inv.to_dict()
        restored = SeasonalChipInventory.from_dict(d)
        assert restored.triple_captain_w1 is False
        assert restored.free_hit_w2 is False
        assert restored.wildcard_w1 is True
        assert restored.wildcard_w2 is True


class TestSeasonalChipPolicyGuardrails:
    """Validate anti-pathology guardrails (e.g. no premature GW 2-4 Wildcards)."""

    def test_early_wildcard_prevented_without_severe_shock(self) -> None:
        policy = SeasonalChipPolicy(early_wc_restricted_gws=(2, 3, 4))
        inv = SeasonalChipInventory()
        squad_ids = list(range(1, 16))
        player_states = tuple(
            HistoricalPlayerState(
                player_id=pid,
                web_name=f"Player {pid}",
                position=Position.DEFENDER,
                team_id=1,
                price_tenths=50,
                status="a",
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
            for pid in squad_ids
        )
        snap = HistoricalGameweekSnapshot(
            season="2023-24",
            gameweek=2,
            deadline_time="2023-08-18T17:15:00Z",
            finished_gameweeks=1,
            players=player_states,
            teams=(),
            fixtures=(),
        )
        projs = [
            ExpectedPointsProjection(
                player_id=pid,
                web_name=f"Player {pid}",
                position=Position.DEFENDER,
                team_id=1,
                team_short="ARS",
                price_tenths=50,
                status="a",
                availability_pct=100.0,
                base_xp_per_match=4.0,
                gameweek=2,
                fixtures=(),
                expected_points=4.0,
            )
            for pid in squad_ids
        ]

        rec_chip = policy.evaluate_gameweek_chip(
            gameweek=2,
            inventory=inv,
            squad_ids=squad_ids,
            snapshot=snap,
            projections=projs,
            initial_squad_ids=tuple(squad_ids),
        )
        # In GW 2 with healthy squad, Wildcard must NOT be deployed!
        assert rec_chip != "wildcard"


# ==============================================================================
# Pillar 3 Tests: Decision-State & Experiment Integrity
# ==============================================================================

class TestDecisionStateAndFallbackTransparency:
    """Verify zero silent fallbacks and explicit version reporting."""

    def test_v115_engine_resolution(self) -> None:
        eng = resolve_decision_engine("v1.1.5", dead_capital_weight=3.0)
        assert isinstance(eng, DecisionEngineV115)
        assert eng.version == "v1.1.5"
        assert eng.dead_capital_weight == 3.0
        assert eng.fallback_occurred is False
        assert eng.fallback_reason is None

    def test_fallback_flag_is_truthfully_exposed_when_raised(self) -> None:
        eng = DecisionEngineV115(dead_capital_weight=3.0)
        # Directly trigger fallback recording
        eng.fallback_occurred = True
        eng.fallback_reason = "Simulated optimization infeasibility"
        cfg = eng.get_strategy_config("OptimizerStrategy")
        assert cfg["fallback_occurred"] is True
        assert cfg["fallback_reason"] == "Simulated optimization infeasibility"
        assert cfg["engine_version"] == "v1.1.5"


# ==============================================================================
# Pillar 4 Tests: Multi-Version Historical Benchmark Ledger
# ==============================================================================

class TestMultiVersionBenchmarkLedger:
    """Verify dual-track historical benchmark runner across V0.9, V1.0, V1.1, V1.1.5."""

    def test_run_version_comparison_smoke_test(self, tmp_path: Path) -> None:
        res = run_version_comparison_backtest(
            seasons=("2023-24",),
            versions=("v0.9", "v1.0", "v1.1", "v1.1.5"),
            tracks=("track_a_no_chips", "track_b_with_chips"),
            start_gw=1,
            end_gw=3,
            save_report=True,
            output_dir=tmp_path,
            smoke_test=True,
        )

        assert res["smoke_test"] is True
        assert res["seasons_evaluated"] == ["2023-24"]
        assert "v1.1.5" in res["version_aggregates"]
        assert "track_a_no_chips" in res["version_aggregates"]["v1.1.5"]
        assert "track_b_with_chips" in res["version_aggregates"]["v1.1.5"]

        # Check provenance
        prov = res["provenance"]
        assert "experiment_id" in prov
        assert prov["decision_engine_version"] == "v0.9,v1.0,v1.1,v1.1.5"
        assert len(prov["configuration_hash"]) == 16

        # Check files were written
        md_file = tmp_path / "multi_version_comparison.md"
        json_file = tmp_path / "multi_version_comparison.json"
        assert md_file.exists()
        assert json_file.exists()

        content = md_file.read_text(encoding="utf-8")
        assert "Multi-Version Historical Benchmark Ledger" in content
        assert "Track A: Without Chips" in content
        assert "Track B: With Chips" in content
        assert "v1.1.5" in content


class TestChipSimulationScoring:
    """Validate matchday scoring rules under active chips (TC 3x multiplier, BB 15-player scoring)."""

    def test_triple_captain_scores_3x(self) -> None:
        starters = list(range(1, 12))
        bench = list(range(12, 16))
        captain_id = 1
        vice_captain_id = 2
        positions = {pid: (Position.GOALKEEPER if pid in (1, 12) else Position.MIDFIELDER) for pid in range(1, 16)}

        # Captain scores 10 pts, other 10 starters score 2 pts each = 20 pts
        outcomes = {
            1: GameweekOutcome(season="2023-24", gameweek=1, player_id=1, minutes=90, total_points=10),
            **{
                pid: GameweekOutcome(season="2023-24", gameweek=1, player_id=pid, minutes=90, total_points=2)
                for pid in range(2, 12)
            },
            **{
                pid: GameweekOutcome(season="2023-24", gameweek=1, player_id=pid, minutes=90, total_points=5)
                for pid in range(12, 16)
            },
        }

        # Normal standard captain (2x) -> 10*2 + 10*2 = 40 pts
        normal_gross, _, _ = simulate_autosubs_and_score(
            starters, bench, captain_id, vice_captain_id, outcomes, positions, chip_used=None
        )
        assert normal_gross == 40

        # Triple Captain (3x) -> 10*3 + 10*2 = 50 pts
        tc_gross, _, _ = simulate_autosubs_and_score(
            starters, bench, captain_id, vice_captain_id, outcomes, positions, chip_used="triple_captain"
        )
        assert tc_gross == 50

    def test_bench_boost_scores_all_15_players(self) -> None:
        starters = list(range(1, 12))
        bench = list(range(12, 16))
        captain_id = 1
        vice_captain_id = 2
        positions = {pid: (Position.GOALKEEPER if pid in (1, 12) else Position.MIDFIELDER) for pid in range(1, 16)}

        # All 15 players score 3 pts each; captain scores 3 pts
        outcomes = {
            pid: GameweekOutcome(season="2023-24", gameweek=1, player_id=pid, minutes=90, total_points=3)
            for pid in range(1, 16)
        }

        # Normal matchday: starters score (10*3 + 1*3*2 = 36 pts), bench does not score
        normal_gross, _, _ = simulate_autosubs_and_score(
            starters, bench, captain_id, vice_captain_id, outcomes, positions, chip_used=None
        )
        assert normal_gross == 36

        # Bench Boost: all 15 score -> 14*3 + 1*3*2 = 42 + 6 = 48 pts
        bb_gross, autosubs, _ = simulate_autosubs_and_score(
            starters, bench, captain_id, vice_captain_id, outcomes, positions, chip_used="bench_boost"
        )
        assert bb_gross == 48
        assert autosubs == ()  # No autosubs needed when bench already scores!

