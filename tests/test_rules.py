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


def test_allows_squad_costing_more_than_100m_by_default() -> None:
    # During an ongoing season, player price rises can easily push total squad value above £100.0m.
    squad_expensive = [player(p.id, p.position, p.team_id, price=70) for p in legal_squad()]
    total_cost = sum(p.price_tenths for p in squad_expensive)
    assert total_cost == 1050  # £105.0m
    # Without budget_tenths, structural FPL rules are validated without enforcing the starting £100.0m cap
    assert validate_squad(squad_expensive).is_valid
    # But when budget_tenths is explicitly enforced, it is rejected
    res = validate_squad(squad_expensive, budget_tenths=1000)
    assert not res.is_valid
    assert "exceeding the £100.0m budget" in " ".join(res.errors)


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


def test_is_free_transfers_chip() -> None:
    from fpl_manager.rules import is_free_transfers_chip

    # Wildcard variants
    assert is_free_transfers_chip("wildcard") is True
    assert is_free_transfers_chip("WILDCARD") is True
    assert is_free_transfers_chip("Wildcard") is True
    assert is_free_transfers_chip("wildcard_1") is True
    assert is_free_transfers_chip("wildcard_2") is True
    assert is_free_transfers_chip("wildcard1") is True
    assert is_free_transfers_chip("wildcard2") is True
    assert is_free_transfers_chip("wc") is True
    assert is_free_transfers_chip("WC") is True

    # Free Hit variants
    assert is_free_transfers_chip("freehit") is True
    assert is_free_transfers_chip("FREEHIT") is True
    assert is_free_transfers_chip("free_hit") is True
    assert is_free_transfers_chip("Free_Hit") is True
    assert is_free_transfers_chip("fh") is True
    assert is_free_transfers_chip("FH") is True

    # Negative / other chips
    assert is_free_transfers_chip(None) is False
    assert is_free_transfers_chip("") is False
    assert is_free_transfers_chip("bench_boost") is False
    assert is_free_transfers_chip("triple_captain") is False
    assert is_free_transfers_chip("bb") is False
    assert is_free_transfers_chip("tc") is False
    assert is_free_transfers_chip("unknown") is False


def test_solve_transfers_enforces_strict_team_quota_with_midseason_excess() -> None:
    """When real-world mid-season transfers cause a squad to exceed 3 players from a club (e.g. 5 MCI players),
    solve_transfers MUST only return moves that restore compliance (<= 3 per club).
    1 transfer cannot resolve 5 players -> returns 0 moves.
    2 transfers selling 2 MCI players -> all returned moves must have <= 3 MCI players.
    """
    from collections import Counter
    from fpl_manager.optimizer import solve_transfers
    from fpl_manager.suggest_transfers import PlayerInfo

    # Create 15 squad players where team 13 (MCI) has 5 players (2 DEF, 2 MID, 1 FWD)
    squad = []
    # 2 GKP (teams 1, 2)
    squad.append(PlayerInfo(id=1, name="GKP1", position=Position.GOALKEEPER, team_id=1, team_short="ARS", price_tenths=50, status="a", expected_points=4.0, total_points=50, xp_floor=3.0, xp_ceiling=5.0, expected_minutes=90))
    squad.append(PlayerInfo(id=2, name="GKP2", position=Position.GOALKEEPER, team_id=2, team_short="AVL", price_tenths=45, status="a", expected_points=3.5, total_points=40, xp_floor=2.0, xp_ceiling=4.0, expected_minutes=90))
    # 5 DEF (2 MCI: id 3, 4; others teams 3, 4, 5)
    squad.append(PlayerInfo(id=3, name="MCI DEF 1", position=Position.DEFENDER, team_id=13, team_short="MCI", price_tenths=55, status="a", expected_points=4.5, total_points=60, xp_floor=3.0, xp_ceiling=6.0, expected_minutes=90))
    squad.append(PlayerInfo(id=4, name="MCI DEF 2", position=Position.DEFENDER, team_id=13, team_short="MCI", price_tenths=50, status="a", expected_points=4.0, total_points=50, xp_floor=2.5, xp_ceiling=5.5, expected_minutes=90))
    squad.append(PlayerInfo(id=5, name="DEF 3", position=Position.DEFENDER, team_id=3, team_short="CHE", price_tenths=50, status="a", expected_points=4.0, total_points=50, xp_floor=2.5, xp_ceiling=5.5, expected_minutes=90))
    squad.append(PlayerInfo(id=6, name="DEF 4", position=Position.DEFENDER, team_id=4, team_short="LIV", price_tenths=50, status="a", expected_points=4.0, total_points=50, xp_floor=2.5, xp_ceiling=5.5, expected_minutes=90))
    squad.append(PlayerInfo(id=7, name="DEF 5", position=Position.DEFENDER, team_id=5, team_short="NEW", price_tenths=45, status="a", expected_points=3.5, total_points=40, xp_floor=2.0, xp_ceiling=4.5, expected_minutes=90))
    # 5 MID (2 MCI: id 8, 9; others teams 6, 7, 8)
    squad.append(PlayerInfo(id=8, name="MCI MID 1", position=Position.MIDFIELDER, team_id=13, team_short="MCI", price_tenths=80, status="a", expected_points=5.5, total_points=80, xp_floor=4.0, xp_ceiling=8.0, expected_minutes=90))
    squad.append(PlayerInfo(id=9, name="MCI MID 2", position=Position.MIDFIELDER, team_id=13, team_short="MCI", price_tenths=75, status="a", expected_points=5.0, total_points=70, xp_floor=3.5, xp_ceiling=7.0, expected_minutes=90))
    squad.append(PlayerInfo(id=10, name="MID 3", position=Position.MIDFIELDER, team_id=6, team_short="TOT", price_tenths=70, status="a", expected_points=4.5, total_points=65, xp_floor=3.0, xp_ceiling=6.5, expected_minutes=90))
    squad.append(PlayerInfo(id=11, name="MID 4", position=Position.MIDFIELDER, team_id=7, team_short="BHA", price_tenths=60, status="a", expected_points=4.0, total_points=55, xp_floor=2.5, xp_ceiling=5.5, expected_minutes=90))
    squad.append(PlayerInfo(id=12, name="MID 5", position=Position.MIDFIELDER, team_id=8, team_short="FUL", price_tenths=55, status="a", expected_points=3.5, total_points=45, xp_floor=2.0, xp_ceiling=5.0, expected_minutes=90))
    # 3 FWD (1 MCI: id 13; others teams 9, 10)
    squad.append(PlayerInfo(id=13, name="MCI FWD 1", position=Position.FORWARD, team_id=13, team_short="MCI", price_tenths=140, status="a", expected_points=7.5, total_points=120, xp_floor=5.0, xp_ceiling=10.0, expected_minutes=90))
    squad.append(PlayerInfo(id=14, name="FWD 2", position=Position.FORWARD, team_id=9, team_short="BRE", price_tenths=70, status="a", expected_points=4.5, total_points=60, xp_floor=3.0, xp_ceiling=6.0, expected_minutes=90))
    squad.append(PlayerInfo(id=15, name="FWD 3", position=Position.FORWARD, team_id=10, team_short="WOL", price_tenths=60, status="a", expected_points=4.0, total_points=50, xp_floor=2.5, xp_ceiling=5.5, expected_minutes=90))

    # Verify initial squad has 5 MCI players
    assert sum(1 for p in squad if p.team_id == 13) == 5

    candidate_pool = [
        PlayerInfo(id=101, name="Cand DEF", position=Position.DEFENDER, team_id=1, team_short="ARS", price_tenths=50, status="a", expected_points=4.8, total_points=55, xp_floor=3.0, xp_ceiling=6.0, expected_minutes=90),
        PlayerInfo(id=102, name="Cand MID", position=Position.MIDFIELDER, team_id=3, team_short="CHE", price_tenths=70, status="a", expected_points=5.8, total_points=75, xp_floor=4.0, xp_ceiling=8.0, expected_minutes=90),
        PlayerInfo(id=103, name="Cand FWD", position=Position.FORWARD, team_id=6, team_short="TOT", price_tenths=70, status="a", expected_points=5.0, total_points=65, xp_floor=3.0, xp_ceiling=7.0, expected_minutes=90),
    ]

    selling_prices = {p.id: p.price_tenths for p in squad}

    # 1 transfer cannot resolve the 5-player excess -> must return 0 moves
    results_1, _ = solve_transfers(
        num_transfers=1,
        squad_players=squad,
        candidate_pool=candidate_pool,
        bank_tenths=20,
        free_transfers=1,
        selling_prices=selling_prices,
        fdr_map={},
        ticker_map={},
    )
    assert len(results_1) == 0

    # 2 transfers can resolve the excess by selling 2 MCI players
    results_2, _ = solve_transfers(
        num_transfers=2,
        squad_players=squad,
        candidate_pool=candidate_pool,
        bank_tenths=20,
        free_transfers=1,
        selling_prices=selling_prices,
        fdr_map={},
        ticker_map={},
    )
    assert len(results_2) > 0
    for r in results_2:
        out_ids = {p["id"] for p in r["outgoing"]}
        in_ids = {p["id"] for p in r["incoming"]}
        new_squad = [p for p in squad if p.id not in out_ids] + [p for p in candidate_pool if p.id in in_ids]
        counts = Counter(p.team_id for p in new_squad)
        assert all(c <= 3 for c in counts.values()), f"Illegal move found with team counts: {counts}"


