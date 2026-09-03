"""Command-line entry points for the V0.1 local data engine."""

import argparse
import json
from pathlib import Path

from .api import fetch_current_data
from .storage import SnapshotStore, utc_timestamp, write_raw_snapshot


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
RAW_DIRECTORY = DATA_DIRECTORY / "raw"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
REPORT_PATH = PROJECT_ROOT / "reports" / "current_state.json"


def update() -> dict[str, object]:
    fetched_at = utc_timestamp()
    bootstrap, fixtures = fetch_current_data()
    write_raw_snapshot(RAW_DIRECTORY, "bootstrap-static", bootstrap, fetched_at)
    write_raw_snapshot(RAW_DIRECTORY, "fixtures", fixtures, fetched_at)
    store = SnapshotStore(DATABASE_PATH)
    snapshot_id = store.save_snapshot(bootstrap, fixtures, fetched_at)
    return {"snapshot_id": snapshot_id, "fetched_at": fetched_at, "players": len(bootstrap["elements"]), "fixtures": len(fixtures)}


def report() -> dict[str, object]:
    summary = SnapshotStore(DATABASE_PATH).latest_summary()
    if summary is None:
        raise RuntimeError("No FPL data found. Run `fpl update` first.")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(prog="fpl", description="Local-first FPL decision engine")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("update", help="Download and persist the latest official FPL data")
    subcommands.add_parser("report", help="Write a machine-readable summary of the latest snapshot")
    arguments = parser.parse_args()

    try:
        result = update() if arguments.command == "update" else report()
    except RuntimeError as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
