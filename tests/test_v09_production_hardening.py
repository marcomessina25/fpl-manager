from pathlib import Path
import pytest

from fpl_manager.errors import (
    DataIntegrityError,
    FPLError,
    HistoricalDataError,
    OptimizationError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    RuleViolationError,
)
from fpl_manager.providers import (
    BaseLLMProvider,
    GeminiProvider,
    HeuristicProvider,
    OpenAIProvider,
    OpenRouterProvider,
    ProviderRequest,
    get_provider,
)
from fpl_manager.security import is_safe_local_host, redact_secrets, validate_cors_origin


def test_structured_error_hierarchy() -> None:
    err = FPLError("Something broke", code="TEST_CODE", details={"foo": "bar"})
    assert err.code == "TEST_CODE"
    assert err.to_dict()["code"] == "TEST_CODE"

    rule_err = RuleViolationError("Illegal formation", errors=["Too few defenders"])
    assert rule_err.code == "RULE_VIOLATION"
    assert "Too few defenders" in rule_err.details["rule_errors"]

    data_err = DataIntegrityError("Corrupted database")
    assert data_err.code == "DATA_INTEGRITY_ERROR"

    opt_err = OptimizationError("Infeasible squad")
    assert opt_err.code == "OPTIMIZATION_ERROR"

    prov_auth = ProviderAuthError("Invalid key", provider="gemini")
    assert prov_auth.code == "PROVIDER_AUTH_ERROR"
    assert prov_auth.details["provider"] == "gemini"

    hist_err = HistoricalDataError("Missing GW data", season="2023-24", gameweek=5)
    assert hist_err.code == "HISTORICAL_DATA_ERROR"
    assert hist_err.details["season"] == "2023-24"
    assert hist_err.details["gameweek"] == 5


def test_security_secret_redaction() -> None:
    # Google AI Studio / Gemini key
    raw_gemini = "Call failed with url: https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0?key=AIzaSyA1234567890abcdefghijklmnopqrstuv"
    redacted_gemini = redact_secrets(raw_gemini)
    assert "AIzaSyA1234567890abcdefghijklmnopqrstuv" not in redacted_gemini
    assert "[REDACTED" in redacted_gemini

    # OpenAI key
    raw_openai = "Bearer sk-abcdefghijklmnopqrstuvwxyz1234567890"
    redacted_openai = redact_secrets(raw_openai)
    assert "sk-abcdefghijklmnopqrstuvwxyz1234567890" not in redacted_openai
    assert "[REDACTED" in redacted_openai

    # OpenRouter key
    raw_openrouter = "Header Authorization: Bearer sk-or-v1-abcdefghijklmnopqrstuvwxyz12345678901234"
    redacted_openrouter = redact_secrets(raw_openrouter)
    assert "sk-or-v1-abcdefghijklmnopqrstuvwxyz12345678901234" not in redacted_openrouter

    # Empty / clean text
    assert redact_secrets("") == ""
    assert redact_secrets("Clean message") == "Clean message"


def test_security_safe_host_and_cors() -> None:
    assert is_safe_local_host("127.0.0.1") is True
    assert is_safe_local_host("localhost") is True
    assert is_safe_local_host("::1") is True
    assert is_safe_local_host("192.168.1.100") is False
    assert is_safe_local_host("8.8.8.8") is False
    assert is_safe_local_host("0.0.0.0", allow_all_interfaces=False) is False
    assert is_safe_local_host("0.0.0.0", allow_all_interfaces=True) is True

    # CORS
    allowed = ["http://localhost:8000", "http://127.0.0.1:8000"]
    assert validate_cors_origin("http://localhost:8000", allowed) is True
    assert validate_cors_origin("http://127.0.0.1:8000", allowed) is True
    assert validate_cors_origin("http://malicious-site.com", allowed) is False
    assert validate_cors_origin("", allowed) is False


def test_provider_abstraction_heuristic_offline() -> None:
    prov = HeuristicProvider()
    assert prov.name == "heuristic"
    assert prov.is_available() is True

    req = ProviderRequest(prompt="Analyze squad for GW10", system_prompt="You are a tactical advisor")
    resp = prov.generate(req)
    assert resp.provider == "heuristic"
    assert resp.model == "deterministic-heuristic-v0.9"
    assert len(resp.content) > 50
    assert "Deterministic Strategic Assessment" in resp.content


def test_provider_factory_fallback() -> None:
    # Explicit heuristic
    prov_heur = get_provider("heuristic")
    assert isinstance(prov_heur, HeuristicProvider)

    # Missing API key falls back to HeuristicProvider safely without errors
    prov_gemini_no_key = get_provider("gemini", api_key="")
    assert isinstance(prov_gemini_no_key, HeuristicProvider)

    prov_openai_no_key = get_provider("openai", api_key="")
    assert isinstance(prov_openai_no_key, HeuristicProvider)

    # Auto mode with no keys defaults to HeuristicProvider
    prov_auto = get_provider("auto", api_key="")
    assert isinstance(prov_auto, HeuristicProvider)
