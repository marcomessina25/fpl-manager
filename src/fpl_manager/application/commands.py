"""Synchronous command boundary for mixed SQLite and existing JSON state.

Actions take no arguments and use their ordinary SnapshotStore/state-file APIs.
Only the outer command owns commit/rollback. SQLite's write lock serializes
independent buses and processes; ContextVar state never shares a connection
between threads.
"""

import hashlib
import json
import logging
import sqlite3
import threading
from _thread import RLock
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from .contexts import CommandContext, HistoricalContext, LiveContext
from .errors import (
    CommandContextError,
    IdempotencyConflictError,
    InvalidCommandError,
    RecoveryRequiredError,
    StaleRevisionError,
)
from .files import FileStaging, publish_file
from .journal import SCHEMA, CommandReceipt, has_schema, json_text


_active: ContextVar["CommandScope | None"] = ContextVar("fpl_active_command", default=None)
LOGGER = logging.getLogger(__name__)
_locks: dict[Path, RLock] = {}
_locks_guard = threading.Lock()
SQLParameters = Sequence[Any] | Mapping[str, Any]


def _database_lock(path: Path) -> RLock:
    with _locks_guard:
        return _locks.setdefault(path, RLock())


class BorrowedCursor:
    """Keep cursor.connection from exposing a prematurely closable owner."""

    def __init__(self, cursor: sqlite3.Cursor, connection: "BorrowedConnection") -> None:
        self._cursor = cursor
        self.connection = connection

    def execute(self, sql: str, parameters: SQLParameters = ()) -> "BorrowedCursor":
        self._cursor.execute(sql, parameters)
        return self

    def executemany(self, sql: str, parameters: Iterable[SQLParameters]) -> "BorrowedCursor":
        self._cursor.executemany(sql, parameters)
        return self

    def executescript(self, sql: str) -> "BorrowedCursor":
        raise InvalidCommandError("executescript is not permitted inside commands; initialize schemas first.")

    def fetchone(self) -> Any:
        return self._cursor.fetchone()

    def fetchmany(self, size: int = 1) -> list[Any]:
        return self._cursor.fetchmany(size)

    def fetchall(self) -> list[Any]:
        return self._cursor.fetchall()

    @property
    def lastrowid(self) -> int | None:
        return self._cursor.lastrowid

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def description(self) -> Any:
        return self._cursor.description

    def close(self) -> None:
        self._cursor.close()

    def __iter__(self) -> "BorrowedCursor":
        return self

    def __next__(self) -> Any:
        return next(self._cursor)


class BorrowedConnection:
    """A transaction-neutral view of the command's owned SQLite connection.

    Legacy ``closing(conn)``, ``with conn`` and explicit commit/close calls are
    intentionally harmless. An exception or rollback marks the *outer* command
    rollback-only, including when a legacy caller subsequently catches it.
    """

    def __init__(self, scope: "CommandScope") -> None:
        self._scope = scope

    def _connection(self) -> sqlite3.Connection:
        self._scope.check_thread()
        return self._scope._connection

    def execute(self, sql: str, parameters: SQLParameters = ()) -> BorrowedCursor:
        return BorrowedCursor(self._connection().execute(sql, parameters), self)

    def executemany(self, sql: str, parameters: Iterable[SQLParameters]) -> BorrowedCursor:
        return BorrowedCursor(self._connection().executemany(sql, parameters), self)

    def executescript(self, sql: str) -> BorrowedCursor:
        raise InvalidCommandError("executescript is not permitted inside commands; initialize schemas first.")

    def cursor(self) -> BorrowedCursor:
        return BorrowedCursor(self._connection().cursor(), self)

    @property
    def row_factory(self) -> Any:
        return self._connection().row_factory

    @row_factory.setter
    def row_factory(self, factory: Any) -> None:
        self._connection().row_factory = factory

    @property
    def in_transaction(self) -> bool:
        return self._connection().in_transaction

    def commit(self) -> None:
        self._scope.check_thread()

    def rollback(self) -> None:
        self._scope.check_thread()
        self._scope.rollback_only = True

    def close(self) -> None:
        self._scope.check_thread()

    def __enter__(self) -> "BorrowedConnection":
        self._scope.check_thread()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if exc_type is not None:
            self.rollback()


@dataclass
class CommandScope:
    context: CommandContext
    database_path: Path
    command_id: str
    operation: str
    revision_before: int
    _connection: sqlite3.Connection
    files: FileStaging = field(default_factory=FileStaging)
    rollback_only: bool = False
    _thread_id: int = field(default_factory=threading.get_ident)
    connection: BorrowedConnection = field(init=False)

    def __post_init__(self) -> None:
        self.connection = BorrowedConnection(self)

    @property
    def revision_after(self) -> int:
        return self.revision_before + 1

    def check_thread(self) -> None:
        if threading.get_ident() != self._thread_id:
            raise InvalidCommandError("An active command connection cannot be used from another thread.")


def active_command(context: CommandContext | None = None) -> CommandScope | None:
    scope = _active.get()
    if scope is not None:
        scope.check_thread()
        if context is not None and context.key != scope.context.key:
            raise CommandContextError(context.to_dict(), scope.context.to_dict())
    return scope


def ambient_connection(database_path: str | Path) -> BorrowedConnection | None:
    scope = active_command()
    if scope is None:
        return None
    if Path(database_path).resolve() != scope.database_path:
        raise CommandContextError(
            {"database_path": str(Path(database_path).resolve())}, scope.context.to_dict()
        )
    return scope.connection


class CommandBus:
    """Durably execute an action and roll its staged state files forward.

    Live callers pass the business SQLite path. Historical callers should pass
    ``config/simulations/command_journal.sqlite3``; a historical context supplied
    with a live path is defensively routed to that dedicated control database.
    ``recover(context)`` selects that same route without ever opening live SQL.
    Plain ``recover()`` operates on the constructor's database path.
    """

    def __init__(
        self, database_path: str | Path, *, historical_database_path: str | Path | None = None
    ) -> None:
        self.database_path = Path(database_path).resolve()
        if historical_database_path is not None:
            self.historical_database_path = Path(historical_database_path).resolve()
        elif self.database_path.name == "command_journal.sqlite3" and self.database_path.parent.name == "simulations":
            self.historical_database_path = self.database_path
        else:
            parent = self.database_path.parent
            root = parent.parent if parent.name in {"data", "config"} else parent
            self.historical_database_path = root / "config" / "simulations" / "command_journal.sqlite3"
        self._initialized: set[Path] = set()

    def _database_for(self, context: CommandContext) -> Path:
        if not isinstance(context, (LiveContext, HistoricalContext)):
            raise InvalidCommandError("An explicit live or historical context is required.")
        return self.historical_database_path if isinstance(context, HistoricalContext) else self.database_path

    @staticmethod
    def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
        mode = "ro" if readonly else "rw"
        connection = sqlite3.connect(f"{path.as_uri()}?mode={mode}", uri=True, timeout=30)
        if not readonly:
            connection.execute("PRAGMA synchronous = FULL")
        return connection

    def initialize(self, context: CommandContext) -> None:
        """Explicit startup initialization; revision reads never call this."""
        path = self._database_for(context)
        if active_command() is not None:
            ambient_connection(path)
            return
        if path in self._initialized:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=30)
        try:
            connection.execute("PRAGMA synchronous = FULL")
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            if mode in {"off", "memory"}:
                connection.execute("PRAGMA journal_mode = DELETE")
            connection.executescript(SCHEMA)
            pending = self._pending(connection)
        finally:
            connection.close()
        if isinstance(context, LiveContext) and pending is None:
            from ..storage import SnapshotStore

            SnapshotStore(path).initialize()
        self._initialized.add(path)

    @staticmethod
    def _pending(connection: sqlite3.Connection) -> tuple[Any, ...] | None:
        return connection.execute(
            "SELECT command_id, context_json, receipt_json, files_json FROM application_commands "
            "WHERE state = 'pending' ORDER BY sequence LIMIT 1"
        ).fetchone()

    @staticmethod
    def _recovery_error(row: tuple[Any, ...]) -> RecoveryRequiredError:
        receipt = CommandReceipt.from_json(row[2])
        return RecoveryRequiredError(receipt.command_id, receipt.revision_after, json.loads(row[1]))

    def revision(self, context: CommandContext) -> int:
        path = self._database_for(context)
        scope = active_command()
        if scope is not None:
            active_command(context)
            ambient_connection(path)
            return scope.revision_before
        if not path.exists():
            return 0
        connection = self._connect(path, readonly=True)
        try:
            if not has_schema(connection):
                return 0
            pending = self._pending(connection)
            if pending is not None:
                raise self._recovery_error(pending)
            row = connection.execute(
                "SELECT revision FROM application_revisions WHERE context_key = ?", (context.key,)
            ).fetchone()
            return int(row[0]) if row is not None else 0
        finally:
            connection.close()

    def _publish(self, connection: sqlite3.Connection, row: tuple[Any, ...]) -> CommandReceipt:
        receipt = CommandReceipt.from_json(row[2])
        context = json.loads(row[1])
        for record in json.loads(row[3]):
            publish_file(record, receipt.command_id, receipt.revision_after, context)
        connection.execute(
            "UPDATE application_commands SET state = 'complete' WHERE command_id = ?", (receipt.command_id,)
        )
        return receipt

    def recover(self, context: CommandContext | None = None) -> list[CommandReceipt]:
        """Explicit, idempotent roll-forward; never initialize or create a DB."""
        if active_command() is not None:
            raise InvalidCommandError("Recovery cannot run inside a command.")
        path = self.database_path if context is None else self._database_for(context)
        if not path.exists():
            return []
        lock = _database_lock(path)
        lock.acquire()
        try:
            connection = self._connect(path)
        except BaseException:
            lock.release()
            raise
        try:
            if not has_schema(connection):
                return []
            connection.execute("BEGIN IMMEDIATE")
            receipts = []
            while (row := self._pending(connection)) is not None:
                try:
                    receipt = self._publish(connection, row)
                    receipts.append(receipt)
                    LOGGER.info(
                        "command_recovered command_id=%s revision=%s context=%s",
                        receipt.command_id, receipt.revision_after, row[1],
                    )
                except RecoveryRequiredError:
                    raise
                except Exception as error:
                    raise self._recovery_error(row) from error
            connection.commit()
            return receipts
        finally:
            try:
                if connection.in_transaction:
                    connection.rollback()
                connection.close()
            finally:
                lock.release()

    def _before_commit(self) -> None:
        """Narrow fault-injection seam after validation, before durable commit."""

    @staticmethod
    def _authorize_action(
        action: int, argument1: str | None, argument2: str | None,
        database: str | None, source: str | None,
    ) -> int:
        if action in {sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT, sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH}:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def execute(
        self,
        context: CommandContext,
        operation: str,
        payload: dict[str, Any],
        action: Callable[[], Any],
        expected_revision: int | None = None,
        command_id: str | None = None,
    ) -> CommandReceipt:
        path = self._database_for(context)
        if not isinstance(operation, str) or not operation.strip() or not isinstance(payload, dict):
            raise InvalidCommandError("A nonempty operation and dictionary payload are required.")
        if expected_revision is not None and (
            isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0
        ):
            raise InvalidCommandError("expected_revision must be a nonnegative integer.")
        if command_id is not None and (not isinstance(command_id, str) or not command_id.strip()):
            raise InvalidCommandError("command_id must be a nonempty string.")
        fingerprint = hashlib.sha256(
            json_text({"context": context.to_dict(), "operation": operation, "payload": payload}).encode("utf-8")
        ).hexdigest()
        scope = active_command(context)
        if scope is not None:
            ambient_connection(path)
            if expected_revision is not None and expected_revision != scope.revision_before:
                raise StaleRevisionError(context.to_dict(), expected_revision, scope.revision_before)
            if command_id is not None and command_id != scope.command_id:
                raise InvalidCommandError("A nested command cannot allocate an independent command ID.")
            try:
                result = json.loads(json_text(action()))
            except BaseException:
                scope.rollback_only = True
                raise
            return CommandReceipt(result, scope.revision_before, scope.revision_after, scope.command_id)

        lock = _database_lock(path)
        lock.acquire()
        try:
            self.initialize(context)
            connection = self._connect(path)
        except BaseException:
            lock.release()
            raise
        try:
            connection.execute("BEGIN IMMEDIATE")
            identifier = command_id or uuid4().hex
            duplicate = connection.execute(
                "SELECT fingerprint, command_id, context_json, receipt_json, files_json, state "
                "FROM application_commands WHERE command_id = ?", (identifier,)
            ).fetchone()
            if duplicate is not None:
                if duplicate[0] != fingerprint:
                    raise IdempotencyConflictError(identifier, context.to_dict())
                if duplicate[5] == "pending":
                    row = (duplicate[1], duplicate[2], duplicate[3], duplicate[4])
                    try:
                        receipt = self._publish(connection, row)
                        connection.commit()
                        LOGGER.info("command_replayed command_id=%s revision=%s", identifier, receipt.revision_after)
                        return receipt
                    except RecoveryRequiredError:
                        raise
                    except Exception as error:
                        raise self._recovery_error(row) from error
                receipt = CommandReceipt.from_json(duplicate[3])
                LOGGER.info("command_replayed command_id=%s revision=%s", identifier, receipt.revision_after)
                return receipt
            pending = self._pending(connection)
            if pending is not None:
                raise self._recovery_error(pending)
            row = connection.execute(
                "SELECT revision FROM application_revisions WHERE context_key = ?", (context.key,)
            ).fetchone()
            revision = int(row[0]) if row is not None else 0
            if expected_revision is not None and expected_revision != revision:
                LOGGER.warning(
                    "command_rejected code=STALE_REVISION command_id=%s context=%s expected=%s revision=%s",
                    identifier, context.key, expected_revision, revision,
                )
                raise StaleRevisionError(context.to_dict(), expected_revision, revision)
            scope = CommandScope(context, path, identifier, operation, revision, connection)
            token = _active.set(scope)
            connection.set_authorizer(self._authorize_action)
            try:
                result = json.loads(json_text(action()))
                if scope.rollback_only:
                    raise InvalidCommandError("A nested operation failed; the command must roll back.")
                scope.files.validate()
                receipt = CommandReceipt(result, revision, revision + 1, identifier)
                files_json = json_text(scope.files.records())
                context_json = json_text(context.to_dict())
                receipt_json = json_text(receipt.to_dict())
                committed = (identifier, context_json, receipt_json, files_json)
                connection.execute(
                    "INSERT INTO application_revisions(context_key, revision) VALUES (?, ?) "
                    "ON CONFLICT(context_key) DO UPDATE SET revision = excluded.revision",
                    (context.key, revision + 1),
                )
                connection.execute(
                    "INSERT INTO application_commands "
                    "(command_id, context_key, context_json, operation, fingerprint, receipt_json, files_json, state) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')",
                    (identifier, context.key, context_json, operation, fingerprint, receipt_json, files_json),
                )
                self._before_commit()
            finally:
                connection.set_authorizer(None)
                _active.reset(token)
            try:
                connection.commit()
                LOGGER.info(
                    "command_committed operation=%s command_id=%s context=%s revision_before=%s revision_after=%s",
                    operation, identifier, context.key, revision, revision + 1,
                )
            except Exception as error:
                if not connection.in_transaction:
                    try:
                        persisted = connection.execute(
                            "SELECT 1 FROM application_commands WHERE command_id = ?", (identifier,)
                        ).fetchone()
                    except sqlite3.Error:
                        raise RecoveryRequiredError(
                            identifier, receipt.revision_after, context.to_dict(), state="commit_unknown"
                        ) from error
                    if persisted is not None:
                        raise self._recovery_error(committed) from error
                raise
            try:
                connection.execute("BEGIN IMMEDIATE")
                state = connection.execute(
                    "SELECT state FROM application_commands WHERE command_id = ?", (identifier,)
                ).fetchone()
                if state[0] == "pending":
                    receipt = self._publish(connection, committed)
                connection.commit()
            except RecoveryRequiredError:
                LOGGER.warning("command_pending_recovery command_id=%s revision=%s", identifier, revision + 1)
                raise
            except Exception as error:
                LOGGER.warning("command_pending_recovery command_id=%s revision=%s", identifier, revision + 1)
                raise self._recovery_error(committed) from error
            return receipt
        finally:
            try:
                if connection.in_transaction:
                    connection.rollback()
                connection.close()
            finally:
                lock.release()
