"""JSON-compatible state I/O with ambient staging and atomic publication.

Existing serializers keep their original schemas. Inside a command, reads and
writes are isolated in memory until SQL and the recovery journal have committed.
Outside commands, writes remain atomic but do not participate in a journal.
"""

import base64
import hashlib
import os
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .errors import InvalidCommandError, RecoveryConflictError


def _path(path: str | Path) -> Path:
    return Path(path).resolve()


def _bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _hash(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


def _sync_directory(path: Path) -> None:
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _atomic_write(path: Path, data: bytes, *, before_replace: Callable[[], None] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.command-{uuid4().hex}.stage")
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        for attempt in range(6):
            if before_replace is not None:
                before_replace()
            try:
                os.replace(temporary, path)
                break
            except PermissionError as error:
                if os.name != "nt" or getattr(error, "winerror", None) not in {5, 32, 33} or attempt == 5:
                    raise
                time.sleep(0.01 * 2**attempt)
        _sync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@dataclass
class _StagedFile:
    path: Path
    before: bytes | None
    after: bytes | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "before_sha256": _hash(self.before),
            "after_sha256": _hash(self.after),
            "after_base64": None if self.after is None else base64.b64encode(self.after).decode("ascii"),
        }


class FileStaging:
    def __init__(self) -> None:
        self._observed: dict[Path, bytes | None] = {}
        self._staged: dict[Path, _StagedFile] = {}

    def read(self, path: str | Path) -> bytes | None:
        target = _path(path)
        if target in self._staged:
            return self._staged[target].after
        if target not in self._observed:
            self._observed[target] = _bytes(target)
        return self._observed[target]

    def write(self, path: str | Path, data: bytes | None) -> None:
        target = _path(path)
        if target in self._staged:
            self._staged[target].after = data
        else:
            self._staged[target] = _StagedFile(target, self.read(target), data)

    def records(self) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in self._staged.values()]

    def validate(self) -> None:
        for entry in self._staged.values():
            if _hash(_bytes(entry.path)) not in {_hash(entry.before), _hash(entry.after)}:
                raise InvalidCommandError("A state file changed during the command.", {"path": str(entry.path)})


def publish_file(record: dict[str, Any], command_id: str, revision: int, context: dict[str, Any]) -> None:
    path = Path(record["path"])
    data = None if record["after_base64"] is None else base64.b64decode(record["after_base64"], validate=True)
    if _hash(data) != record["after_sha256"]:
        raise RecoveryConflictError(command_id, revision, context, str(path))
    def check_current() -> None:
        if _hash(_bytes(path)) not in {record["before_sha256"], record["after_sha256"]}:
            raise RecoveryConflictError(command_id, revision, context, str(path))

    current_hash = _hash(_bytes(path))
    if current_hash == record["after_sha256"]:
        return
    if current_hash != record["before_sha256"]:
        raise RecoveryConflictError(command_id, revision, context, str(path))
    if data is None:
        path.unlink()
        _sync_directory(path.parent)
    else:
        _atomic_write(path, data, before_replace=check_current)


def read_state_text(path: str | Path) -> str:
    from .commands import active_command

    command = active_command()
    data = command.files.read(path) if command is not None else _bytes(_path(path))
    if data is None:
        raise FileNotFoundError(str(path))
    return data.decode("utf-8")


def state_file_exists(path: str | Path) -> bool:
    """Include new staged files and exclude staged deletions."""
    from .commands import active_command

    command = active_command()
    return command.files.read(path) is not None if command is not None else _path(path).is_file()


def write_state_text(path: str | Path, text: str) -> None:
    from .commands import active_command

    data = text.encode("utf-8")
    command = active_command()
    if command is None:
        _atomic_write(_path(path), data)
    else:
        command.files.write(path, data)


def delete_state_file(path: str | Path) -> None:
    from .commands import active_command

    command = active_command()
    if command is not None:
        command.files.write(path, None)
    else:
        target = _path(path)
        try:
            target.unlink()
        except FileNotFoundError:
            return
        _sync_directory(target.parent)
