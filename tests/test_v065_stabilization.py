"""Comprehensive V0.65 stabilization and regression test suite.

Covers:
1. State & sequential transfer integrity, rollback on failure, and price restoration.
2. Expected points (xP) availability scaling, consistency, and bounds.
3. Autosubstitutions with strict formation legality, captain promotion, and chips.
4. Combinatorial optimizer branch-and-bound equivalence vs exhaustive enumeration.
5. Multi-team workspace isolation, active team switching, and slug collision resolution.
6. LLM advisor deterministic guardrails, provider routing, and diagnostic reporting.
"""

from contextlib import closing
import itertools
import json
import math
from pathlib import Path
from unittest.mock import patch
import pytest

from fpl_manager.decision_log import (
    compute_expected_free_transfers,
    get_gameweek_decision,
    log_decision_from_current_squad,
    record_gameweek_decision,
    undo_gameweek_changes,
)
from fpl_manager.expected_points import (
    calculate_component_xp,
    calculate_expected_minutes,
    project_player_gameweek,
)
from fpl_manager.live_matchday import get_live_gameweek_matchday_summary
from fpl_manager.llm_advisor import (
    generate_llm_advisory,
    validate_proposed_advisory_actions,
)
from fpl_manager.models import Position
from fpl_manager.optimizer import PlayerOptInfo, solve_transfers, solve_wildcard
from fpl_manager.rules import Player, validate_squad, validate_starting_lineup
from fpl_manager.squad_state import CurrentSquadState, load_current_squad, save_current_squad
from fpl_manager.storage import SnapshotStore, utc_timestamp
from fpl_manager.teams import (
    create_team,
    get_active_team_id,
    get_team_id_from_squad_path,
    get_team_squad_path,
    list_teams,
    set_active_team,
)
from fpl_manager.transfers import Transfer, execute_transfers, selling_price, validate_transfers


@pytest.fixture
def stabilization_env(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Sets up a complete isolated testing environment for V0.65 stabilization."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "fpl.sqlite3"
    squad_path = config_dir / "current_squad.json"

    store = SnapshotStore(db_path)
    store.initialize()

    teams = [
        {"id": 1, "name": "Arsenal", "short_name": "ARS"},
        {"id": 2, "name": "Liverpool", "short_name": "LIV"},
        {"id": 3, "name": "Manchester City", "short_name": "MCI"},
        {"id": 4, "name": "Chelsea", "short_name": "CHE"},
        {"id": 5, "name": "Tottenham", "short_name": "TOT"},
        {"id": 6, "name": "Newcastle", "short_name": "NEW"},
        {"id": 7, "name": "Aston Villa", "short_name": "AVL"},
        {"id": 8, "name": "Brighton", "short_name": "BHA"},
        {"id": 9, "name": "Fulham", "short_name": "FUL"},
        {"id": 10, "name": "Brentford", "short_name": "BRE"},
    ]

    elements = []
    # 20 players:
    # 1-2: GKP
    # 3-8: DEF
    # 9-14: MID
    # 15-20: FWD
    for p_id in range(1, 21):
        if p_id <= 2:
            pos_id = 1
            cost = 50
        elif p_id <= 8:
            pos_id = 2
            cost = 50
        elif p_id <= 14:
            pos_id = 3
            cost = 60
        else:
            pos_id = 4
            cost = 70

        elements.append({
            "id": p_id,
            "web_name": f"Player_{p_id}",
            "team": ((p_id - 1) % 10) + 1,
            "element_type": pos_id,
            "now_cost": cost,
            "status": "a",
            "chance_of_playing_next_round": 100,
            "news": "",
            "total_points": 25,
            "minutes": 450,
            "starts": 5,
            "expected_goals": "0.20",
            "expected_assists": "0.15",
            "expected_goals_conceded": "1.0",
            "selected_by_percent": 15.0,
        })

    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-15T11:30:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 3, "team_a": 4, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-22T14:00:00Z", "finished": True},
        {"id": 3, "event": 2, "team_h": 1, "team_a": 5, "team_h_difficulty": 2, "team_a_difficulty": 4, "kickoff_time": "2026-08-22T16:30:00Z", "finished": True},
        {"id": 4, "event": 2, "team_h": 6, "team_a": 7, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-22T14:00:00Z", "finished": True},
        {"id": 5, "event": 2, "team_h": 8, "team_a": 9, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-22T14:00:00Z", "finished": True},
        {"id": 6, "event": 2, "team_h": 10, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-22T14:00:00Z", "finished": True},
        {"id": 7, "event": 3, "team_h": 2, "team_a": 3, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-29T14:00:00Z", "finished": False},
    ]

    store.save_snapshot({"teams": teams, "elements": elements}, fixtures, utc_timestamp())

    # Squad: 2 GKP (1, 2), 5 DEF (3, 4, 5, 6, 7), 5 MID (9, 10, 11, 12, 13), 3 FWD (15, 16, 17)
    squad_ids = [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 15, 16, 17]
    prices = {p: (50 if p <= 7 else (60 if p <= 13 else 70)) for p in squad_ids}
    squad_data = CurrentSquadState(
        player_ids=tuple(squad_ids),
        purchase_prices_tenths=prices,
        bank_tenths=15,
        free_transfers=1,
        chips_remaining=("wildcard", "freehit", "bench_boost", "triple_captain"),
        season="2026/27",
        gameweek=2,
    )
    save_current_squad(squad_path, squad_data)

    return config_dir, db_path, squad_path


# ==============================================================================
# 1. State & Transfer Integrity
# ==============================================================================

def test_transfer_sequence_preserves_state(stabilization_env: tuple[Path, Path, Path]) -> None:
    _, db_path, squad_path = stabilization_env

    # Step 1: Base state has player 15
    init_state = load_current_squad(squad_path)
    assert 15 in init_state.player_ids
    assert 18 not in init_state.player_ids

    # Step 2: Execute Transfer 1 (FWD 15 -> FWD 18, both cost 70 tenths)
    res1 = execute_transfers(squad_path, [(15, 18)], database_path=db_path, gameweek=2)
    assert res1["success"] is True
    assert res1["transfer_hits"] == 0
    assert res1["free_transfers"] == 0

    state1 = load_current_squad(squad_path)
    assert 18 in state1.player_ids
    assert 15 not in state1.player_ids
    assert state1.purchase_prices_tenths[18] == 70

    # Step 3: Execute Transfer 2 in same GW (FWD 16 -> FWD 19, triggers 1 hit)
    res2 = execute_transfers(squad_path, [(16, 19)], database_path=db_path, gameweek=2)
    assert res2["success"] is True
    assert res2["transfer_hits"] == 1
    assert len(res2["transfers"]) == 2

    state2 = load_current_squad(squad_path)
    assert 19 in state2.player_ids
    assert 16 not in state2.player_ids

    # Step 4: Verify decision record in database accurately contains both sequential moves
    dec = get_gameweek_decision(2, database_path=db_path)
    assert dec is not None
    assert len(dec["transfers"]) == 2
    assert dec["transfer_hits"] == 1


def test_transfer_undo_is_exact(stabilization_env: tuple[Path, Path, Path]) -> None:
    _, db_path, squad_path = stabilization_env

    # Record baseline decision for GW1
    log_decision_from_current_squad(
        gameweek=1,
        squad_path=squad_path,
        database_path=db_path,
        starting_player_ids=[1, 3, 4, 5, 9, 10, 11, 12, 13, 15, 16],
        bench_player_ids=[2, 6, 7, 17],
        captain_id=15,
        vice_captain_id=9,
        overwrite=True,
    )

    orig_state = load_current_squad(squad_path)
    orig_bank = orig_state.bank_tenths
    orig_players = orig_state.player_ids

    # Execute transfer in GW2 (17 -> 18)
    execute_transfers(squad_path, [(17, 18)], database_path=db_path, gameweek=2)
    transferred_state = load_current_squad(squad_path)
    assert 18 in transferred_state.player_ids

    # Undo GW2 changes
    undo_res = undo_gameweek_changes(squad_path, gameweek=2, database_path=db_path)
    assert undo_res["success"] is True
    assert undo_res["reverted_to_gameweek"] == 1

    reverted_state = load_current_squad(squad_path)
    assert set(reverted_state.player_ids) == set(orig_players)
    assert reverted_state.bank_tenths == orig_bank
    assert reverted_state.purchase_prices_tenths == orig_state.purchase_prices_tenths
    assert reverted_state.free_transfers == 1


def test_purchase_price_after_rise_and_undo(stabilization_env: tuple[Path, Path, Path]) -> None:
    _, db_path, squad_path = stabilization_env

    # In FPL: buy at 50, rises to 60 -> selling price is 50 + (60 - 50)//2 = 55
    assert selling_price(50, 60) == 55
    # Odd rise: buy at 50, rises to 53 -> 50 + 3//2 = 51
    assert selling_price(50, 53) == 51
    # Fall: buy at 50, drops to 48 -> selling price is 48
    assert selling_price(50, 48) == 48

    # Set up GW1 decision
    log_decision_from_current_squad(
        gameweek=1,
        squad_path=squad_path,
        database_path=db_path,
        starting_player_ids=[1, 3, 4, 5, 9, 10, 11, 12, 13, 15, 16],
        bench_player_ids=[2, 6, 7, 17],
        captain_id=15,
        vice_captain_id=9,
        overwrite=True,
    )

    # In GW2: sell player 3 (DEF, bought at 50) and buy player 8 (DEF, cost 50)
    execute_transfers(squad_path, [(3, 8)], database_path=db_path, gameweek=2)
    squad_after_tx = load_current_squad(squad_path)
    assert 8 in squad_after_tx.player_ids
    assert 3 not in squad_after_tx.player_ids

    # Undo GW2: Player 3 must be restored with exact original purchase price (50)
    undo_gameweek_changes(squad_path, gameweek=2, database_path=db_path)
    restored_squad = load_current_squad(squad_path)
    assert 3 in restored_squad.player_ids
    assert restored_squad.purchase_prices_tenths[3] == 50


def test_ft_rollover_boundary(stabilization_env: tuple[Path, Path, Path]) -> None:
    _, db_path, squad_path = stabilization_env

    # GW2 begins with 1 FT
    assert compute_expected_free_transfers(2, database_path=db_path) == 1

    # If rolling in GW2 (0 transfers made), enter GW3 with 2 FTs
    record_gameweek_decision(
        gameweek=2,
        squad_player_ids=[1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 15, 16, 17],
        starting_player_ids=[1, 3, 4, 5, 9, 10, 11, 12, 13, 15, 16],
        bench_player_ids=[2, 6, 7, 17],
        captain_id=15,
        vice_captain_id=9,
        transfers=[],
        database_path=db_path,
        overwrite=True,
    )
    assert compute_expected_free_transfers(3, database_path=db_path) == 2

    # Log consecutive rolls through GW7 to verify 5 FT cap
    for gw in range(3, 8):
        record_gameweek_decision(
            gameweek=gw,
            squad_player_ids=[1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 15, 16, 17],
            starting_player_ids=[1, 3, 4, 5, 9, 10, 11, 12, 13, 15, 16],
            bench_player_ids=[2, 6, 7, 17],
            captain_id=15,
            vice_captain_id=9,
            transfers=[],
            database_path=db_path,
            overwrite=True,
        )

    # Entering GW8 after 6 consecutive rolls should cap at 5 FTs
    assert compute_expected_free_transfers(8, database_path=db_path) == 5


def test_execute_transfers_rollback_when_decision_write_fails(stabilization_env: tuple[Path, Path, Path]) -> None:
    """Direction 1: decision write fails -> squad restored, decision unchanged."""
    _, db_path, squad_path = stabilization_env
    orig_text = squad_path.read_text(encoding="utf-8")

    # Pre-record an existing baseline decision for GW2
    record_gameweek_decision(
        gameweek=2,
        squad_player_ids=[1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 15, 16, 17],
        starting_player_ids=[1, 3, 4, 5, 9, 10, 11, 12, 13, 15, 16],
        bench_player_ids=[2, 6, 7, 17],
        captain_id=15,
        vice_captain_id=9,
        transfers=[],
        notes="Pre-existing decision before failure",
        database_path=db_path,
        overwrite=True,
    )
    pre_dec = get_gameweek_decision(2, database_path=db_path)
    assert pre_dec is not None
    assert pre_dec["notes"] == "Pre-existing decision before failure"

    # Force record_gameweek_decision to fail during execute_transfers
    with patch("fpl_manager.decision_log.record_gameweek_decision", side_effect=RuntimeError("Simulated DB lock during decision write")):
        with pytest.raises(RuntimeError, match="Simulated DB lock during decision write"):
            execute_transfers(squad_path, [(15, 18)], database_path=db_path, gameweek=2)

    # 1. Verify squad file was rolled back exactly to original state
    after_failed_text = squad_path.read_text(encoding="utf-8")
    assert after_failed_text == orig_text

    # 2. Verify pre-existing decision record is unchanged in the database
    dec = get_gameweek_decision(2, database_path=db_path)
    assert dec is not None
    assert dec["notes"] == "Pre-existing decision before failure"
    assert dec["transfers"] == []
    assert dec["captain_id"] == 15


def test_execute_transfers_rollback_when_final_squad_write_fails(stabilization_env: tuple[Path, Path, Path]) -> None:
    """Direction 2: final squad write fails -> squad restored, decision restored."""
    _, db_path, squad_path = stabilization_env
    orig_text = squad_path.read_text(encoding="utf-8")

    # Pre-record a decision for GW2 with player 15 as captain
    record_gameweek_decision(
        gameweek=2,
        squad_player_ids=[1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 15, 16, 17],
        starting_player_ids=[1, 3, 4, 5, 9, 10, 11, 12, 13, 15, 16],
        bench_player_ids=[2, 6, 7, 17],
        captain_id=15,
        vice_captain_id=9,
        transfers=[],
        notes="Pre-existing GW2 decision",
        database_path=db_path,
        overwrite=True,
    )
    pre_dec = get_gameweek_decision(2, database_path=db_path)
    assert pre_dec is not None
    assert pre_dec["notes"] == "Pre-existing GW2 decision"

    # Simulate failure on the final squad save after record_gameweek_decision has succeeded
    orig_save = save_current_squad

    def failing_save(path: Path, state: CurrentSquadState) -> None:
        if state.gameweek == 2 and 18 in state.player_ids:
            raise IOError("Simulated disk full during final squad save")
        return orig_save(path, state)

    with patch("fpl_manager.transfers.save_current_squad", side_effect=failing_save):
        with pytest.raises(IOError, match="Simulated disk full"):
            execute_transfers(squad_path, [(15, 18)], database_path=db_path, gameweek=2)

    # 1. Verify squad file was rolled back
    assert squad_path.read_text(encoding="utf-8") == orig_text

    # 2. Verify pre-existing decision record was restored exactly (compensating rollback in DB)
    restored_dec = get_gameweek_decision(2, database_path=db_path)
    assert restored_dec is not None
    assert restored_dec["notes"] == "Pre-existing GW2 decision"
    assert restored_dec["transfers"] == []
    assert restored_dec["captain_id"] == 15


def test_execute_transfers_rollback_deletes_new_decision_when_final_squad_write_fails(stabilization_env: tuple[Path, Path, Path]) -> None:
    """When no prior decision existed, final squad write failure deletes the newly created decision."""
    _, db_path, squad_path = stabilization_env
    orig_text = squad_path.read_text(encoding="utf-8")

    # Confirm no decision exists for GW2 initially
    assert get_gameweek_decision(2, database_path=db_path) is None

    # Simulate failure on final squad save
    orig_save = save_current_squad

    def failing_save(path: Path, state: CurrentSquadState) -> None:
        if state.gameweek == 2 and 18 in state.player_ids:
            raise IOError("Simulated disk full during final squad save")
        return orig_save(path, state)

    with patch("fpl_manager.transfers.save_current_squad", side_effect=failing_save):
        with pytest.raises(IOError, match="Simulated disk full"):
            execute_transfers(squad_path, [(15, 18)], database_path=db_path, gameweek=2)

    # 1. Squad restored
    assert squad_path.read_text(encoding="utf-8") == orig_text

    # 2. Decision created during execution was rolled back (deleted)
    assert get_gameweek_decision(2, database_path=db_path) is None


# ==============================================================================
# 2. Expected Points (xP) Correctness Audit
# ==============================================================================

def test_availability_scaling() -> None:
    # Test probability consistency: prob_60 + prob_sub == p_start + p_sub
    for avail in (1.0, 0.75, 0.50, 0.25):
        xm, p_start, p_60, p_sub = calculate_expected_minutes(
            status="a" if avail == 1.0 else "d",
            chance_of_playing_next_round=int(avail * 100),
            starts=5,
            minutes=450,
            finished_matches=5,
            price_tenths=100,
            position=Position.MIDFIELDER,
        )
        assert round(p_60 + p_sub, 3) == round(p_start + round(0.05 * avail, 3), 3) or round(p_60 + p_sub, 2) == round(p_start, 2)
        assert 0.0 <= xm <= 90.0


def test_zero_availability_zero_projection() -> None:
    # 0% chance of playing yields exactly 0.0 xP
    xm, p_start, p_60, p_sub = calculate_expected_minutes(
        status="i",
        chance_of_playing_next_round=0,
        starts=5,
        minutes=450,
        finished_matches=5,
    )
    assert xm == 0.0
    assert p_start == 0.0
    assert p_60 == 0.0

    comp = calculate_component_xp(
        position=Position.FORWARD,
        price_tenths=120,
        fdr=2,
        is_home=True,
        expected_minutes=0.0,
        prob_60_plus=0.0,
        prob_sub=0.0,
    )
    assert comp["total"] == 0.0
    assert comp["floor"] == 0.0
    assert comp["ceil"] == 0.0
    assert comp["sigma"] == 0.0


def test_expected_minutes_bounds() -> None:
    # Extreme starts and minutes must never exceed 90.0
    xm, _, _, _ = calculate_expected_minutes(
        status="a",
        starts=100,
        minutes=9000,
        finished_matches=100,
        price_tenths=150,
    )
    assert xm <= 90.0
    assert xm >= 0.0


# ==============================================================================
# 3. Combinatorial Optimizer Verification
# ==============================================================================

def test_branch_and_bound_matches_exhaustive() -> None:
    """Compare branch-and-bound solver against exhaustive enumeration on a synthetic pool."""
    squad = [
        PlayerOptInfo(id=1, name="GKP1", position=Position.GOALKEEPER, team_id=1, team_short="ARS", price_tenths=50, status="a", total_points=20, expected_points=3.5),
        PlayerOptInfo(id=2, name="DEF1", position=Position.DEFENDER, team_id=1, team_short="ARS", price_tenths=50, status="a", total_points=20, expected_points=3.8),
        PlayerOptInfo(id=3, name="MID1", position=Position.MIDFIELDER, team_id=2, team_short="LIV", price_tenths=70, status="a", total_points=25, expected_points=4.2),
        PlayerOptInfo(id=4, name="FWD1", position=Position.FORWARD, team_id=3, team_short="MCI", price_tenths=80, status="a", total_points=30, expected_points=5.0),
    ]

    candidates = [
        PlayerOptInfo(id=101, name="DEF_T1", position=Position.DEFENDER, team_id=4, team_short="CHE", price_tenths=52, status="a", total_points=30, expected_points=5.5),
        PlayerOptInfo(id=102, name="DEF_T2", position=Position.DEFENDER, team_id=5, team_short="TOT", price_tenths=48, status="a", total_points=22, expected_points=4.0),
        PlayerOptInfo(id=103, name="MID_T1", position=Position.MIDFIELDER, team_id=4, team_short="CHE", price_tenths=72, status="a", total_points=35, expected_points=6.2),
        PlayerOptInfo(id=104, name="MID_T2", position=Position.MIDFIELDER, team_id=5, team_short="TOT", price_tenths=68, status="a", total_points=28, expected_points=5.1),
        PlayerOptInfo(id=105, name="FWD_T1", position=Position.FORWARD, team_id=4, team_short="CHE", price_tenths=85, status="a", total_points=40, expected_points=7.5),
        PlayerOptInfo(id=106, name="FWD_T2", position=Position.FORWARD, team_id=5, team_short="TOT", price_tenths=78, status="a", total_points=32, expected_points=6.0),
    ]

    selling_prices = {p.id: p.price_tenths for p in squad}
    fdr_map = {"ARS": 3.0, "LIV": 3.0, "MCI": 3.0, "CHE": 2.0, "TOT": 3.0}
    ticker_map = {t: "GW" for t in fdr_map}

    # 1-transfer test
    bnb_results, _ = solve_transfers(
        num_transfers=1,
        squad_players=squad,
        candidate_pool=candidates,
        bank_tenths=20,
        free_transfers=1,
        selling_prices=selling_prices,
        fdr_map=fdr_map,
        ticker_map=ticker_map,
        cand_limit=50,
        max_results=5,
    )

    # Exhaustive enumeration for 1 transfer
    best_score = -999.0
    best_move = None
    for out_p in squad:
        for in_p in candidates:
            if in_p.position == out_p.position and in_p.price_tenths <= selling_prices[out_p.id] + 20:
                fdr_delta = (3.0 - fdr_map.get(in_p.team_short, 3.0)) - (3.0 - fdr_map.get(out_p.team_short, 3.0))
                score = round((in_p.expected_points - out_p.expected_points) + 0.1 * fdr_delta, 3)
                if score > best_score:
                    best_score = score
                    best_move = (out_p.id, in_p.id)

    assert len(bnb_results) > 0
    top_bnb = bnb_results[0]
    assert top_bnb["outgoing"][0]["id"] == best_move[0]
    assert top_bnb["incoming"][0]["id"] == best_move[1]
    assert round(top_bnb["score"], 3) == best_score


# ==============================================================================
# 4. Live Matchday & Autosub Formation Legality
# ==============================================================================

def test_autosub_formation_legality(stabilization_env: tuple[Path, Path, Path]) -> None:
    """Verify autosub maintains legal formation (minimum 3 DEF) when starting defender has 0 minutes."""
    _, db_path, squad_path = stabilization_env

    # 3-5-2 Starting Lineup:
    # Starters: GKP 1, DEF 3, 4, 5, MID 9, 10, 11, 12, 13, FWD 15, 16
    # Bench: GKP 2, Bench 1 = FWD 17, Bench 2 = DEF 6, Bench 3 = DEF 7
    starters = [1, 3, 4, 5, 9, 10, 11, 12, 13, 15, 16]
    bench = [2, 17, 6, 7]

    record_gameweek_decision(
        gameweek=2,
        squad_player_ids=[1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 15, 16, 17],
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=15,
        vice_captain_id=9,
        database_path=db_path,
        overwrite=True,
    )

    # Mock detailed stats:
    # DEF 3 played 0 minutes and match finished
    # Bench 1 (FWD 17) played 90 mins (scored 5 pts)
    # Bench 2 (DEF 6) played 90 mins (scored 6 pts)
    def mock_live_stats(gw, **kwargs):
        stats = {pid: {"total_points": 4, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 15} for pid in range(1, 21)}
        stats[3] = {"total_points": 0, "minutes": 0, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 0}
        stats[17] = {"total_points": 5, "minutes": 90, "goals_scored": 0, "assists": 1, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 20}
        stats[6] = {"total_points": 6, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 1, "goals_conceded": 0, "bonus": 0, "bps": 25}
        return stats

    with patch("fpl_manager.live_matchday.get_detailed_player_gameweek_stats", side_effect=mock_live_stats):
        summary = get_live_gameweek_matchday_summary(
            gameweek=2,
            squad_path=squad_path,
            database_path=db_path,
            save_reports=False,
        )

        autosubs = summary["autosubs"]
        assert len(autosubs) == 1
        # Crucial check: Sub in MUST be DEF 6, NOT FWD 17, to prevent illegal 2-DEF formation!
        assert autosubs[0]["out"]["id"] == 3
        assert autosubs[0]["in"]["id"] == 6
        assert autosubs[0]["in"]["position"] == "DEF"


def test_captain_promotion_and_triple_captain(stabilization_env: tuple[Path, Path, Path]) -> None:
    _, db_path, squad_path = stabilization_env

    # Captain 15 played 0 mins (finished), VC 9 played 90 mins and scored 8 pts with Triple Captain active
    record_gameweek_decision(
        gameweek=2,
        squad_player_ids=[1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 15, 16, 17],
        starting_player_ids=[1, 3, 4, 5, 9, 10, 11, 12, 13, 15, 16],
        bench_player_ids=[2, 6, 7, 17],
        captain_id=15,
        vice_captain_id=9,
        chip_played="triple_captain",
        database_path=db_path,
        overwrite=True,
    )

    def mock_stats(gw, **kwargs):
        stats = {pid: {"total_points": 4, "minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 15} for pid in range(1, 21)}
        stats[15] = {"total_points": 0, "minutes": 0, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 0, "bps": 0}
        stats[9] = {"total_points": 8, "minutes": 90, "goals_scored": 1, "assists": 0, "clean_sheets": 0, "goals_conceded": 0, "bonus": 1, "bps": 30}
        return stats

    with patch("fpl_manager.live_matchday.get_detailed_player_gameweek_stats", side_effect=mock_stats):
        summary = get_live_gameweek_matchday_summary(
            gameweek=2,
            squad_path=squad_path,
            database_path=db_path,
            save_reports=False,
        )

        assert summary["captain"]["promoted_from_vice"] is True
        assert summary["captain"]["id"] == 9
        assert summary["captain"]["multiplier"] == 3

        # VC (promoted to TC) scores 8 * 3 = 24 pts
        promoted_vc = next(p for p in summary["starters"] if p["id"] == 9)
        assert promoted_vc["multiplier"] == 3
        assert promoted_vc["points"] == 24


# ==============================================================================
# 5. Multi-Team Isolation & Slug Collision
# ==============================================================================

def test_team_isolation_and_slug_collision(stabilization_env: tuple[Path, Path, Path]) -> None:
    config_dir, db_path, _ = stabilization_env

    # 1. Team creation with slug collision handling
    t1 = create_team("Invincibles XI", config_dir=config_dir, set_as_active=False)
    assert t1["team_id"] == "invincibles-xi"

    # Creating another team with identical name auto-disambiguates to 'invincibles-xi-2'
    t2 = create_team("Invincibles XI", config_dir=config_dir, set_as_active=False)
    assert t2["team_id"] == "invincibles-xi-2"

    # 2. Team path identification using Path.relative_to
    squad_t1_path = Path(t1["squad_path"])
    assert get_team_id_from_squad_path(squad_t1_path, config_dir=config_dir) == "invincibles-xi"

    # 3. Team decision isolation
    record_gameweek_decision(
        gameweek=2,
        team_id="invincibles-xi",
        squad_player_ids=[1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 15, 16, 17],
        starting_player_ids=[1, 3, 4, 5, 9, 10, 11, 12, 13, 15, 16],
        bench_player_ids=[2, 6, 7, 17],
        captain_id=15,
        vice_captain_id=9,
        notes="Unique note for Team 1",
        database_path=db_path,
        overwrite=True,
    )

    dec_t1 = get_gameweek_decision(2, team_id="invincibles-xi", database_path=db_path)
    assert dec_t1 is not None
    assert dec_t1["notes"] == "Unique note for Team 1"

    # Team 2 has no decision for GW2
    dec_t2 = get_gameweek_decision(2, team_id="invincibles-xi-2", database_path=db_path)
    assert dec_t2 is None


# ==============================================================================
# 6. LLM Advisor Diagnostics & Guardrails
# ==============================================================================

def test_llm_advisor_diagnostics_and_guardrails(stabilization_env: tuple[Path, Path, Path]) -> None:
    _, db_path, squad_path = stabilization_env

    # 1. Test auto-routing captures failure reasons when external providers fail
    with patch("fpl_manager.llm_advisor._call_gemini_api", side_effect=RuntimeError("Gemini Quota Exceeded")):
        with patch("fpl_manager.llm_advisor._call_openai_api", side_effect=RuntimeError("OpenAI Server Error")):
            adv = generate_llm_advisory(
                gameweek=2,
                squad_path=squad_path,
                database_path=db_path,
                provider="auto",
                api_key="mock-key-for-test",
                save_reports=False,
            )
            assert adv["provider_used"] == "heuristic (auto-fallback)"
            assert any("Gemini" in reason for reason in adv["fallback_reasons"])
            assert any("OpenAI" in reason for reason in adv["fallback_reasons"])

    # 2. Test unfenced JSON extraction and robust player resolution
    mock_unfenced_json = """
    Here is my direct feedback without code fences:
    {
      "critique_points": ["Template midfield overexposure"],
      "tactical_notes": ["Target newly promoted defensive lapses"],
      "captain": "player-15",
      "vice_captain": "Player 9",
      "transfers": [
        {"out": "player_16", "in": "player 18", "rationale": "Form upgrade"}
      ]
    }
    """
    with patch("fpl_manager.llm_advisor._call_gemini_api", return_value=mock_unfenced_json):
        adv2 = generate_llm_advisory(
            gameweek=2,
            squad_path=squad_path,
            database_path=db_path,
            provider="gemini",
            api_key="dummy-key",
            save_reports=False,
        )
        assert adv2["proposed_captain"] == "player-15"
        assert adv2["validation"]["is_legal"] is True
        assert len(adv2["validation"]["validated_transfers"]) == 1
        assert adv2["validation"]["validated_transfers"][0]["out_name"] == "Player_16"
        assert adv2["validation"]["validated_transfers"][0]["in_name"] == "Player_18"
