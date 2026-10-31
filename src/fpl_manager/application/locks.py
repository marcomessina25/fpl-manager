"""Cross-process writer exclusion through SQL commit and JSON publication."""

import errno
import os
from pathlib import Path
import sqlite3
import threading
import time

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class CommandWriteLock:
    """Reentrant thread lock plus an OS-released per-database file lock."""

    def __init__(self, database_path: Path, *, timeout: float = 30) -> None:
        self.path = database_path.with_name(database_path.name + ".command.lock")
        self.timeout = timeout
        self._thread_lock = threading.RLock()
        self._descriptor: int | None = None
        self._owner: int | None = None
        self._depth = 0

    def _acquire_file(self, descriptor: int) -> None:
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if os.name == "nt":
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError as error:
                if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise sqlite3.OperationalError(
                        "Timed out waiting for the cross-process command write lock."
                    ) from error
                time.sleep(min(0.05, remaining))

    def acquire(self) -> bool:
        self._thread_lock.acquire()
        try:
            if self._depth == 0:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
                try:
                    self._acquire_file(descriptor)
                except BaseException:
                    os.close(descriptor)
                    raise
                self._descriptor = descriptor
                self._owner = threading.get_ident()
            self._depth += 1
            return True
        except BaseException:
            self._thread_lock.release()
            raise

    def release(self) -> None:
        if self._owner != threading.get_ident() or self._depth == 0:
            raise RuntimeError("Cannot release an unowned command write lock.")
        self._depth -= 1
        try:
            if self._depth == 0:
                descriptor = self._descriptor
                assert descriptor is not None
                try:
                    if os.name == "nt":
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    try:
                        os.close(descriptor)
                    finally:
                        self._descriptor = None
                        self._owner = None
        finally:
            self._thread_lock.release()
        # Do not unlink the sidecar: waiting writers must retain the same inode.
