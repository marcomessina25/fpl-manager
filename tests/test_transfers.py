import json
from pathlib import Path
import pytest

from fpl_manager.cli import validate_transfer_set
from fpl_manager.models import Player, Position
from fpl_manager.squad_state import CurrentSquadState
from fpl_manager.storage import SnapshotStore, utc_timestamp
from fpl_manager.transfers import Transfer, selling_price, validate_transfers


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

