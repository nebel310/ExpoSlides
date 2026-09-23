from __future__ import annotations

import asyncio
import importlib
import json
import logging
from pathlib import Path

import httpx
import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
MODEL = "Qwen/Qwen3.8-27B:deepinfra"
SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string", "minLength": 1, "maxLength": 12}},
    "required": ["title"],
    "additionalProperties": False,
}


@pytest.fixture
def llm(monkeypatch, service_importer):
    monkeypatch.setenv("LLM_API_KEY", "hf_test_token")
    return service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")


@pytest.fixture
def mock_http(monkeypatch):
    sync_client, async_client = httpx.Client, httpx.AsyncClient

    def install(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(httpx, "Client", lambda **kw: sync_client(transport=transport, **kw))
        monkeypatch.setattr(
            httpx, "AsyncClient", lambda **kw: async_client(transport=transport, **kw),
        )

    return install


def generate(llm, mode, *, strict=True):
    client = llm.fast_llm_client if mode == "fast" else llm.llm_client

    async def run():
        try:
            return await client.generate_json_with_schema("Исходный текст", SCHEMA, strict=strict)
        finally:
            if mode == "fast":
                await client.aclose()

    return asyncio.run(run())


@pytest.mark.parametrize("mode", ["standard", "fast"])
@pytest.mark.parametrize("strict", [True, False])
def test_generation_sends_huggingface_schema_and_model(llm, mock_http, mode, strict):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"title":"Пример"}'}, "finish_reason": "stop"}],
        })

    mock_http(respond)
    assert generate(llm, mode, strict=strict) == {"title": "Пример"}
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://router.huggingface.co/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer hf_test_token"
    payload = json.loads(request.content)
    assert payload["model"] == MODEL
    assert payload["messages"] == [{"role": "user", "content": "Исходный текст"}]
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "exposlides_response",
            "schema": llm.LLMClient._schema_for_generation(SCHEMA),
            "strict": strict,
        },
    }
    assert "provider" not in payload
    assert payload["reasoning_effort"] == "none"
    assert payload["temperature"] == llm.settings.llm_temperature
    assert payload["max_tokens"] == llm.settings.llm_max_tokens
    assert SCHEMA["properties"]["title"]["maxLength"] == 12


@pytest.mark.parametrize("mode", ["standard", "fast"])
def test_explicit_none_reasoning_is_sent_to_huggingface(llm, mock_http, monkeypatch, mode):
    monkeypatch.setattr(llm.settings, "llm_reasoning_effort", "none")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"title":"Пример"}'}, "finish_reason": "stop"}],
        })

    mock_http(respond)
    assert generate(llm, mode) == {"title": "Пример"}
    assert len(requests) == 1
    assert str(requests[0].url) == "https://router.huggingface.co/v1/chat/completions"
    assert json.loads(requests[0].content)["reasoning_effort"] == "none"


@pytest.mark.parametrize("base_url, extras", [
    ("https://openrouter.ai/api/v1", {"provider": {"require_parameters": True}}),
    ("https://router.huggingface.co/v1/", {"reasoning_effort": "medium"}),
    ("https://custom.example.test/v1", {}),
    ("https://openrouter.ai.example.test/v1", {}),
])
def test_gateway_parameters_only_sent_to_matching_host(llm, monkeypatch, base_url, extras):
    monkeypatch.setattr(llm.settings, "llm_base_url", base_url)
    monkeypatch.setattr(llm.settings, "llm_reasoning_effort", "medium")
    payload = llm.LLMClient._chat_payload("Текст", SCHEMA, True, MODEL)
    assert {key: payload[key] for key in ("provider", "reasoning_effort") if key in payload} == extras


@pytest.mark.parametrize("mode", ["standard", "fast"])
def test_old_provider_key_is_not_sent_to_huggingface(
    monkeypatch, service_importer, mock_http, mode, caplog,
):
    old_key = "sk-or-v1-offline-secret"
    monkeypatch.setenv("LLM_API_KEY", old_key)
    monkeypatch.setenv("LLM_BASE_URL", "https://router.huggingface.co/v1")
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"title":"Пример"}'}}],
        })

    mock_http(respond)
    with caplog.at_level(logging.INFO), pytest.raises(llm.LLMGenerationError) as caught:
        generate(llm, mode)
    errors = importlib.import_module("app.errors")
    assert errors.content_error_code(caught.value) == "auth"
    assert requests == []
    assert old_key not in caplog.text
    assert old_key not in str(caught.value)


@pytest.mark.parametrize("mode, expected_calls", [("standard", 3), ("fast", 1)])
@pytest.mark.parametrize("body", [
    {"choices": []},
    {"choices": [{"message": {"content": '{"title":"Пример"}'}, "finish_reason": "length"}]},
    {"choices": [{"message": {"content": None}, "finish_reason": "stop"}]},
])
def test_invalid_envelope_has_bounded_typed_failure(
    llm, mock_http, mode, expected_calls, body,
):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=body)

    mock_http(respond)
    with pytest.raises(llm.LLMGenerationError) as caught:
        generate(llm, mode)
    errors = importlib.import_module("app.errors")
    assert errors.content_error_code(caught.value) == "invalid_response"
    assert len(requests) == expected_calls


@pytest.mark.parametrize("mode", ["standard", "fast"])
def test_auth_failure_does_not_retry_or_leak_response(llm, mock_http, mode, caplog):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(401, json={"error": {"message": "private provider body"}})

    mock_http(respond)
    with caplog.at_level(logging.INFO), pytest.raises(llm.LLMGenerationError) as caught:
        generate(llm, mode)
    errors = importlib.import_module("app.errors")
    assert errors.content_error_code(caught.value) == "auth"
    assert len(requests) == 1
    assert "private provider body" not in caplog.text
    assert "hf_test_token" not in caplog.text
    assert "private provider body" not in str(caught.value)
