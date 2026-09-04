"""Utility for automatically importing squad players from a text file into current_squad.json."""

import json
from pathlib import Path
from typing import Any

from .fixtures import get_current_gameweek
from .storage import SnapshotStore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
DEFAULT_PLAYERS_PATH = PROJECT_ROOT / "players.txt"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"
EXAMPLE_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.example.json"


def search_player_exact_or_single(store: SnapshotStore, query: str) -> dict[str, Any] | None:
    """Find a single matching player from snapshot store by search query.

    Returns player dict if exactly 1 match found (or 1 exact web_name match).
    Returns None if 0 matches or >1 ambiguous matches are found.
    """
    matches = store.search_latest_players(query)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        exact_matches = [m for m in matches if m["name"].strip().lower() == query.strip().lower()]
        if len(exact_matches) == 1:
            return exact_matches[0]
    return None


def import_squad_from_file(
    players_path: Path = DEFAULT_PLAYERS_PATH,
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    """Read players.txt line-by-line, fetch FPL IDs/prices, log status, and update current_squad.json."""
    if not players_path.is_file():
        raise RuntimeError(f"Players file not found: {players_path}")

    store = SnapshotStore(database_path)
    lines = players_path.read_text(encoding="utf-8").splitlines()

    imported_players: list[dict[str, Any]] = []

    for line in lines:
        query = line.strip()
        if not query or query.startswith("#"):
            continue

        match = search_player_exact_or_single(store, query)
        if match is not None:
            player_id = match["id"]
            name = match["name"]
            team = match["team"]
            price = match["price_tenths"]
            print(f"importing id {player_id} player {name} team {team} price {price}")
            imported_players.append(match)
        else:
            print(f"failed importing player {query}")

    # Load existing squad JSON base, fallback to example file, or fallback to standard default structure
    if squad_path.is_file():
        squad_data = json.loads(squad_path.read_text(encoding="utf-8"))
    elif EXAMPLE_SQUAD_PATH.is_file():
        squad_data = json.loads(EXAMPLE_SQUAD_PATH.read_text(encoding="utf-8"))
    else:
        squad_data = {
            "season": "2026/27",
            "player_ids": [],
            "purchase_prices_tenths": {},
            "bank_tenths": 0,
            "free_transfers": 1,
            "chips_remaining": ["wildcard_1", "wildcard_2", "free_hit", "bench_boost", "triple_captain"],
        }

    squad_data["player_ids"] = [p["id"] for p in imported_players]
    squad_data["purchase_prices_tenths"] = {str(p["id"]): p["price_tenths"] for p in imported_players}
    if "gameweek" not in squad_data:
        try:
            squad_data["gameweek"] = get_current_gameweek(store)
        except Exception:
            squad_data["gameweek"] = 1

    squad_path.parent.mkdir(parents=True, exist_ok=True)
    squad_path.write_text(json.dumps(squad_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return squad_data
