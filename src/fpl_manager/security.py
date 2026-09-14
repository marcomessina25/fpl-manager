"""Security utilities and trust boundary enforcement for FPL Manager (V0.9.10 Production Hardening).

Implements Section 28 of docs/v09/v09.md:
- Secret redaction for API keys, bearer tokens, and credentials in logs and outputs.
- Verification that network servers bind strictly to local-only interfaces by default.
- Safe CORS origin validation.
"""

import re
from typing import Sequence

# Regex patterns for common API keys and tokens
_SECRET_PATTERNS = [
    # Google AI Studio / Gemini API keys (AIzaSy...)
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    # OpenAI API keys (sk-...)
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    # OpenRouter API keys (sk-or-...)
    re.compile(r"sk-or-v1-[a-zA-Z0-9]{40,}"),
    # Generic Authorization: Bearer <token>
    re.compile(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{15,}"),
    # Generic key assignment in URLs: ?key=... or &key=...
    re.compile(r"(?i)([?&]key=)[a-zA-Z0-9_\-]{15,}"),
]

# Safe local-only bind addresses
_SAFE_LOCAL_HOSTS = {
    "127.0.0.1",
    "localhost",
    "::1",
    "0.0.0.0",  # May be permitted in explicit container environments, but warned
}


def redact_secrets(text: str) -> str:
    """Redact known API keys, tokens, and secrets from logs, errors, and reports."""
    if not text:
        return text

    sanitized = text
    for pattern in _SECRET_PATTERNS:
        def _replace_secret(match: re.Match[str]) -> str:
            val = match.group(0)
            if val.lower().startswith("bearer "):
                return "Bearer [REDACTED_TOKEN]"
            if match.groups():
                prefix = match.group(1)
                return f"{prefix}[REDACTED_API_KEY]"
            # Show first 4 chars, redact rest
            prefix = val[:4]
            return f"{prefix}...[REDACTED_SECRET]"

        sanitized = pattern.sub(_replace_secret, sanitized)

    return sanitized


def is_safe_local_host(host: str, allow_all_interfaces: bool = False) -> bool:
    """Verify if a host address adheres to local-only trust boundaries."""
    host_clean = host.strip().lower()
    if host_clean in ("127.0.0.1", "localhost", "::1"):
        return True
    if host_clean == "0.0.0.0":
        return allow_all_interfaces
    return False


def validate_cors_origin(origin: str, allowed_origins: Sequence[str]) -> bool:
    """Validate CORS origin against configured safe allowed origins."""
    if not origin:
        return False
    norm_origin = origin.strip().rstrip("/").lower()
    for allowed in allowed_origins:
        norm_allowed = allowed.strip().rstrip("/").lower()
        if norm_allowed == "*" or norm_origin == norm_allowed:
            return True
    return False
