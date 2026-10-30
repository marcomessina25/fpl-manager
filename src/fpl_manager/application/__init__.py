"""Framework-neutral command API; existing JSON state remains authoritative.

Wrap public mutations in ``CommandBus(path).execute(context, operation, payload,
lambda: mutation())`` and return ``receipt.result`` for legacy response schemas.
Nested public mutations may call ``active_command(context)`` and reuse the
outer action; do not open another transaction or publish files themselves.

For historical commands pass the dedicated
``config/simulations/command_journal.sqlite3`` control path, not the live DB.
Startup can initialize explicitly. Reads never migrate schema or recover
implicitly. A committed-but-unpublished command raises RecoveryRequiredError:
call ``recover()`` on its bus or retry its exact command ID.
"""

from .commands import BorrowedConnection, CommandBus, CommandScope, active_command, ambient_connection
from .contexts import CommandContext, HistoricalContext, LiveContext
from .errors import (
    CommandContextError,
    IdempotencyConflictError,
    InvalidCommandError,
    RecoveryConflictError,
    RecoveryRequiredError,
    StaleRevisionError,
)
from .files import delete_state_file, read_state_text, state_file_exists, write_state_text
from .journal import CommandReceipt

__all__ = [
    "BorrowedConnection", "CommandBus", "CommandContext", "CommandContextError", "CommandReceipt",
    "CommandScope", "HistoricalContext", "IdempotencyConflictError", "InvalidCommandError",
    "LiveContext", "RecoveryConflictError", "RecoveryRequiredError", "StaleRevisionError",
    "active_command", "ambient_connection", "delete_state_file", "read_state_text", "state_file_exists",
    "write_state_text",
]
