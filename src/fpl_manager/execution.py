"""Versioned execution semantics, separate from a decision-engine identifier."""

from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from typing import Iterator

from .errors import FPLError


class ExecutionVersion(str, Enum):
    UNKNOWN_ARCHIVE = "unknown"
    LEGACY_V146 = "v146"
    CORRECTED_V147 = "v147"


CURRENT_EXECUTION_VERSION = ExecutionVersion.CORRECTED_V147
LEGACY_EXECUTION_VERSION = ExecutionVersion.LEGACY_V146
_active_execution: ContextVar[ExecutionVersion] = ContextVar(
    "fpl_execution_version", default=CURRENT_EXECUTION_VERSION
)


def resolve_execution_version(
    version: str | ExecutionVersion | None = None,
) -> ExecutionVersion:
    if version is None:
        return _active_execution.get()
    try:
        resolved = ExecutionVersion(version)
        if resolved is ExecutionVersion.UNKNOWN_ARCHIVE:
            raise ValueError("An unverified archive is not an executable policy.")
        return resolved
    except ValueError as error:
        raise ValueError(f"Unknown execution version: {version!r}.") from error


def admit_persisted_execution_version(value: object) -> ExecutionVersion:
    """Only explicit recognized persisted identities can enable execution."""
    if value == CURRENT_EXECUTION_VERSION.value:
        return CURRENT_EXECUTION_VERSION
    if value == LEGACY_EXECUTION_VERSION.value:
        return LEGACY_EXECUTION_VERSION
    return ExecutionVersion.UNKNOWN_ARCHIVE


@contextmanager
def execution_scope(version: str | ExecutionVersion) -> Iterator[ExecutionVersion]:
    resolved = resolve_execution_version(version)
    token = _active_execution.set(resolved)
    try:
        yield resolved
    finally:
        _active_execution.reset(token)


class LegacyTrialReadOnlyError(FPLError):
    def __init__(self) -> None:
        super().__init__(
            "This legacy simulation is read-only. Create an explicit corrected fork "
            "to continue without rewriting the recorded trial.",
            code="LEGACY_TRIAL_READ_ONLY",
        )
