from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
SOURCE = "Команда готовит запуск продукта и описывает стратегию развития."
TEXT = "Команда готовит запуск продукта"


def _load(service_importer):
    fast = service_importer(CONTENT_SERVICE_ROOT, "app.graph.fast")
    models = importlib.import_module("app.models.presentation")
    graph = importlib.import_module("app.models.graph_state")
    field = fast._Field(1, "28", models.PlaceholderData(
        idx=28, placeholder_type="BODY", max_length=16,
    ))
    return fast, models, graph, field


@pytest.mark.parametrize("original", [
    "LangChain работает вдвое быстрее прежней системы.",
    "LangChain требует втрое меньше памяти.",
    "LangChain запрещён политикой компании.",
    "LangChain недоступен для внешних клиентов.",
    "LangChain отключен на рабочих серверах.",
    "LangChain отсутствует в этой сборке продукта.",
    "LangChain is unavailable for external clients.",
])
def test_rescue_does_not_remove_word_based_quantity_or_negative_state(
    service_importer, original,
):
    fast, _, _, field = _load(service_importer)

    assert fast._source_label_fallback(
        field, original, source_text=original, require_exact_facts=True,
    ) is None
    assert fast._fitting_alternatives(
        field, original, ["LangChain"], source_text=original, require_exact_facts=True,
    ) == []


@pytest.mark.parametrize("context", [
    "LangChain работает вдвое быстрее",
    "LangChain запрещён политикой компании",
    "LangChain недоступен для внешних клиентов",
])
def test_topic_context_does_not_remove_word_based_fact_or_negative_state(
    service_importer, context,
):
    fast, _, _, field = _load(service_importer)

    assert fast._source_label_fallback(
        field, "Инструменты создания интеллектуальных агентов", source_text=context,
        require_exact_facts=True, topic_context=context,
    ) is None


@pytest.mark.parametrize("original,candidate", [
    ("LangChain работает вдвое быстрее прежней системы.", "LangChain вдвое быстрее"),
    ("LangChain запрещён политикой компании.", "LangChain запрещен"),
    ("LangChain недоступен для внешних клиентов.", "LangChain недоступен"),
])
def test_repair_can_preserve_word_based_fact_and_negative_state(
    service_importer, original, candidate,
):
    fast, _, _, field = _load(service_importer)
    field.placeholder.max_length = 32

    assert fast._fitting_alternatives(
        field, original, [candidate], source_text=original, require_exact_facts=True,
    ) == [candidate]


def test_fifteen_slide_mixed_json_types_repair_only_bad_fields(monkeypatch, service_importer):
    fast, models, graph, _ = _load(service_importer)
    bad_values = [None, True, 42, 2.5, {"text": TEXT}, [TEXT], ""]
    state = graph.ContentGraphState(
        script=SOURCE,
        presentation=models.PresentationData(slides=[models.SlideData(
            index=index,
            placeholders=[models.PlaceholderData(
                idx=key, placeholder_type="BODY", max_length=80,
            ) for key in (0, 1)],
        ) for index in range(1, 16)]),
    )
    state.settings.max_slides = 15
    draft = {
        "analysis": {
            "topic": "Запуск продукта", "audience": "", "objective": "", "blocks": [{
                "index": 1, "heading": "Запуск продукта", "summary": SOURCE,
                "key_points": [SOURCE], "facts": [],
            }], "key_messages": [SOURCE], "facts": [],
        },
        "plan": {"slides": [{
            "template_slide_index": index, "title": "Запуск продукта", "content": SOURCE,
            "purpose": "Описать стратегию", "key_message": SOURCE, "source_block_indices": [1],
        } for index in range(1, 16)]},
    }
    bad_aliases = [f"field_{2 * index + 1:04d}" for index in range(len(bad_values))]
    calls = []

    class Client:
        async def generate_json(self, prompt, model, strict=True):
            return model.model_validate(draft)

        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append(schema)
            response = {alias: TEXT for alias in schema["required"]}
            if len(calls) == 1:
                response.update(zip(bad_aliases, bad_values, strict=True))
            else:
                assert len(calls) == 2
                assert schema["required"] == bad_aliases
            return response

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    result = asyncio.run(fast.generate_fast(state))

    assert result["validation"].ok
    assert len(calls) == 2
    assert list(result["content"]) == list(range(1, 16))
    assert all(slide.placeholders == {"0": TEXT, "1": TEXT}
               for slide in result["content"].values())
