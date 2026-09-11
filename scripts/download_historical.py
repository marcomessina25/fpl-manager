#!/usr/bin/env python3
"""Utility script to download historical FPL season data to data/historical.

Examples:
    python scripts/download_historical.py --season 2021-22
    python scripts/download_historical.py 2021-22
    python scripts/download_historical.py --season 2021-22 --overwrite
    python scripts/download_historical.py --season 2021-22 --raw-only
"""

import argparse
import sys
from pathlib import Path

# Ensure 'src' directory is in sys.path when script is executed directly
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fpl_manager.historical.ingestion import (
    DEFAULT_HISTORICAL_DIR,
    DEFAULT_HISTORICAL_RAW_DIR,
    SeasonManifest,
    download_historical_season,
    normalize_season_name,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Download and normalize historical FPL season data to data/historical/<season>"
    )
    parser.add_argument(
        "season_pos",
        nargs="?",
        default=None,
        metavar="SEASON",
        help="Season identifier (e.g. 2021-22, 2022-23)",
    )
    parser.add_argument(
        "--season",
        "-s",
        type=str,
        default=None,
        help="Season identifier in YYYY-YY format (e.g. 2021-22, 2022-23)",
    )
    parser.add_argument(
        "--dest-dir",
        "--output-dir",
        "-o",
        type=Path,
        default=None,
        help="Target directory for normalized JSON files (default: data/historical/<season>)",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=None,
        help="Target directory for raw CSV downloads (default: data/historical/raw/<season>)",
    )
    parser.add_argument(
        "--max-gameweeks",
        type=int,
        default=38,
        help="Maximum number of gameweeks to download (default: 38)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Network request timeout in seconds (default: 15.0)",
    )
    parser.add_argument(
        "--overwrite",
        "-f",
        "--force",
        action="store_true",
        help="Overwrite previously downloaded/ingested files",
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="Download raw CSV files only, skipping normalization into JSON format",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress messages",
    )

    args = parser.parse_args(argv)
    raw_season = args.season or args.season_pos
    if not raw_season:
        parser.error("A season must be specified via --season or as a positional argument (e.g., --season 2021-22).")

    season = normalize_season_name(raw_season)
    dest_dir = args.dest_dir or (DEFAULT_HISTORICAL_DIR / season)
    raw_dir = args.raw_dir or (DEFAULT_HISTORICAL_RAW_DIR / season)

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg)

    log(f"Downloading historical data for season '{season}'...")
    log(f"  Raw CSV target:  {raw_dir}")
    if not args.raw_only:
        log(f"  Normalized JSON: {dest_dir}")

    try:
        result = download_historical_season(
            season=season,
            output_dir=dest_dir,
            raw_dir=raw_dir,
            max_gameweeks=args.max_gameweeks,
            timeout_seconds=args.timeout,
            overwrite=args.overwrite,
            raw_only=args.raw_only,
            progress_callback=log,
        )

        if isinstance(result, SeasonManifest):
            log(f"\nSuccessfully downloaded and ingested season '{season}':")
            log(f"  - Gameweeks: {result.total_gameweeks}")
            log(f"  - Players:   {result.num_players}")
            log(f"  - Teams:     {result.num_teams}")
            log(f"  - Fixtures:  {result.num_fixtures}")
            log(f"  - Location:  {dest_dir}")
        else:
            log(f"\nSuccessfully downloaded raw data for season '{season}' to {result}")

    except Exception as error:
        sys.stdout.flush()
        print(f"\nError: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
