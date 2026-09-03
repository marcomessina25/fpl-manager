from fpl_manager.models import Player, Position
from fpl_manager.rules import validate_squad, validate_starting_lineup


def player(player_id: int, position: Position, team_id: int, price: int = 50) -> Player:
    return Player(player_id, f"Player {player_id}", position, team_id, price)


def legal_squad() -> list[Player]:
    players: list[Player] = []
    player_id = 1
    for position, count in ((Position.GOALKEEPER, 2), (Position.DEFENDER, 5), (Position.MIDFIELDER, 5), (Position.FORWARD, 3)):
        for _ in range(count):
            players.append(player(player_id, position, ((player_id - 1) // 3) + 1))
            player_id += 1
    return players


def test_validates_legal_squad() -> None:
    assert validate_squad(legal_squad()).is_valid


def test_rejects_excessive_budget() -> None:
    assert "exceeding" in " ".join(validate_squad(legal_squad(), budget_tenths=749).errors)


def test_rejects_too_many_players_from_one_team() -> None:
    squad = legal_squad()
    squad[3] = player(squad[3].id, squad[3].position, 1)
    assert "maximum" in " ".join(validate_squad(squad).errors)


def test_validates_legal_starting_lineup() -> None:
    squad = legal_squad()
    starters = [1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14]
    assert validate_starting_lineup(squad, starters).is_valid


def test_rejects_illegal_formation() -> None:
    squad = legal_squad()
    starters = [1, 3, 4, 8, 9, 10, 11, 12, 13, 14, 15]
    assert "defenders" in " ".join(validate_starting_lineup(squad, starters).errors)
