"""Command-line entry points for the V0.1 local data engine."""

import argparse
import json
from pathlib import Path

from .api import fetch_current_data
from .squad_state import load_current_squad
from .storage import SnapshotStore, utc_timestamp, write_raw_snapshot
from .transfers import Transfer, validate_transfers


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
RAW_DIRECTORY = DATA_DIRECTORY / "raw"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
REPORT_PATH = PROJECT_ROOT / "reports" / "current_state.json"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"


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


def validate_transfer_set(squad_path: Path, transfers: list[str]) -> dict[str, object]:
    parsed_transfers: list[Transfer] = []
    for value in transfers:
        try:
            outgoing, incoming = value.split(":", maxsplit=1)
            parsed_transfers.append(Transfer(int(outgoing), int(incoming)))
        except ValueError as error:
            raise RuntimeError(f"Invalid transfer '{value}'. Use OUTGOING_ID:INCOMING_ID.") from error
    state = load_current_squad(squad_path)
    result = validate_transfers(state, SnapshotStore(DATABASE_PATH).latest_players(), parsed_transfers)
    return {
        "is_valid": result.is_valid,
        "errors": list(result.errors),
        "bank_after_tenths": result.bank_after_tenths,
        "transfer_hits": result.transfer_hits,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="fpl", description="Local-first FPL decision engine")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("update", help="Download and persist the latest official FPL data")
    subcommands.add_parser("report", help="Write a machine-readable summary of the latest snapshot")
    players_parser = subcommands.add_parser("players", help="Find player IDs in the latest FPL snapshot")
    players_parser.add_argument("--search", required=True, help="Part of a player's displayed name")
    validate_parser = subcommands.add_parser("validate-transfers", help="Validate proposed transfers against the local squad state")
    validate_parser.add_argument("--squad", type=Path, default=DEFAULT_SQUAD_PATH, help="Private current-squad JSON path")
    validate_parser.add_argument("--transfer", action="append", required=True, help="Transfer as OUTGOING_ID:INCOMING_ID; repeat for multiple moves")
    arguments = parser.parse_args()

    try:
        if arguments.command == "update":
            result = update()
        elif arguments.command == "report":
            result = report()
        elif arguments.command == "players":
            result = {"players": SnapshotStore(DATABASE_PATH).search_latest_players(arguments.search)}
        else:
            result = validate_transfer_set(arguments.squad, arguments.transfer)
    except RuntimeError as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
