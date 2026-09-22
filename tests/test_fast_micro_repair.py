from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
SOURCE = "Команда готовит запуск продукта и описывает стратегию развития."


def _load(service_importer, count=1, limit=18):
    fast = service_importer(CONTENT_SERVICE_ROOT, "app.graph.fast")
    presentation = importlib.import_module("app.models.presentation")
    fields = {
        f"field_{index:04d}": fast._Field(1, str(index), presentation.PlaceholderData(
            idx=index, placeholder_type="TITLE", max_length=limit,
        )) for index in range(count)
    }
    return fast, fields


def test_collects_all_groups_and_only_retries_remaining_field(monkeypatch, service_importer):
    fast, fields = _load(service_importer, count=33)
    calls = []

    class Client:
        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append((prompt, schema))
            if len(calls) <= 3:
                return {
                    alias: [SOURCE] * 3 if alias == "field_0000" else ["Продукт"] * 3
                    for alias in schema["required"]
                }
            assert len(calls) == 4
            assert schema["required"] == ["field_0000"]
            assert schema["properties"]["field_0000"]["maxLength"] == 18
            assert 'Целевая длина: {"field_0000":9}' in prompt
            assert "одно-два слова" in prompt
            assert "field_0001" not in prompt
            return {"field_0000": "Запуск"}

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    result = asyncio.run(fast._request_length_alternatives(
        fields, {alias: SOURCE for alias in fields},
    ))

    assert len(calls) == 4
    assert result == {alias: "Запуск" if alias == "field_0000" else "Продукт" for alias in fields}


def test_micro_repair_recovers_whole_term_after_three_real_shaped_overlong_names(
    monkeypatch, service_importer,
):
    fast, fields = _load(service_importer, limit=22)
    names = [
        "Паттерны архитектуры мульти-агентных систем",
        "Мульти-агентные архитектурные паттерны",
        "Архитектура мульти-агентов",
    ]
    assert all(len(name) > 22 for name in names)
    calls = []

    class Client:
        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append(schema)
            if len(calls) == 1:
                return {"field_0000": names}
            assert len(calls) == 2
            return {"field_0000": "Архитектура"}

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    result = asyncio.run(fast._request_length_alternatives(fields, {"field_0000": names[0]}))

    assert result == {"field_0000": "Архитектура"}
    assert len(calls) == 2


def test_more_than_sixteen_remaining_fields_cannot_start_another_batch(
    monkeypatch, service_importer,
):
    fast, fields = _load(service_importer, count=17)
    calls = []

    class Client:
        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append(schema)
            assert len(calls) <= 2
            return {alias: [SOURCE] * 3 for alias in schema["required"]}

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    with pytest.raises(fast.ContentValidationError, match="нет короткого текста"):
        asyncio.run(fast._request_length_alternatives(fields, {alias: SOURCE for alias in fields}))
    assert len(calls) == 2


@pytest.mark.parametrize("original,answer", [
    (SOURCE, SOURCE),
    ("Рост достиг 18% по итогам работы", "Рост"),
    ("Нельзя использовать устаревшую модель", "Модель"),
    (SOURCE, "Продукт 18%"),
    (SOURCE, "Разработ…"),
])
def test_micro_repair_does_not_bypass_limits_facts_negation_or_whole_words(
    monkeypatch, service_importer, original, answer,
):
    fast, fields = _load(service_importer)
    calls = []

    class Client:
        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append(schema)
            if len(calls) == 1:
                return {"field_0000": [original] * 3}
            assert len(calls) == 2
            return {"field_0000": answer}

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    with pytest.raises(fast.ContentValidationError, match="нет короткого текста"):
        asyncio.run(fast._request_length_alternatives(fields, {"field_0000": original}))
    assert len(calls) == 2


@pytest.mark.parametrize("response", [
    {}, {"field_0000": ["Запуск"]}, {"field_0000": "Запуск", "unknown": "Продукт"},
])
def test_micro_repair_requires_exact_keys_and_string_values(monkeypatch, service_importer, response):
    fast, fields = _load(service_importer)
    calls = []

    class Client:
        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append(schema)
            assert len(calls) <= 2
            return {"field_0000": [SOURCE] * 3} if len(calls) == 1 else response

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    with pytest.raises(fast.ContentValidationError, match="неверные поля или типы"):
        asyncio.run(fast._request_length_alternatives(fields, {"field_0000": SOURCE}))
    assert len(calls) == 2


def test_micro_repair_can_be_cancelled_by_existing_deadline(monkeypatch, service_importer):
    fast, fields = _load(service_importer)
    calls = []
    cancelled = []

    class Client:
        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append(schema)
            if len(calls) == 1:
                return {"field_0000": [SOURCE] * 3}
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

    monkeypatch.setattr(fast, "fast_llm_client", Client())

    async def run():
        async with asyncio.timeout(0.01):
            return await fast._request_length_alternatives(fields, {"field_0000": SOURCE})

    with pytest.raises(TimeoutError):
        asyncio.run(run())
    assert len(calls) == 2
    assert cancelled == [True]


def test_pipeline_validates_result_after_single_micro_repair(monkeypatch, service_importer):
    fast, fields = _load(service_importer)
    graph = importlib.import_module("app.models.graph_state")
    presentation = importlib.import_module("app.models.presentation")
    state = graph.ContentGraphState(script=SOURCE, presentation=presentation.PresentationData(
        slides=[presentation.SlideData(index=1, placeholders=[
            fields["field_0000"].placeholder,
            presentation.PlaceholderData(idx=1, placeholder_type="BODY", max_length=120),
        ])],
    ))
    draft = {
        "analysis": {
            "topic": "Запуск продукта", "audience": "", "objective": "",
            "blocks": [{
                "index": 1, "heading": "Стратегия запуска", "summary": SOURCE,
                "key_points": [SOURCE], "facts": [],
            }],
            "key_messages": [SOURCE], "facts": [],
        },
        "plan": {"slides": [{
            "template_slide_index": 1, "title": "Стратегия запуска", "content": SOURCE,
            "purpose": "Раскрыть стратегию", "key_message": SOURCE, "source_block_indices": [1],
        }]},
    }
    calls = []

    class Client:
        async def generate_json(self, prompt, model, strict=True):
            return model.model_validate(draft)

        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append(schema)
            if len(calls) <= 2:
                return {alias: SOURCE for alias in schema["required"]}
            assert schema["required"] == ["field_0000"]
            if len(calls) == 3:
                return {"field_0000": [SOURCE] * 3}
            assert len(calls) == 4
            return {"field_0000": "Запуск"}

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    result = asyncio.run(fast.generate_fast(state))

    assert result["validation"].ok
    assert result["content"][1].placeholders == {"0": "Запуск", "1": SOURCE}
    assert len(calls) == 4
