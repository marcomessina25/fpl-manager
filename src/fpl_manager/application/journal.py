"""SQLite journal format and JSON-only durable receipts.

The journal lives beside business tables in live mode, and in the simulation
control database in historical mode. A pending row always means SQL committed:
recovery rolls files forward, never attempts to undo business SQL.
"""

import json
import math
import sqlite3
from dataclasses import dataclass
from typing import Any

from .errors import InvalidCommandError


SCHEMA = """
CREATE TABLE IF NOT EXISTS application_revisions (
    context_key TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision >= 0)
);
CREATE TABLE IF NOT EXISTS application_commands (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    command_id TEXT NOT NULL UNIQUE,
    context_key TEXT NOT NULL,
    context_json TEXT NOT NULL,
    operation TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    receipt_json TEXT NOT NULL,
    files_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'complete'))
);
CREATE INDEX IF NOT EXISTS application_commands_pending
    ON application_commands(state, sequence);
"""


def normalize_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidCommandError("Command JSON cannot contain nonfinite numbers.")
        return value
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise InvalidCommandError("Command JSON object keys must be strings.")
        return {key: normalize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_json(item) for item in value]
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        return normalize_json(converter())
    raise InvalidCommandError(f"Unsupported command JSON type: {type(value).__name__}.")


def json_text(value: Any) -> str:
    try:
        return json.dumps(normalize_json(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (RecursionError, ValueError) as error:
        raise InvalidCommandError("Command JSON must be finite and acyclic.") from error


@dataclass(frozen=True)
class CommandReceipt:
    result: Any
    revision_before: int
    revision_after: int
    command_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "revision_before": self.revision_before,
            "revision_after": self.revision_after,
            "command_id": self.command_id,
        }

    @classmethod
    def from_json(cls, text: str) -> "CommandReceipt":
        return cls(**json.loads(text))


def has_schema(connection: sqlite3.Connection) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'application_commands'"
    ).fetchone() is not None
