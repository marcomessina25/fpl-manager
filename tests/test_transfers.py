import json
from pathlib import Path
import pytest

from fpl_manager.cli import validate_transfer_set
from fpl_manager.models import Player, Position
from fpl_manager.squad_state import CurrentSquadState
from fpl_manager.storage import SnapshotStore, utc_timestamp
from fpl_manager.transfers import Transfer, resolve_chained_transfers, selling_price, validate_transfers


def make_player(player_id: int, position: Position, team_id: int, price: int) -> Player:
    return Player(player_id, f"Player {player_id}", position, team_id, price)


def squad_and_state() -> tuple[list[Player], CurrentSquadState]:
    players: list[Player] = []
    player_id = 1
    for position, count in ((Position.GOALKEEPER, 2), (Position.DEFENDER, 5), (Position.MIDFIELDER, 5), (Position.FORWARD, 3)):
        for _ in range(count):
            players.append(make_player(player_id, position, ((player_id - 1) // 3) + 1, 50))
            player_id += 1
    state = CurrentSquadState(tuple(range(1, 16)), {player_id: 50 for player_id in range(1, 16)}, 10, 1, (), "2026/27")
    return players, state


def test_selling_price_keeps_half_of_a_rise() -> None:
    assert selling_price(50, 57) == 53


def test_valid_transfer_updates_bank() -> None:
    players, state = squad_and_state()
    players.append(make_player(16, Position.GOALKEEPER, 6, 55))
    result = validate_transfers(state, players, [Transfer(1, 16)])
    assert result.is_valid
    assert result.bank_after_tenths == 5
    assert result.transfer_hits == 0


def test_rejects_position_change() -> None:
    players, state = squad_and_state()
    players.append(make_player(16, Position.MIDFIELDER, 6, 50))
    assert not validate_transfers(state, players, [Transfer(1, 16)]).is_valid


def test_rejects_unaffordable_transfer() -> None:
    players, state = squad_and_state()
    players.append(make_player(16, Position.GOALKEEPER, 6, 70))
    assert "need" in " ".join(validate_transfers(state, players, [Transfer(1, 16)]).errors)


def test_counts_transfer_hit() -> None:
    players, state = squad_and_state()
    players.extend([make_player(16, Position.GOALKEEPER, 6, 50), make_player(17, Position.DEFENDER, 6, 50)])
    result = validate_transfers(state, players, [Transfer(1, 16), Transfer(3, 17)])
    assert result.is_valid
    assert result.transfer_hits == 1


def test_validate_transfer_set_by_name(tmp_path: Path) -> None:
    db_path = tmp_path / "fpl.sqlite3"
    squad_file = tmp_path / "current_squad.json"

    store = SnapshotStore(db_path)
    bootstrap = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Manchester City", "short_name": "MCI"},
            {"id": 3, "name": "Liverpool", "short_name": "LIV"},
            {"id": 4, "name": "Chelsea", "short_name": "CHE"},
            {"id": 5, "name": "Tottenham", "short_name": "TOT"},
            {"id": 6, "name": "Newcastle", "short_name": "NEW"},
        ],
        "elements": [
            {"id": 1, "web_name": "Raya", "team": 1, "element_type": 1, "now_cost": 55, "status": "a", "total_points": 100},
            {"id": 2, "web_name": "Haaland", "team": 2, "element_type": 4, "now_cost": 150, "status": "a", "total_points": 200},
            {"id": 3, "web_name": "Pickford", "team": 1, "element_type": 1, "now_cost": 50, "status": "a", "total_points": 90},
        ] + [
            {
                "id": k,
                "web_name": f"P{k}",
                "team": (k % 6) + 1,
                "element_type": 1 if k == 4 else (2 if k < 10 else (3 if k < 15 else 4)),
                "now_cost": 50,
                "status": "a",
                "total_points": 50,
            }
            for k in range(4, 18)
        ],
    }
    store.save_snapshot(bootstrap, [], utc_timestamp())

    # Build valid squad of 15 players
    squad_data = {
        "season": "2026/27",
        "player_ids": [1] + list(range(4, 18)),
        "purchase_prices_tenths": {str(k): 50 for k in [1] + list(range(4, 18))},
        "bank_tenths": 20,
        "free_transfers": 1,
        "chips_remaining": [],
    }
    squad_file.write_text(json.dumps(squad_data), encoding="utf-8")

    # Name-based transfer: Raya (ID 1) -> Pickford (ID 3)
    res = validate_transfer_set(squad_file, ["Raya:Pickford"], by_name=True, database_path=db_path)
    assert res["is_valid"] is True

    # Failed resolution raises RuntimeError
    with pytest.raises(RuntimeError, match="Could not resolve outgoing player 'NonExistent'"):
        validate_transfer_set(squad_file, ["NonExistent:Pickford"], by_name=True, database_path=db_path)


def test_execute_transfers(tmp_path: Path) -> None:
    from fpl_manager.squad_state import load_current_squad
    from fpl_manager.transfers import execute_transfers

    db_path = tmp_path / "fpl.sqlite3"
    squad_file = tmp_path / "current_squad.json"

    store = SnapshotStore(db_path)
    bootstrap = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Manchester City", "short_name": "MCI"},
            {"id": 3, "name": "Liverpool", "short_name": "LIV"},
            {"id": 4, "name": "Chelsea", "short_name": "CHE"},
            {"id": 5, "name": "Tottenham", "short_name": "TOT"},
            {"id": 6, "name": "Newcastle", "short_name": "NEW"},
        ],
        "elements": [
            {"id": 1, "web_name": "Raya", "team": 1, "element_type": 1, "now_cost": 55, "status": "a", "total_points": 100},
            {"id": 2, "web_name": "Pickford", "team": 2, "element_type": 1, "now_cost": 50, "status": "a", "total_points": 90},
        ]
        + [
            {
                "id": k,
                "web_name": f"P{k}",
                "team": (k % 6) + 1,
                "element_type": 1 if k == 4 else (2 if k < 10 else (3 if k < 15 else 4)),
                "now_cost": 50,
                "status": "a",
                "total_points": 50,
            }
            for k in range(4, 18)
        ],
    }
    store.save_snapshot(bootstrap, [], utc_timestamp())

    squad_data = {
        "season": "2026/27",
        "player_ids": [1] + list(range(4, 18)),
        "purchase_prices_tenths": {str(k): 50 for k in [1] + list(range(4, 18))},
        "bank_tenths": 10,
        "free_transfers": 1,
        "chips_remaining": ["wildcard"],
        "gameweek": 3,
    }
    squad_file.write_text(json.dumps(squad_data), encoding="utf-8")

    res = execute_transfers(squad_file, [(1, 2)], database_path=db_path, gameweek=3)
    assert res["success"] is True
    assert res["free_transfers"] == 0
    assert 2 in res["new_player_ids"]
    assert 1 not in res["new_player_ids"]

    updated = load_current_squad(squad_file)
    assert 2 in updated.player_ids
    assert 1 not in updated.player_ids
    assert updated.purchase_price(2) == 50
    assert updated.free_transfers == 0


def test_validate_transfers_crossed_positions_realigned() -> None:
    # Squad has player 3 (DEF) and player 8 (MID)
    players, state = squad_and_state()
    # Add candidate player 16 (MID) and player 17 (DEF)
    players.extend([make_player(16, Position.MIDFIELDER, 6, 50), make_player(17, Position.DEFENDER, 6, 50)])
    # Submit crossed pairs: player 3 (DEF) -> player 16 (MID), player 8 (MID) -> player 17 (DEF)
    result = validate_transfers(state, players, [Transfer(3, 16), Transfer(8, 17)])
    assert result.is_valid
    assert result.bank_after_tenths == 10


def test_resolve_chained_transfers_single_chain() -> None:
    """Player A -> Player B and subsequently Player B -> Player C counts as Player A -> Player C."""
    # Transfer objects
    txs = [Transfer(outgoing_id=1, incoming_id=2), Transfer(outgoing_id=2, incoming_id=3)]
    resolved = resolve_chained_transfers(txs)
    assert len(resolved) == 1
    assert resolved[0].outgoing_id == 1
    assert resolved[0].incoming_id == 3

    # Dict format with metadata
    tx_dicts = [
        {
            "outgoing_id": 1,
            "outgoing_name": "Player A",
            "outgoing_team": 1,
            "outgoing_purchase_price_tenths": 45,
            "selling_price_tenths": 50,
            "incoming_id": 2,
            "incoming_name": "Player B",
            "incoming_team": 2,
            "purchase_price_tenths": 55,
        },
        {
            "outgoing_id": 2,
            "outgoing_name": "Player B",
            "outgoing_team": 2,
            "outgoing_purchase_price_tenths": 55,
            "selling_price_tenths": 55,
            "incoming_id": 3,
            "incoming_name": "Player C",
            "incoming_team": 3,
            "purchase_price_tenths": 60,
        },
    ]
    resolved_dict = resolve_chained_transfers(tx_dicts)
    assert len(resolved_dict) == 1
    rec = resolved_dict[0]
    assert rec["outgoing_id"] == 1
    assert rec["outgoing_name"] == "Player A"
    assert rec["outgoing_purchase_price_tenths"] == 45
    assert rec["selling_price_tenths"] == 50
    assert rec["incoming_id"] == 3
    assert rec["incoming_name"] == "Player C"
    assert rec["incoming_team"] == 3
    assert rec["purchase_price_tenths"] == 60


def test_chained_logical_transactions_preserve_identities_without_transformation() -> None:
    """Explicitly verify that chained logical transactions do not accidentally transform into a different transfer set."""
    # T1: 1 (DEF) -> 2 (DEF)
    # T2: 3 (DEF) -> 4 (DEF)
    # Subsequently T3: 2 (DEF) -> 5 (DEF)
    txs = [
        Transfer(outgoing_id=1, incoming_id=2),
        Transfer(outgoing_id=3, incoming_id=4),
        Transfer(outgoing_id=2, incoming_id=5),
    ]
    resolved = resolve_chained_transfers(txs)
    assert len(resolved) == 2
    # Chain 1 must strictly resolve 1 -> 5
    # Chain 2 must strictly remain 3 -> 4
    pairs = [(t.outgoing_id, t.incoming_id) for t in resolved]
    assert (1, 5) in pairs
    assert (3, 4) in pairs
    # Explicitly test that it did NOT accidentally transform into cross-pairs
    assert (1, 4) not in pairs
    assert (3, 5) not in pairs

    # Further chain: T4: 4 (DEF) -> 6 (DEF)
    txs_extended = txs + [Transfer(outgoing_id=4, incoming_id=6)]
    resolved_ext = resolve_chained_transfers(txs_extended)
    assert len(resolved_ext) == 2
    pairs_ext = [(t.outgoing_id, t.incoming_id) for t in resolved_ext]
    assert (1, 5) in pairs_ext
    assert (3, 6) in pairs_ext
    assert (1, 6) not in pairs_ext
    assert (3, 5) not in pairs_ext


def test_resolve_chained_transfers_cancellation_and_splice() -> None:
    """Reversing a transfer cancels out to 0 net transfers; transitive chains splice properly."""
    # A -> B followed by B -> A cancels out
    assert resolve_chained_transfers([Transfer(1, 2), Transfer(2, 1)]) == []

    # 1 -> 2, 3 -> 4, 2 -> 3 splices into 1 -> 4
    spliced = resolve_chained_transfers([
        Transfer(outgoing_id=1, incoming_id=2),
        Transfer(outgoing_id=3, incoming_id=4),
        Transfer(outgoing_id=2, incoming_id=3),
    ])
    assert len(spliced) == 1
    assert spliced[0].outgoing_id == 1
    assert spliced[0].incoming_id == 4


def test_validate_transfers_with_chained_transfers() -> None:
    """validate_transfers correctly consolidates A -> B and B -> C into a single transfer."""
    players, state = squad_and_state()
    players.extend([
        make_player(16, Position.GOALKEEPER, 6, 52),
        make_player(17, Position.GOALKEEPER, 6, 55),
    ])
    # Player 1 is in squad; player 16 and 17 are candidates
    result = validate_transfers(state, players, [Transfer(1, 16), Transfer(16, 17)])
    assert result.is_valid
    # 1 free transfer available, 1 net transfer executed -> 0 hits
    assert result.transfer_hits == 0
    # Bank starts at 10; Raya (1) sold at 50, P17 bought at 55 -> bank 5
    assert result.bank_after_tenths == 5


def test_execute_transfers_chained_sequential_in_same_gameweek(tmp_path: Path) -> None:
    """Executing A -> B and subsequently B -> C in the same gameweek counts as only 1 transfer."""
    from fpl_manager.decision_log import get_gameweek_decision
    from fpl_manager.squad_state import load_current_squad
    from fpl_manager.transfers import execute_transfers

    db_path = tmp_path / "fpl.sqlite3"
    squad_file = tmp_path / "current_squad.json"

    store = SnapshotStore(db_path)
    bootstrap = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Manchester City", "short_name": "MCI"},
            {"id": 3, "name": "Liverpool", "short_name": "LIV"},
            {"id": 4, "name": "Chelsea", "short_name": "CHE"},
            {"id": 5, "name": "Tottenham", "short_name": "TOT"},
            {"id": 6, "name": "Newcastle", "short_name": "NEW"},
        ],
        "elements": [
            {"id": 1, "web_name": "Raya", "team": 1, "element_type": 1, "now_cost": 50, "status": "a", "total_points": 100},
            {"id": 2, "web_name": "Pickford", "team": 2, "element_type": 1, "now_cost": 50, "status": "a", "total_points": 90},
            {"id": 3, "web_name": "Alisson", "team": 3, "element_type": 1, "now_cost": 50, "status": "a", "total_points": 95},
        ]
        + [
            {
                "id": k,
                "web_name": f"P{k}",
                "team": (k % 6) + 1,
                "element_type": 1 if k == 4 else (2 if k < 10 else (3 if k < 15 else 4)),
                "now_cost": 50,
                "status": "a",
                "total_points": 50,
            }
            for k in range(4, 25)
        ],
    }
    store.save_snapshot(bootstrap, [], utc_timestamp())

    squad_data = {
        "season": "2026/27",
        "player_ids": [1] + list(range(4, 18)),
        "purchase_prices_tenths": {str(k): 50 for k in [1] + list(range(4, 18))},
        "bank_tenths": 20,
        "free_transfers": 1,
        "chips_remaining": ["wildcard"],
        "gameweek": 3,
    }
    squad_file.write_text(json.dumps(squad_data), encoding="utf-8")

    # Call 1: User transfers Raya (1) -> Pickford (2)
    res1 = execute_transfers(squad_file, [(1, 2)], database_path=db_path, gameweek=3)
    assert res1["success"] is True
    assert len(res1["transfers"]) == 1
    assert res1["transfers"][0]["outgoing_id"] == 1
    assert res1["transfers"][0]["incoming_id"] == 2
    assert res1["transfer_hits"] == 0
    assert res1["free_transfers"] == 0

    dec1 = get_gameweek_decision(3, database_path=db_path)
    assert dec1 is not None
    assert len(dec1["transfers"]) == 1
    assert dec1["transfer_hits"] == 0

    # Call 2: In the same GW, user changes their mind and transfers Pickford (2) -> Alisson (3)
    res2 = execute_transfers(squad_file, [(2, 3)], database_path=db_path, gameweek=3)
    assert res2["success"] is True
    # The chain 1 -> 2 -> 3 must consolidate to exactly 1 transfer: 1 -> 3
    assert len(res2["transfers"]) == 1
    assert res2["transfers"][0]["outgoing_id"] == 1
    assert res2["transfers"][0]["incoming_id"] == 3
    # Must count as only 1 transfer and NOT two, hence 0 transfer hits
    assert res2["transfer_hits"] == 0
    assert res2["free_transfers"] == 0

    # Verify database decision record reflects only 1 transfer and 0 hits
    dec2 = get_gameweek_decision(3, database_path=db_path)
    assert dec2 is not None
    assert len(dec2["transfers"]) == 1
    assert dec2["transfers"][0]["outgoing_id"] == 1
    assert dec2["transfers"][0]["incoming_id"] == 3
    assert dec2["transfer_hits"] == 0

    # Verify squad file state
    sq = load_current_squad(squad_file)
    assert 3 in sq.player_ids
    assert 2 not in sq.player_ids
    assert 1 not in sq.player_ids
    assert sq.free_transfers == 0


def test_execute_transfers_chained_multi_player_preserves_transfer_set(tmp_path: Path) -> None:
    """Multiple chained transfers preserve distinct logical paths without cross-contamination."""
    from fpl_manager.decision_log import get_gameweek_decision
    from fpl_manager.transfers import execute_transfers

    db_path = tmp_path / "fpl.sqlite3"
    squad_file = tmp_path / "current_squad.json"

    store = SnapshotStore(db_path)
    bootstrap = {
        "teams": [
            {"id": 1, "name": "Team 1", "short_name": "T1"},
            {"id": 2, "name": "Team 2", "short_name": "T2"},
            {"id": 3, "name": "Team 3", "short_name": "T3"},
            {"id": 4, "name": "Team 4", "short_name": "T4"},
            {"id": 5, "name": "Team 5", "short_name": "T5"},
            {"id": 6, "name": "Team 6", "short_name": "T6"},
        ],
        "elements": [
            {
                "id": k,
                "web_name": f"P{k}",
                "team": ((k - 1) % 5) + 1,
                "element_type": 1 if k <= 2 else (2 if k <= 7 else (3 if k <= 12 else 4)),
                "now_cost": 50,
                "status": "a",
                "total_points": 50,
            }
            for k in range(1, 16)
        ]
        + [
            # Candidate DEF outside squad: 16 (team 6), 17 (team 6), 18 (team 6)
            {"id": 16, "web_name": "Candidate_16", "team": 6, "element_type": 2, "now_cost": 50, "status": "a", "total_points": 50},
            {"id": 17, "web_name": "Candidate_17", "team": 6, "element_type": 2, "now_cost": 50, "status": "a", "total_points": 50},
            {"id": 18, "web_name": "Candidate_18", "team": 6, "element_type": 2, "now_cost": 50, "status": "a", "total_points": 50},
        ],
    }
    store.save_snapshot(bootstrap, [], utc_timestamp())

    # Squad has DEF 4 and DEF 5
    squad_data = {
        "season": "2026/27",
        "player_ids": list(range(1, 16)),
        "purchase_prices_tenths": {str(k): 50 for k in range(1, 16)},
        "bank_tenths": 30,
        "free_transfers": 1,
        "chips_remaining": [],
        "gameweek": 3,
    }
    squad_file.write_text(json.dumps(squad_data), encoding="utf-8")

    # Call 1: Move 4 -> 16 (DEF -> DEF) and 5 -> 17 (DEF -> DEF)
    res1 = execute_transfers(squad_file, [(4, 16), (5, 17)], database_path=db_path, gameweek=3)
    assert res1["success"] is True
    assert len(res1["transfers"]) == 2
    assert res1["transfer_hits"] == 1  # 2 tx - 1 FT = 1 hit

    # Call 2: Subsequently move 16 -> 18 (DEF -> DEF)
    res2 = execute_transfers(squad_file, [(16, 18)], database_path=db_path, gameweek=3)
    assert res2["success"] is True
    # 4 -> 16 -> 18 should become 4 -> 18; 5 -> 17 remains 5 -> 17. Total 2 transfers!
    assert len(res2["transfers"]) == 2
    pairs = [(t["outgoing_id"], t["incoming_id"]) for t in res2["transfers"]]
    assert (4, 18) in pairs
    assert (5, 17) in pairs
    # Explicitly verify they did not cross-transform into (4, 17) and (5, 18)
    assert (4, 17) not in pairs
    assert (5, 18) not in pairs
    # 2 net transfers with 1 FT = 1 hit (NOT 3 transfers with 1 FT = 2 hits!)
    assert res2["transfer_hits"] == 1

    dec = get_gameweek_decision(3, database_path=db_path)
    assert dec is not None
    assert len(dec["transfers"]) == 2
    assert dec["transfer_hits"] == 1
