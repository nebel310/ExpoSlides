from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from httpx import ConnectError
from pydantic import BaseModel, Field, ValidationError

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


class ShortTitle(BaseModel):
    title: str = Field(min_length=1, max_length=12)


@pytest.fixture
def llm(monkeypatch, service_importer):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    module = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    monkeypatch.setattr(module.settings, "llm_response_retries", 5)
    return module


def response(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def http_error(status):
    request = httpx.Request("POST", "https://example.test/private-url")
    response = httpx.Response(status, request=request, content=b"private response body")
    return httpx.HTTPStatusError("private response body", request=request, response=response)


def install_async_response(llm, monkeypatch, content):
    calls = []

    async def achat(chat):
        calls.append(chat)
        return response(content)

    monkeypatch.setattr(llm.fast_llm_client.client, "achat", achat)
    return calls


def test_fast_profile_is_lazy_and_configures_separate_transport_timeout(
    monkeypatch, service_importer
):
    constructors = []
    chats = []

    class FakeChatCompletionsClient:
        def __init__(self, **kwargs):
            constructors.append(kwargs)

        async def achat(self, chat):
            chats.append(chat)
            return response('{"title":"Кратко"}')

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://router.huggingface.co/v1")
    monkeypatch.setenv("LLM_API_TIMEOUT", "37")
    monkeypatch.setenv("LLM_FAST_API_TIMEOUT", "13")
    monkeypatch.setenv("LLM_FAST_MODEL", "Qwen/Qwen3.8-27B:deepinfra")
    module = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    monkeypatch.setattr(module, "ChatCompletionsClient", FakeChatCompletionsClient)
    module.LLMClient()
    client = module.FastLLMClient()
    assert len(constructors) == 1
    assert constructors[0] == {
        "base_url": "https://router.huggingface.co/v1", "api_key": "test-key", "timeout": 37,
    }

    result = asyncio.run(client.generate_json("Источник", ShortTitle))

    assert result.title == "Кратко"
    assert len(constructors) == 2
    assert constructors[1] == {
        "base_url": "https://router.huggingface.co/v1", "api_key": "test-key", "timeout": 13,
    }
    assert chats[0]["model"] == "Qwen/Qwen3.8-27B:deepinfra"
    assert len(chats) == 1


def test_custom_endpoint_uses_chat_transport_configuration(llm, monkeypatch):
    captured = {}

    def transport(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(llm.settings, "llm_base_url", "https://custom.example.test/v1")
    monkeypatch.setattr(llm, "ChatCompletionsClient", transport)

    assert llm.fast_llm_client.client is not None
    assert captured == {
        "base_url": "https://custom.example.test/v1", "api_key": "test-key",
        "timeout": llm.settings.llm_fast_api_timeout,
    }


def test_fast_settings_validate_deadline_and_default_model(llm):
    defaults = llm.settings.__class__(_env_file=None)
    assert defaults.llm_model == "Qwen/Qwen3.8-27B:deepinfra"
    assert defaults.llm_fast_model == "Qwen/Qwen3.8-27B:deepinfra"
    assert defaults.llm_fast_repair_model == "Qwen/Qwen3.8-27B:deepinfra"
    assert defaults.llm_base_url == "https://router.huggingface.co/v1"
    assert defaults.llm_reasoning_effort == "none"
    assert defaults.llm_fast_api_timeout == 180
    assert defaults.fast_generation_timeout == 240
    for fields in (
        {"llm_fast_api_timeout": 0},
        {"llm_fast_model": ""},
        {"llm_fast_repair_model": ""},
        {"fast_generation_timeout": 29},
        {"fast_generation_timeout": 271},
        {"llm_reasoning_effort": "unsupported"},
    ):
        with pytest.raises(ValidationError):
            llm.settings.__class__(_env_file=None, **fields)


@pytest.mark.parametrize("effort", ["none", "low", "medium", "xhigh"])
def test_settings_accept_supported_reasoning_efforts(llm, effort):
    configured = llm.settings.__class__(_env_file=None, llm_reasoning_effort=effort)
    assert configured.llm_reasoning_effort == effort


def test_raw_object_preserves_valid_fields_for_pipeline_repair(llm, monkeypatch):
    data = {"good": "Коротко", "bad": 42, "extra": ["исходные данные"]}
    calls = install_async_response(llm, monkeypatch, json.dumps(data, ensure_ascii=False))
    schema = {
        "type": "object",
        "properties": {"good": {"type": "string"}, "bad": {"type": "string"}},
        "required": ["good", "bad"],
        "additionalProperties": False,
    }

    assert asyncio.run(llm.fast_llm_client.generate_json_object("Источник", schema)) == data
    assert len(calls) == 1
    assert calls[0]["messages"] == [{"role": "user", "content": "Источник"}]
    assert calls[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "exposlides_response", "schema": schema, "strict": True},
    }

    with pytest.raises(llm.LLMGenerationError) as error:
        asyncio.run(llm.fast_llm_client.generate_json_with_schema("Источник", schema))
    assert error.value.invalid_response is True
    assert error.value.response_data == data
    assert len(calls) == 2


def test_pydantic_error_keeps_parsed_data_and_does_not_retry(llm, monkeypatch, caplog):
    sensitive = "Секретный исходный материал превышает лимит"
    data = {"title": sensitive}
    calls = install_async_response(llm, monkeypatch, json.dumps(data, ensure_ascii=False))
    with caplog.at_level(logging.INFO):
        with pytest.raises(llm.LLMGenerationError) as error:
            asyncio.run(llm.fast_llm_client.generate_json(sensitive, ShortTitle))
    assert error.value.invalid_response is True
    assert error.value.response_data == data
    assert sensitive not in str(error.value)
    assert sensitive not in caplog.text
    assert len(calls) == 1


@pytest.mark.parametrize("content", ["", "[]", "null", "не JSON", '{"title":'])
def test_invalid_json_has_typed_repairable_error_without_retry(llm, monkeypatch, content):
    calls = install_async_response(llm, monkeypatch, content)
    with pytest.raises(llm.LLMGenerationError) as error:
        asyncio.run(llm.fast_llm_client.generate_json_object("Источник", {"type": "object"}))
    assert error.value.invalid_response is True
    assert error.value.response_data is None
    assert len(calls) == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 501])
def test_permanent_http_errors_never_retry(llm, monkeypatch, status, caplog):
    calls = []

    async def achat(chat):
        calls.append(chat)
        raise http_error(status)

    monkeypatch.setattr(llm.fast_llm_client.client, "achat", achat)
    with caplog.at_level(logging.INFO):
        with pytest.raises(llm.LLMGenerationError) as error:
            asyncio.run(llm.fast_llm_client.generate_json_object("Источник", {}))
    assert not getattr(error.value, "invalid_response", False)
    assert "private response body" not in caplog.text
    assert "private response body" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_http_errors_retry_twice_and_recover(llm, monkeypatch, status, caplog):
    calls = []
    delays = []

    async def achat(chat):
        calls.append(chat)
        if len(calls) <= 2:
            raise http_error(status)
        return response('{"title":"Кратко"}')

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(llm.fast_llm_client.client, "achat", achat)
    monkeypatch.setattr(llm.asyncio, "sleep", sleep)
    with caplog.at_level(logging.INFO):
        result = asyncio.run(llm.fast_llm_client.generate_json_object(
            "private source text", {}, model="repair-model",
        ))

    assert result == {"title": "Кратко"}
    assert len(calls) == 3
    assert all(chat is calls[0] for chat in calls)
    assert all(chat["model"] == "repair-model" for chat in calls)
    assert delays == [1, 2]
    assert f"HTTP {status}" in caplog.text
    assert "private" not in caplog.text


@pytest.mark.parametrize("status", [429, 503])
def test_transient_http_retry_has_fixed_bound_and_redacted_error(
    llm, monkeypatch, status, caplog,
):
    calls = []
    delays = []

    async def achat(chat):
        calls.append(chat)
        raise http_error(status)

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(llm.fast_llm_client.client, "achat", achat)
    monkeypatch.setattr(llm.asyncio, "sleep", sleep)
    with caplog.at_level(logging.INFO):
        with pytest.raises(llm.LLMGenerationError) as error:
            asyncio.run(llm.fast_llm_client.generate_json_object("private source", {}))

    assert len(calls) == 3
    assert delays == [1, 2]
    assert "private" not in caplog.text
    assert "private" not in str(error.value)
    assert not getattr(error.value, "invalid_response", False)


def test_connection_errors_have_bounded_redacted_retries(llm, monkeypatch):
    calls = []
    delays = []

    async def achat(chat):
        calls.append(chat)
        raise ConnectError("private connection details")

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(llm.fast_llm_client.client, "achat", achat)
    monkeypatch.setattr(llm.asyncio, "sleep", sleep)
    with pytest.raises(llm.LLMGenerationError) as error:
        asyncio.run(llm.fast_llm_client.generate_json_object("Источник", {}))

    assert len(calls) == 3
    assert delays == [1, 2]
    assert "private" not in str(error.value)


@pytest.mark.parametrize("outer_deadline", [False, True])
def test_deadline_cancels_retry_backoff_without_another_call(llm, monkeypatch, outer_deadline):
    calls = []
    cancelled = []

    async def achat(chat):
        calls.append(chat)
        raise http_error(429)

    async def sleep(delay):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(delay)

    monkeypatch.setattr(llm.fast_llm_client.client, "achat", achat)
    monkeypatch.setattr(llm.asyncio, "sleep", sleep)
    if not outer_deadline:
        monkeypatch.setattr(llm.settings, "llm_fast_api_timeout", 0.01)

    async def run():
        if outer_deadline:
            async with asyncio.timeout(0.01):
                await llm.fast_llm_client.generate_json_object("Источник", {})
        else:
            await llm.fast_llm_client.generate_json_object("Источник", {})

    expected = TimeoutError if outer_deadline else llm.LLMGenerationError
    with pytest.raises(expected):
        asyncio.run(run())

    assert len(calls) == 1
    assert cancelled == [1]


@pytest.mark.parametrize("outer_deadline", [False, True])
def test_async_deadline_cancels_active_transport(llm, monkeypatch, outer_deadline):
    calls = []
    cancelled = []

    async def achat(chat):
        calls.append(chat)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(llm.fast_llm_client.client, "achat", achat)
    if not outer_deadline:
        monkeypatch.setattr(llm.settings, "llm_fast_api_timeout", 0.01)

    async def run():
        if outer_deadline:
            async with asyncio.timeout(0.01):
                await llm.fast_llm_client.generate_json_object("Источник", {})
        else:
            await llm.fast_llm_client.generate_json_object("Источник", {})

    expected = TimeoutError if outer_deadline else llm.LLMGenerationError
    with pytest.raises(expected) as error:
        asyncio.run(run())
    assert not getattr(error.value, "invalid_response", False)
    assert len(calls) == 1
    assert cancelled == [True]


def test_model_setting_is_read_for_each_request(llm, monkeypatch):
    calls = install_async_response(llm, monkeypatch, '{}')
    monkeypatch.setattr(llm.settings, "llm_fast_model", "first-model")
    asyncio.run(llm.fast_llm_client.generate_json_object("Источник", {}))
    monkeypatch.setattr(llm.settings, "llm_fast_model", "second-model")
    asyncio.run(llm.fast_llm_client.generate_json_object("Источник", {}))
    assert [chat["model"] for chat in calls] == ["first-model", "second-model"]


def test_request_model_override_does_not_change_normal_generation_model(llm, monkeypatch):
    calls = install_async_response(llm, monkeypatch, '{}')
    monkeypatch.setattr(llm.settings, "llm_fast_model", "default-model")
    monkeypatch.setattr(llm.settings, "llm_fast_repair_model", "repair-model")

    async def run():
        await llm.fast_llm_client.generate_json_object(
            "Исправить", {}, model=llm.settings.llm_fast_repair_model,
        )
        await llm.fast_llm_client.generate_json_object("Создать", {})
        await llm.fast_llm_client.generate_json_object("Создать", {}, model=None)

    asyncio.run(run())

    assert [chat["model"] for chat in calls] == ["repair-model", "default-model", "default-model"]
    assert llm.settings.llm_fast_model == "default-model"


def test_fast_repair_model_can_be_configured_from_environment(llm, monkeypatch):
    monkeypatch.setenv("LLM_FAST_REPAIR_MODEL", "custom-repair-model")

    settings = llm.settings.__class__(_env_file=None)

    assert settings.llm_fast_repair_model == "custom-repair-model"
