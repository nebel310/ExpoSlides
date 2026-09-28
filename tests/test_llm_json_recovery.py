from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


def test_plan_recovers_noise_before_source_indices_without_retry(monkeypatch, service_importer):
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    models = importlib.import_module("app.models.graph_state")
    content = '''{"slides": [{
        "template_slide_index": 2,
        "title": "Архитектура агента",
        erv"content": "Модель и инструменты",
        "purpose": "Описать архитектуру",
        "key_message": "Агент использует инструменты",
        "source_block_indices": [
            1,
            erv 3,
            4
        ]
    }]}'''
    calls = []

    def fake_chat(chat):
        calls.append(chat)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(llm.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm.llm_client.client, "chat", fake_chat)
    plan = asyncio.run(llm.llm_client.generate_json("Источник", models.SlidePlan))
    assert plan.slides[0].source_block_indices == [1, 3, 4]
    assert plan.slides[0].content == "Модель и инструменты"
    assert len(calls) == 1


@pytest.mark.parametrize("value", [3, -2, 1.25, True, False, None])
def test_recovers_complete_scalar_tokens(service_importer, value):
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    content = '{"values": [\nerv ' + json.dumps(value) + ',\n]}'
    assert llm.LLMClient._parse_json_object(content) == {"values": [value]}


def test_recovery_preserves_string_values_and_escapes(service_importer):
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    value = 'erv 3,] и ,} и "цитата" и \\ и перенос\nerv 5'
    content = '{"text": ' + json.dumps(value, ensure_ascii=False) + ',\n"ids": [\nerv 3,\n],}'
    assert llm.LLMClient._parse_json_object(content) == {"text": value, "ids": [3]}


@pytest.mark.parametrize("value", ["erv 2 3", "erv 01", "erv 3oops", "erv 1e", "erv"])
def test_does_not_guess_broken_scalar_values(service_importer, value):
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    with pytest.raises(ValueError, match="invalid JSON"):
        llm.LLMClient._parse_json_object('{"ids": [\n' + value + '\n]}')


def test_rejects_truncated_plan(service_importer):
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    with pytest.raises(ValueError, match="invalid JSON"):
        llm.LLMClient._parse_json_object('{"slides": [{"template_slide_index": 1}')


@pytest.mark.parametrize("invalid", ["", "   ", "\n\t"])
def test_empty_placeholder_retries_before_returning(monkeypatch, service_importer, invalid):
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    responses = iter([invalid, "Модель выбирает инструменты"])
    calls = []

    def fake_chat(chat):
        calls.append(chat)
        content = json.dumps({"28": next(responses)})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(llm.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm.llm_client.client, "chat", fake_chat)
    schema = {
        "type": "object",
        "properties": {"28": {"type": "string", "minLength": 1}},
        "required": ["28"],
        "additionalProperties": False,
    }
    result = asyncio.run(llm.llm_client.generate_json_with_schema("Источник", schema))
    assert result == {"28": "Модель выбирает инструменты"}
    assert len(calls) == 2
    assert "nonblank text" in calls[1]["messages"][0]["content"]
    assert json.dumps({"28": invalid}, ensure_ascii=False) in calls[1]["messages"][0]["content"]


def test_length_retry_includes_rejected_value(monkeypatch, service_importer):
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    responses = iter(["Слишком длинный заголовок", "Коротко"])
    calls = []

    def fake_chat(chat):
        calls.append(chat)
        content = json.dumps({"0": next(responses)}, ensure_ascii=False)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(llm.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm.llm_client.client, "chat", fake_chat)
    schema = {
        "type": "object",
        "properties": {"0": {"type": "string", "minLength": 1, "maxLength": 10}},
        "required": ["0"],
    }
    result = asyncio.run(llm.llm_client.generate_json_with_schema("Источник", schema))
    assert result == {"0": "Коротко"}
    correction = calls[1]["messages"][0]["content"]
    assert "Слишком длинный заголовок" in correction
    assert "maxLength 10" in correction
    assert "<REJECTED_RESPONSE>" in correction
    assert '"max_words": 1' in correction
    assert '"target_chars": 5' in correction
    wire = calls[0]["response_format"]["json_schema"]["schema"]["properties"]["0"]
    assert "maxLength" not in wire
    assert "Максимум 10 символов" in wire["description"]
    assert wire["minLength"] == 1
    assert schema["properties"]["0"]["maxLength"] == 10


def test_json_retry_includes_unparseable_response(monkeypatch, service_importer):
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    responses = iter(['{"0": "текст"', '{"0": "текст"}'])
    calls = []

    def fake_chat(chat):
        calls.append(chat)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=next(responses)))]
        )

    monkeypatch.setattr(llm.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm.llm_client.client, "chat", fake_chat)
    result = asyncio.run(llm.llm_client.generate_json_with_schema("Источник", {"type": "object"}))
    assert result == {"0": "текст"}
    assert '<REJECTED_RESPONSE>\n{"0": "текст"\n' in calls[1]["messages"][0]["content"]


def test_generation_schema_preserves_structure_and_original(service_importer):
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {"type": "string", "maxLength": 27, "description": "Заголовок"},
                "maxItems": 2,
            },
        },
        "required": ["items"],
        "additionalProperties": False,
    }
    before = json.dumps(schema)
    result = llm.LLMClient._schema_for_generation(schema)
    assert json.dumps(schema) == before
    assert result["required"] == ["items"]
    assert result["additionalProperties"] is False
    assert result["properties"]["items"]["maxItems"] == 2
    item = result["properties"]["items"]["items"]
    assert item["type"] == "string"
    assert "maxLength" not in item
    assert item["description"].startswith("Заголовок Максимум 27")


def test_field_retry_preserves_valid_values_and_requests_only_invalid(monkeypatch, service_importer):
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    responses = iter([{"0": "Готово", "28": "Очень длинный текст"}, {"28": "Кратко"}])
    calls = []

    def fake_chat(chat):
        calls.append(chat)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps(next(responses), ensure_ascii=False),
        ))])

    monkeypatch.setattr(llm.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm.llm_client.client, "chat", fake_chat)
    schema = {
        "type": "object",
        "properties": {
            "0": {"type": "string", "minLength": 1, "maxLength": 10},
            "28": {"type": "string", "minLength": 1, "maxLength": 10},
        },
        "required": ["0", "28"],
        "additionalProperties": False,
    }
    result = asyncio.run(llm.llm_client.generate_json_with_schema("Источник", schema))
    assert result == {"0": "Готово", "28": "Кратко"}
    retry_schema = calls[1]["response_format"]["json_schema"]["schema"]
    assert set(retry_schema["properties"]) == {"28"}
    assert retry_schema["required"] == ["28"]
    assert retry_schema["additionalProperties"] is False
    assert schema["required"] == ["0", "28"]


@pytest.mark.parametrize("status, recover, expected_calls", [
    (429, True, 2), (429, False, 3), (502, True, 2), (503, False, 3), (401, False, 1),
])
def test_server_retry_is_bounded_and_does_not_retry_auth(
    monkeypatch, service_importer, status, recover, expected_calls,
):
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    errors = importlib.import_module("app.errors")

    calls = []
    delays = []

    def fake_chat(chat):
        calls.append(chat)
        if recover and len(calls) > 1:
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"0":"OK"}'))])
        request = httpx.Request("POST", "https://example.test")
        raise httpx.HTTPStatusError(
            "test failure", request=request, response=httpx.Response(status, request=request),
        )

    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(llm.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm.settings, "llm_response_retries", 2)
    monkeypatch.setattr(llm.llm_client.client, "chat", fake_chat)
    monkeypatch.setattr(llm.asyncio, "sleep", fake_sleep)
    if recover:
        assert asyncio.run(llm.llm_client.generate_json_with_schema("Источник", {})) == {"0": "OK"}
    else:
        with pytest.raises(errors.LLMGenerationError, match="LLM request failed"):
            asyncio.run(llm.llm_client.generate_json_with_schema("Источник", {}))
    assert len(calls) == expected_calls
    assert len(delays) == expected_calls - 1
