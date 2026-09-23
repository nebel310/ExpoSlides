from __future__ import annotations

import asyncio
import importlib
import logging
import ssl
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


@pytest.fixture
def llm(monkeypatch, service_importer):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    return service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")


def _response():
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))])


@pytest.mark.parametrize("error_type", [
    httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.CloseError, httpx.ConnectTimeout,
])
def test_transient_transport_recovers_without_extra_content_requests(
    llm, monkeypatch, caplog, error_type,
):
    calls = []
    delays = []

    async def achat(chat):
        calls.append(chat)
        if len(calls) == 1:
            raise error_type("private endpoint or payload")
        return _response()

    async def sleep(delay):
        delays.append(delay)

    llm.fast_llm_client._client = SimpleNamespace(achat=achat)
    monkeypatch.setattr(llm.asyncio, "sleep", sleep)
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(llm.fast_llm_client.generate_json_object("private source", {}))

    assert result == {"ok": True}
    assert len(calls) == 2
    assert calls[0] is calls[1]
    assert delays == [1]
    assert "private" not in caplog.text


@pytest.mark.parametrize("error_type,expected_code", [
    (httpx.ReadError, "network"), (httpx.ConnectTimeout, "timeout"),
])
def test_exhausted_transport_retries_preserve_typed_cause_and_redaction(
    llm, monkeypatch, caplog, error_type, expected_code,
):
    calls = []
    delays = []

    async def achat(chat):
        calls.append(chat)
        raise error_type("private endpoint or payload")

    async def sleep(delay):
        delays.append(delay)

    llm.fast_llm_client._client = SimpleNamespace(achat=achat)
    monkeypatch.setattr(llm.asyncio, "sleep", sleep)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(llm.LLMGenerationError) as raised:
            asyncio.run(llm.fast_llm_client.generate_json_object("private source", {}))

    assert len(calls) == 3
    assert delays == [1, 2]
    assert isinstance(raised.value.__cause__, error_type)
    assert not getattr(raised.value, "invalid_response", False)
    assert "private" not in str(raised.value)
    assert "private" not in caplog.text
    errors = importlib.import_module("app.errors")
    assert errors.content_error_code(raised.value) == expected_code


@pytest.mark.parametrize("cause_kind", ["ssl_cause", "ssl_context", "ssl_message", "auth", "cycle"])
def test_wrapped_tls_or_authentication_errors_never_retry(
    llm, monkeypatch, cause_kind,
):
    calls = []
    transport_error = httpx.ConnectError("private transport details")
    certificate_error = ssl.SSLCertVerificationError(1, "certificate verify failed")
    if cause_kind == "ssl_cause":
        transport_error.__cause__ = certificate_error
    elif cause_kind == "ssl_context":
        transport_error.__context__ = certificate_error
    elif cause_kind == "ssl_message":
        transport_error = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] private details")
    elif cause_kind == "auth":
        request = httpx.Request("POST", "https://example.test/private")
        transport_error.__cause__ = httpx.HTTPStatusError(
            "private", request=request,
            response=httpx.Response(401, request=request, content=b"private"),
        )
    else:
        transport_error.__cause__ = certificate_error
        certificate_error.__context__ = transport_error

    async def achat(chat):
        calls.append(chat)
        raise transport_error

    async def sleep(delay):
        pytest.fail("permanent connection failures must not retry")

    llm.fast_llm_client._client = SimpleNamespace(achat=achat)
    monkeypatch.setattr(llm.asyncio, "sleep", sleep)
    with pytest.raises(llm.LLMGenerationError) as raised:
        asyncio.run(llm.fast_llm_client.generate_json_object("private source", {}))
    assert len(calls) == 1
    assert raised.value.__cause__ is transport_error
    assert "private" not in str(raised.value)


@pytest.mark.parametrize("outer_deadline", [False, True])
def test_transport_backoff_remains_inside_deadline_and_is_cancelled(
    llm, monkeypatch, outer_deadline,
):
    calls = []
    cancelled = []

    async def achat(chat):
        calls.append(chat)
        raise httpx.ReadError("private disconnected transport")

    async def sleep(delay):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(delay)

    llm.fast_llm_client._client = SimpleNamespace(achat=achat)
    monkeypatch.setattr(llm.asyncio, "sleep", sleep)
    if not outer_deadline:
        monkeypatch.setattr(llm.settings, "llm_fast_api_timeout", 0.01)

    async def run():
        if outer_deadline:
            async with asyncio.timeout(0.01):
                await llm.fast_llm_client.generate_json_object("source", {})
        else:
            await llm.fast_llm_client.generate_json_object("source", {})

    with pytest.raises(TimeoutError if outer_deadline else llm.LLMGenerationError):
        asyncio.run(run())
    assert len(calls) == 1
    assert cancelled == [1]


def test_read_timeout_does_not_start_another_expensive_generation(llm, monkeypatch):
    calls = []

    async def achat(chat):
        calls.append(chat)
        raise httpx.ReadTimeout("private timeout")

    async def sleep(delay):
        pytest.fail("read timeout must not retry")

    llm.fast_llm_client._client = SimpleNamespace(achat=achat)
    monkeypatch.setattr(llm.asyncio, "sleep", sleep)
    with pytest.raises(llm.LLMGenerationError) as raised:
        asyncio.run(llm.fast_llm_client.generate_json_object("source", {}))
    assert len(calls) == 1
    assert isinstance(raised.value.__cause__, httpx.ReadTimeout)
