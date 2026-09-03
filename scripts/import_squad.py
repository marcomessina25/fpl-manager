#!/usr/bin/env python3
"""Utility script to automatically populate config/current_squad.json from players.txt."""

import argparse
import sys
from pathlib import Path

# Ensure 'src' directory is in sys.path when script is executed directly
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fpl_manager.import_squad import (
    DEFAULT_PLAYERS_PATH,
    DEFAULT_SQUAD_PATH,
    import_squad_from_file,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import squad player IDs and prices from a text file into current_squad.json"
    )
    parser.add_argument(
        "--players",
        type=Path,
        default=DEFAULT_PLAYERS_PATH,
        help="Path to input players text file (default: players.txt)",
    )
    parser.add_argument(
        "--squad",
        type=Path,
        default=DEFAULT_SQUAD_PATH,
        help="Path to target squad JSON file (default: config/current_squad.json)",
    )
    args = parser.parse_args()

    try:
        import_squad_from_file(players_path=args.players, squad_path=args.squad)
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
