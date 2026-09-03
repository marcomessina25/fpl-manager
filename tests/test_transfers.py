from fpl_manager.models import Player, Position
from fpl_manager.squad_state import CurrentSquadState
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
