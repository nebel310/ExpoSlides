from __future__ import annotations

import importlib
from pathlib import Path

import httpx
import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


@pytest.fixture
def errors(service_importer):
    return service_importer(CONTENT_SERVICE_ROOT, "app.errors")


def http_error(status):
    request = httpx.Request("POST", "https://example.test/private")
    response = httpx.Response(status, request=request, content=b"secret response")
    return httpx.HTTPStatusError("private response", request=request, response=response)


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
        (http_error(401), "auth"),
        (http_error(403), "auth"),
        (http_error(429), "network"),
        (http_error(500), "network"),
        (http_error(503), "network"),
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


def test_credentials_mismatch_is_auth_even_when_a_key_is_configured(errors):
    cause = errors.LLMCredentialsError("provider credentials mismatch")
    wrapper = errors.LLMGenerationError("wrapper")
    wrapper.__cause__ = cause

    assert isinstance(cause, errors.LLMGenerationError)
    assert errors.content_error_code(cause) == "auth"
    assert errors.content_error_code(wrapper, credentials_configured=True) == "auth"


@pytest.mark.parametrize("status", [400, 404, 422])
def test_other_http_statuses_remain_unknown(errors, status):
    error = errors.LLMGenerationError("wrapper")
    error.__cause__ = http_error(status)
    assert errors.content_error_code(error) == "unknown"


def test_http_classification_preserves_timeout_and_auth_precedence(errors):
    network = httpx.ConnectError("private")
    network.__cause__ = http_error(403)
    assert errors.content_error_code(network) == "auth"
    network.__cause__.__context__ = httpx.ConnectTimeout("private")
    assert errors.content_error_code(network) == "timeout"


def test_isolated_service_error_code_contract_matches_root_cli(errors, monkeypatch):
    monkeypatch.syspath_prepend(str(CONTENT_SERVICE_ROOT.parents[1]))
    from exposlides.cli import CONTENT_ERROR_CODES

    assert {value: key for key, value in errors.CONTENT_ERROR_EXIT_CODES.items()} == (
        CONTENT_ERROR_CODES
    )


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("ContentValidationError", 21), ("TimeoutError", 22), ("LLMGenerationError", 1),
     ("LLMCredentialsError", 23)],
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
