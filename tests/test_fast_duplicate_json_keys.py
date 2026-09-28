from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


@pytest.fixture
def llm(monkeypatch, service_importer):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    return service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")


@pytest.mark.parametrize("content", [
    '{"plan":{"slides":{"1":{"title":"Первый"},"1":{"title":"Другой"}}}}',
    '{"field_0000":"Первый","field_0000":"Другой"}',
    '{"field_0000":"Одинаковый","field_0000":"Одинаковый"}',
    '{"slides":[{"title":"Первый","title":"Другой"}]}',
    '{"slides":{"1":{"title":"Первый"},"\\u0031":{"title":"Другой"}}}',
    '{"private source key":true,"private source key":false}',
    '```json\n{"slides":{"1":{"title":"Первый"},"1":{"title":"Другой"}}}\n```',
    '{"slides":{"1":{"title":"Первый"},"1":{"title":"Другой"},},}',
    'Ответ:\n{\nerv "slides": {\n"1":{"title":"Первый"},\n'
    '"1":{"title":"Другой"},\n}\n}\nГотово.',
])
def test_duplicate_keys_are_rejected_without_dropping_content(llm, content):
    with pytest.raises(llm._InvalidLLMResponse, match="duplicate JSON object keys") as raised:
        llm.LLMClient._parse_json_object(content)
    assert "private" not in str(raised.value)
    assert "Первый" not in str(raised.value)
    assert "Другой" not in str(raised.value)


def test_duplicate_keys_become_typed_repairable_failure_without_partial_data(llm, caplog):
    content = '{"private source key":"private first","private source key":"private second"}'
    calls = []

    async def achat(chat):
        calls.append(chat)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    llm.fast_llm_client._client = SimpleNamespace(achat=achat)
    with caplog.at_level(logging.INFO):
        with pytest.raises(llm.InvalidLLMGenerationError) as raised:
            asyncio.run(llm.fast_llm_client.generate_json_object("private prompt", {}))

    assert raised.value.invalid_response is True
    assert raised.value.response_data is None
    assert isinstance(raised.value.__cause__, llm._InvalidLLMResponse)
    assert "private" not in str(raised.value)
    assert "private" not in str(raised.value.__cause__)
    assert "private" not in caplog.text
    assert len(calls) == 1


@pytest.mark.parametrize("content", [
    '{"slides":{"2":{"title":"Второй"},"1":{"title":"Первый"}}}',
    '```json\n{"slides":{"2":{"title":"Второй"},"1":{"title":"Первый"},},}\n```',
    'Ответ:\n{\nerv "slides": {\n"2":{"title":"Второй"},\n'
    '"1":{"title":"Первый"},\n}\n}\nГотово.',
])
def test_repeated_property_names_in_distinct_objects_preserve_plan_order(llm, content):
    result = llm.LLMClient._parse_json_object(content)
    assert list(result["slides"]) == ["2", "1"]
    assert result["slides"] == {"2": {"title": "Второй"}, "1": {"title": "Первый"}}


def test_duplicate_looking_text_inside_strings_is_not_interpreted_as_keys(llm):
    content = r'{"text":"\"1\":{},\"1\":{}","other":{"text":"без изменений"}}'
    assert llm.LLMClient._parse_json_object(content) == {
        "text": '"1":{},"1":{}', "other": {"text": "без изменений"},
    }
