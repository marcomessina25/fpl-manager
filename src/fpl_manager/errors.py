"""Structured domain error hierarchy for FPL Manager (V1.0.1).

Defines explicit, typed domain exceptions with machine-readable error codes and context
so that API endpoints, CLI routines, and LLM integrations handle failures gracefully.
"""

from typing import Any


class FPLError(Exception):
    """Base domain exception for all FPL Manager operations."""

    def __init__(self, message: str, code: str = "FPL_GENERIC_ERROR", details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


class DataIntegrityError(FPLError):
    """Raised when persisted snapshot, database, or squad state is corrupt or inconsistent."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="DATA_INTEGRITY_ERROR", details=details)


class RuleViolationError(FPLError):
    """Raised when an action violates official FPL budget, quota, or formation rules."""

    def __init__(self, message: str, errors: list[str] | None = None, details: dict[str, Any] | None = None) -> None:
        d = details or {}
        if errors:
            d["rule_errors"] = errors
        super().__init__(message, code="RULE_VIOLATION", details=d)


class OptimizationError(FPLError):
    """Raised when the squad or transfer optimizer encounters an infeasible formulation."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, code="OPTIMIZATION_ERROR", details=details)


class ProviderError(FPLError):
    """Base exception for external LLM or API provider failures."""

    def __init__(self, message: str, provider: str, code: str = "PROVIDER_ERROR", details: dict[str, Any] | None = None) -> None:
        d = details or {}
        d["provider"] = provider
        super().__init__(message, code=code, details=d)


class ProviderAuthError(ProviderError):
    """Raised when an external API key is invalid, missing, or unauthorized."""

    def __init__(self, message: str, provider: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, provider=provider, code="PROVIDER_AUTH_ERROR", details=details)


class ProviderRateLimitError(ProviderError):
    """Raised when an external API provider rate limits or quotas are exceeded."""

    def __init__(self, message: str, provider: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, provider=provider, code="PROVIDER_RATE_LIMIT", details=details)


class ProviderTimeoutError(ProviderError):
    """Raised when an external API call times out."""

    def __init__(self, message: str, provider: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, provider=provider, code="PROVIDER_TIMEOUT", details=details)


class HistoricalDataError(FPLError):
    """Raised when point-in-time historical datasets or matchday outcomes are missing."""

    def __init__(self, message: str, season: str, gameweek: int | None = None, details: dict[str, Any] | None = None) -> None:
        d = details or {}
        d["season"] = season
        if gameweek is not None:
            d["gameweek"] = gameweek
        super().__init__(message, code="HISTORICAL_DATA_ERROR", details=d)
