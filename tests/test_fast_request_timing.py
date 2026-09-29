from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
PRIVATE_SOURCE = "private source that must not appear in timing logs"
PRIVATE_KEY = "hf_OfflineTimingToken123"


@pytest.fixture
def llm(monkeypatch, service_importer):
    monkeypatch.setenv("LLM_API_KEY", PRIVATE_KEY)
    module = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    monkeypatch.setattr(module.settings, "llm_fast_api_timeout", 0.1)
    return module


def test_fast_response_logs_elapsed_time_without_content(llm, caplog):
    private_result = "private generated content"

    async def achat(chat):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"title":"private generated content"}',
        ))])

    llm.fast_llm_client._client = SimpleNamespace(achat=achat)
    with caplog.at_level(logging.INFO):
        result = asyncio.run(llm.fast_llm_client.generate_json_object(PRIVATE_SOURCE, {}))

    assert result == {"title": private_result}
    messages = [record.getMessage() for record in caplog.records]
    assert any(re.fullmatch(
        r"Ответ LLM получен за \d+\.\d{2} с, лимит запроса 0\.10 с", message,
    ) for message in messages)
    assert all(value not in caplog.text for value in (PRIVATE_SOURCE, PRIVATE_KEY, private_result))


def test_request_deadline_logs_its_limit_and_cancels_transport(llm, monkeypatch, caplog):
    calls = 0
    cancelled = False

    async def achat(chat):
        nonlocal calls, cancelled
        calls += 1
        try:
            await asyncio.Future()
        finally:
            cancelled = True

    llm.fast_llm_client._client = SimpleNamespace(achat=achat)
    monkeypatch.setattr(llm.settings, "llm_fast_api_timeout", 0.01)
    with caplog.at_level(logging.INFO), pytest.raises(llm.LLMGenerationError) as caught:
        asyncio.run(llm.fast_llm_client.generate_json_object(PRIVATE_SOURCE, {}))

    assert isinstance(caught.value.__cause__, TimeoutError)
    assert not getattr(caught.value, "invalid_response", False)
    assert calls == 1
    assert cancelled
    assert any(re.fullmatch(
        r"Истёк лимит запроса LLM: прошло \d+\.\d{2} с, лимит 0\.01 с",
        record.getMessage(),
    ) for record in caplog.records)
    assert "Таймаут транспорта LLM" not in caplog.text
    assert "Ответ LLM получен" not in caplog.text
    assert PRIVATE_SOURCE not in caplog.text
    assert PRIVATE_KEY not in caplog.text


@pytest.mark.parametrize("timeout_type, expected_calls", [
    (httpx.ReadTimeout, 1),
    (httpx.ConnectTimeout, 3),
])
def test_transport_timeout_logs_type_without_private_error(
    llm, monkeypatch, caplog, timeout_type, expected_calls,
):
    calls = 0
    private_error = "private upstream timeout details"

    async def achat(chat):
        nonlocal calls
        calls += 1
        raise timeout_type(private_error)

    async def sleep(delay):
        pass

    llm.fast_llm_client._client = SimpleNamespace(achat=achat)
    monkeypatch.setattr(llm.asyncio, "sleep", sleep)
    with caplog.at_level(logging.INFO), pytest.raises(llm.LLMGenerationError) as caught:
        asyncio.run(llm.fast_llm_client.generate_json_object(PRIVATE_SOURCE, {}))

    assert isinstance(caught.value.__cause__, timeout_type)
    assert calls == expected_calls
    assert any(re.fullmatch(
        r"Таймаут транспорта LLM: прошло \d+\.\d{2} с, лимит запроса 0\.10 с, тип "
        + timeout_type.__name__, record.getMessage(),
    ) for record in caplog.records)
    assert "Истёк лимит запроса LLM" not in caplog.text
    assert "Ответ LLM получен" not in caplog.text
    assert all(value not in caplog.text for value in (PRIVATE_SOURCE, PRIVATE_KEY, private_error))


def test_outer_deadline_is_not_logged_as_request_timeout(llm, caplog):
    cancelled = False

    async def achat(chat):
        nonlocal cancelled
        try:
            await asyncio.Future()
        finally:
            cancelled = True

    async def run():
        async with asyncio.timeout(0.01):
            await llm.fast_llm_client.generate_json_object(PRIVATE_SOURCE, {})

    llm.fast_llm_client._client = SimpleNamespace(achat=achat)
    with caplog.at_level(logging.INFO), pytest.raises(TimeoutError):
        asyncio.run(run())

    assert cancelled
    assert "Истёк лимит запроса LLM" not in caplog.text
    assert "Таймаут транспорта LLM" not in caplog.text
    assert "Ответ LLM получен" not in caplog.text
    assert PRIVATE_SOURCE not in caplog.text
    assert PRIVATE_KEY not in caplog.text


def test_request_override_allows_longer_stream_without_changing_shared_settings(llm, monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_fast_api_timeout", 0.001)
    client = llm.FastLLMClient(stream=True, request_timeout=0.5)

    async def achat(chat):
        assert chat["stream"] is True
        await asyncio.sleep(0.01)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))])

    client._client = SimpleNamespace(achat=achat)
    assert asyncio.run(client.generate_json_object("test", {})) == {"ok": True}
    assert llm.settings.llm_fast_api_timeout == 0.001


def test_request_override_is_applied_to_transport_and_deadline(llm):
    client = llm.FastLLMClient(request_timeout=0.01)
    assert client.client._timeout == 0.01
    cancelled = []

    async def achat(chat):
        try:
            await asyncio.Future()
        finally:
            cancelled.append(True)

    client._client = SimpleNamespace(achat=achat)
    with pytest.raises(llm.LLMGenerationError) as error:
        asyncio.run(client.generate_json_object("test", {}))
    assert isinstance(error.value.__cause__, TimeoutError)
    assert cancelled == [True]


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_request_override_rejects_unbounded_timeouts(llm, value):
    with pytest.raises(ValueError):
        llm.FastLLMClient(request_timeout=value)
