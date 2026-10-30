"""Machine-readable command failures, including committed-but-unpublished state."""

from typing import Any

from ..errors import FPLError


class StaleRevisionError(FPLError):
    def __init__(self, context: dict[str, Any], expected_revision: int, revision: int) -> None:
        super().__init__(
            "The state changed; refresh it before retrying this command.",
            code="STALE_REVISION",
            details={"context": context, "expected_revision": expected_revision, "revision": revision},
        )


class IdempotencyConflictError(FPLError):
    def __init__(self, command_id: str, context: dict[str, Any]) -> None:
        super().__init__(
            "This command ID was already used with a different context, operation, or payload.",
            code="IDEMPOTENCY_CONFLICT",
            details={"command_id": command_id, "context": context},
        )


class RecoveryRequiredError(FPLError):
    def __init__(
        self, command_id: str, revision: int, context: dict[str, Any], state: str = "pending"
    ) -> None:
        super().__init__(
            "The command is committed but its state files need recovery. Do not apply it again.",
            code="RECOVERY_REQUIRED",
            details={"command_id": command_id, "revision": revision, "state": state, "context": context},
        )
        self.command_id = command_id
        self.revision = revision
        self.state = state


class RecoveryConflictError(RecoveryRequiredError):
    def __init__(self, command_id: str, revision: int, context: dict[str, Any], path: str) -> None:
        super().__init__(command_id, revision, context, state="conflict")
        self.code = "RECOVERY_CONFLICT"
        self.message = "Recovery found an external file change; the file was not overwritten."
        self.args = (self.message,)
        self.details["path"] = path


class CommandContextError(FPLError):
    def __init__(self, context: dict[str, Any], active_context: dict[str, Any]) -> None:
        super().__init__(
            "A nested command cannot change its context or database.",
            code="COMMAND_CONTEXT_CONFLICT",
            details={"context": context, "active_context": active_context},
        )


class InvalidCommandError(FPLError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="INVALID_COMMAND", details=details)
