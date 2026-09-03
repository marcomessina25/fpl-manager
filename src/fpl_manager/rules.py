"""Pure FPL legality checks. Recommendations must pass these checks."""

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .models import Player, Position


SQUAD_SIZE = 15
MAX_BUDGET_TENTHS = 1000
MAX_PLAYERS_PER_TEAM = 3
SQUAD_QUOTAS = {
    Position.GOALKEEPER: 2,
    Position.DEFENDER: 5,
    Position.MIDFIELDER: 5,
    Position.FORWARD: 3,
}
MIN_STARTING_QUOTAS = {
    Position.GOALKEEPER: 1,
    Position.DEFENDER: 3,
    Position.MIDFIELDER: 2,
    Position.FORWARD: 1,
}


@dataclass(frozen=True, slots=True)
class ValidationResult:
    errors: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.errors


def validate_squad(players: Iterable[Player], budget_tenths: int = MAX_BUDGET_TENTHS) -> ValidationResult:
    """Validate a complete 15-player squad against fixed FPL constraints."""
    squad = tuple(players)
    errors: list[str] = []
    ids = [player.id for player in squad]

    if len(squad) != SQUAD_SIZE:
        errors.append(f"A squad must contain {SQUAD_SIZE} players; received {len(squad)}.")
    if len(set(ids)) != len(ids):
        errors.append("A squad cannot contain the same player more than once.")

    total_cost = sum(player.price_tenths for player in squad)
    if total_cost > budget_tenths:
        errors.append(
            f"Squad costs £{total_cost / 10:.1f}m, exceeding the £{budget_tenths / 10:.1f}m budget."
        )

    positions = Counter(player.position for player in squad)
    for position, required in SQUAD_QUOTAS.items():
        actual = positions[position]
        if actual != required:
            errors.append(f"Squad requires {required} {position.name.lower()}s; received {actual}.")

    teams = Counter(player.team_id for player in squad)
    for team_id, count in sorted(teams.items()):
        if count > MAX_PLAYERS_PER_TEAM:
            errors.append(f"Team {team_id} has {count} players; maximum is {MAX_PLAYERS_PER_TEAM}.")

    return ValidationResult(tuple(errors))


def validate_starting_lineup(squad: Iterable[Player], starters: Iterable[int]) -> ValidationResult:
    """Validate 11 starter IDs, including legal formation constraints."""
    squad_by_id = {player.id: player for player in squad}
    starter_ids = tuple(starters)
    errors: list[str] = []

    if len(starter_ids) != 11:
        errors.append(f"A starting lineup must contain 11 players; received {len(starter_ids)}.")
    if len(set(starter_ids)) != len(starter_ids):
        errors.append("A starting lineup cannot contain the same player more than once.")

    unknown_ids = sorted(set(starter_ids) - set(squad_by_id))
    if unknown_ids:
        errors.append(f"Starting lineup contains players outside the squad: {unknown_ids}.")

    known_starters = [squad_by_id[player_id] for player_id in starter_ids if player_id in squad_by_id]
    positions = Counter(player.position for player in known_starters)
    for position, minimum in MIN_STARTING_QUOTAS.items():
        actual = positions[position]
        if actual < minimum:
            errors.append(f"Starting lineup requires at least {minimum} {position.name.lower()}s; received {actual}.")

    return ValidationResult(tuple(errors))
