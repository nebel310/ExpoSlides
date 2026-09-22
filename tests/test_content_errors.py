from __future__ import annotations

import importlib
from pathlib import Path

import httpx
import pytest
from gigachat.exceptions import AuthenticationError, ForbiddenError, RateLimitError, ServerError

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


@pytest.fixture
def errors(service_importer):
    return service_importer(CONTENT_SERVICE_ROOT, "app.errors")


@pytest.mark.parametrize("kind", ["AnalysisValidationError", "PlanValidationError",
                                  "ContentValidationError", "UserMappingValidationError"])
def test_semantic_validation_has_its_own_code(errors, kind):
    error = getattr(errors, kind)("401 timeout network secret source")
    assert errors.content_error_code(error) == "content_validation"


@pytest.mark.parametrize(
    ("cause", "expected"),
    [
        (TimeoutError("secret source"), "timeout"),
        (httpx.ReadTimeout("secret source"), "timeout"),
        (httpx.ConnectError("private endpoint"), "network"),
        (ConnectionError("private endpoint"), "network"),
        (AuthenticationError("private", 401, b"secret", None), "auth"),
        (ForbiddenError("private", 403, b"secret", None), "auth"),
        (RateLimitError("private", 429, b"secret", None), "network"),
        (ServerError("private", 503, b"secret", None), "network"),
    ],
)
def test_classification_keeps_root_cause_through_wrappers(errors, cause, expected):
    error = errors.ContentValidationError("wrapper")
    wrapper = errors.LLMGenerationError("wrapper")
    wrapper.__cause__ = cause
    error.__cause__ = wrapper
    assert errors.content_error_code(error) == expected


def test_classification_recognizes_invalid_response_and_missing_credentials(errors):
    invalid = errors.LLMGenerationError("private response")
    invalid.invalid_response = True
    wrapper = errors.ContentValidationError("wrapper")
    wrapper.__cause__ = invalid
    assert errors.content_error_code(wrapper) == "invalid_response"
    assert errors.content_error_code(
        errors.LLMGenerationError("private"), credentials_configured=False,
    ) == "auth"
    assert errors.content_error_code(ValueError("timeout 401 network")) == "unknown"


def test_classification_handles_circular_exception_context(errors):
    error = errors.LLMGenerationError("private")
    error.__context__ = error
    assert errors.content_error_code(error) == "unknown"


def test_isolated_service_error_code_contract_matches_root_cli(errors):
    from exposlides.cli import CONTENT_ERROR_CODES

    assert {value: key for key, value in errors.CONTENT_ERROR_EXIT_CODES.items()} == (
        CONTENT_ERROR_CODES
    )


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("ContentValidationError", 21), ("TimeoutError", 22), ("LLMGenerationError", 1)],
)
def test_content_cli_exits_with_safe_code_without_output(
    service_importer, monkeypatch, tmp_path, kind, expected,
):
    main = service_importer(CONTENT_SERVICE_ROOT, "app.main")
    errors = importlib.import_module("app.errors")
    monkeypatch.setattr(main, "setup_logging", lambda: None)
    monkeypatch.setattr(main.settings, "llm_api_key", "test-key")

    async def fail(*args):
        error_type = TimeoutError if kind == "TimeoutError" else getattr(errors, kind)
        raise error_type("private response")

    monkeypatch.setattr(main, "run", fail)
    output = tmp_path / "content.json"
    result = main.main(["--cli", "--output-json", str(output)])
    assert result == expected
    assert not output.exists()
