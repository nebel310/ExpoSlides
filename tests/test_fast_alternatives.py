from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
SOURCE = "Команда готовит запуск продукта и описывает стратегию развития."
FITTING = "Команда готовит запуск продукта"


def _load(service_importer):
    fast = service_importer(CONTENT_SERVICE_ROOT, "app.graph.fast")
    graph = importlib.import_module("app.models.graph_state")
    presentation = importlib.import_module("app.models.presentation")
    return fast, graph, presentation


def _variants(full, short, keyword):
    return [full, short, keyword]


def _one_field(fast, presentation, limit=20):
    return {"field_0000": fast._Field(1, "0", presentation.PlaceholderData(
        idx=0, name="Заголовок", placeholder_type="TITLE", max_length=limit,
    ))}


def _install_candidates(fast, monkeypatch, result):
    calls = []

    class Client:
        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append((prompt, schema, model))
            if all(field.get("type") == "string" for field in schema["properties"].values()):
                return {alias: variants[-1] for alias, variants in result.items()}
            return result

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    return calls


@pytest.mark.parametrize("mixed_errors", [False, True])
def test_final_alternatives_recover_forty_fields_and_preserve_valid_values(
    monkeypatch, service_importer, mixed_errors,
):
    fast, graph, presentation = _load(service_importer)
    state = graph.ContentGraphState(
        script=SOURCE,
        presentation=presentation.PresentationData(slides=[
            presentation.SlideData(index=slide_index, placeholders=[
                presentation.PlaceholderData(
                    idx=index, name=f"Текст {index}", placeholder_type="BODY", max_length=40,
                ) for index in range(7 if slide_index <= 10 else 6)
            ]) for slide_index in range(1, 16)
        ]),
    )
    draft = fast.CombinedDraft.model_validate({
        "analysis": {
            "topic": "Запуск продукта", "audience": "", "objective": "",
            "blocks": [{
                "index": 1, "heading": "Стратегия запуска", "summary": SOURCE,
                "key_points": [SOURCE], "facts": [],
            }],
            "key_messages": [SOURCE], "facts": [],
        },
        "plan": {"slides": [{
            "template_slide_index": slide_index, "title": "Стратегия запуска",
            "content": SOURCE, "purpose": "Раскрыть стратегию", "key_message": SOURCE,
            "source_block_indices": [1],
        } for slide_index in range(1, 16)]},
    })
    calls = []
    bad_values = {f"field_{index:04d}": SOURCE for index in range(40)}
    if mixed_errors:
        placeholders = [field for slide in state.presentation.slides for field in slide.placeholders]
        placeholders[41].text = "Имя докладчика"
        bad_values.update({
            "field_0040": "Телефон +7 495 123 45 67",
            "field_0041": "Иван Петров",
        })

    class Client:
        async def generate_json(self, prompt, model, strict=True):
            return model.model_validate(draft.model_dump())

        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append((prompt, schema, model))
            if len(calls) == 1:
                return {
                    alias: bad_values.get(alias, FITTING)
                    for alias in schema["required"]
                }
            if next(iter(schema["properties"].values()))["type"] == "string":
                return {alias: bad_values[alias] for alias in schema["required"]}
            return {alias: _variants(SOURCE, FITTING, "Продукт") for alias in schema["required"]}

    monkeypatch.setattr(fast, "fast_llm_client", Client())

    result = asyncio.run(fast.generate_fast(state))

    assert result["validation"].ok
    assert len(result["content"]) == 15
    assert len(calls) == 7  # initial batch, three ordinary repairs, three alternative groups
    for _, schema, model in calls[1:]:
        assert len(schema["required"]) <= 16
        assert model == "Qwen/Qwen3.8-27B:deepinfra"
    for prompt, schema, _ in calls[-3:]:
        assert "SOURCE_SCRIPT" not in prompt
        assert "SLIDE_CONTEXT" not in prompt
        assert len(schema["required"]) <= 16
        assert "495" not in prompt
        assert "Иван Петров" not in prompt
    assert all(
        value == FITTING
        for slide in result["content"].values() for value in slide.placeholders.values()
    )


@pytest.mark.parametrize("response", [
    {},
    {"field_0000": "Одна строка"},
    {"field_0000": ["Первая", "Вторая"]},
    {"field_0000": ["Первая", "Вторая", 3]},
    {"field_0000": ["Первая", "Вторая", " "]},
    {"field_0000": ["Первая", "Вторая", "Третья"], "unknown": []},
])
def test_alternatives_require_exact_shape(monkeypatch, service_importer, response):
    fast, _, presentation = _load(service_importer)
    fields = _one_field(fast, presentation)
    calls = _install_candidates(fast, monkeypatch, response)

    with pytest.raises(fast.ContentValidationError):
        asyncio.run(fast._request_length_alternatives(fields, {"field_0000": SOURCE}))

    assert len(calls) == 1


def test_alternatives_never_cut_a_too_long_candidate(monkeypatch, service_importer):
    fast, _, presentation = _load(service_importer)
    fields = _one_field(fast, presentation, limit=7)
    _install_candidates(fast, monkeypatch, {
        "field_0000": _variants("Подготовка продукта", "Разработка продукта", "Разработка"),
    })

    with pytest.raises(fast.ContentValidationError, match="нет короткого текста"):
        asyncio.run(fast._request_length_alternatives(fields, {"field_0000": SOURCE}))


def test_alternatives_preserve_fact_tokens_and_negation(monkeypatch, service_importer):
    fast, _, presentation = _load(service_importer)
    fields = _one_field(fast, presentation, limit=22)
    _install_candidates(fast, monkeypatch, {
        "field_0000": _variants("Учитывать 18%", "Не учитывать 18%", "Не учитывать 27%"),
    })

    result = asyncio.run(fast._request_length_alternatives(
        fields, {"field_0000": "Не учитывать рост на 18% в прогнозе продаж"},
    ))

    assert result == {"field_0000": "Не учитывать 18%"}


@pytest.mark.parametrize("original,candidates", [
    ("Рост достиг 18% по итогам работы", _variants("Рост", "Результат", "Итоги")),
    ("Нельзя использовать устаревшую модель", _variants("Модель", "Использование", "Подход")),
    ("Показатель достиг 18%", _variants("Рост на 18%", "Вдвое выше 18%", "Втрое выше 18%")),
    (SOURCE, _variants("Разработ…", "- Продукт", "Продукт...")),
])
def test_alternatives_reject_changed_facts_negation_and_fragments(
    monkeypatch, service_importer, original, candidates,
):
    fast, _, presentation = _load(service_importer)
    fields = _one_field(fast, presentation, limit=25)
    _install_candidates(fast, monkeypatch, {"field_0000": candidates})

    with pytest.raises(fast.ContentValidationError, match="нет короткого текста"):
        asyncio.run(fast._request_length_alternatives(fields, {"field_0000": original}))


def test_alternatives_cancellation_stops_before_remaining_groups(monkeypatch, service_importer):
    fast, _, presentation = _load(service_importer)
    fields = {
        f"field_{index:04d}": fast._Field(1, str(index), presentation.PlaceholderData(
            idx=index, placeholder_type="TITLE", max_length=20,
        )) for index in range(33)
    }
    calls = []
    cancelled = []

    class Client:
        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append(schema)
            if len(calls) == 2:
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.append(True)
            return {
                alias: _variants(SOURCE, "Разработка продукта", "Продукт")
                for alias in schema["required"]
            }

    monkeypatch.setattr(fast, "fast_llm_client", Client())

    async def run():
        async with asyncio.timeout(0.01):
            return await fast._request_length_alternatives(
                fields, {alias: SOURCE for alias in fields},
            )

    with pytest.raises(TimeoutError):
        asyncio.run(run())

    assert len(calls) == 2
    assert cancelled == [True]


@pytest.mark.parametrize("bad_text,template_text", [
    ("Телефон +7 495 123 45 67", "Телефон"),
    ("Иван Петров", "Имя докладчика"),
    ("FOOTER", "Нижний колонтитул"),
])
def test_semantic_alternatives_cannot_restore_hallucinated_contact_or_metadata(
    monkeypatch, service_importer, bad_text, template_text,
):
    fast, graph, presentation = _load(service_importer)
    fields = _one_field(fast, presentation, limit=100)
    fields["field_0000"].placeholder.text = template_text
    state = graph.ContentGraphState(
        script=SOURCE,
        presentation=presentation.PresentationData(slides=[presentation.SlideData(
            index=1, placeholders=[fields["field_0000"].placeholder],
        )]),
    )
    draft = fast.CombinedDraft.model_validate({
        "analysis": {
            "topic": "Запуск продукта", "audience": "", "objective": "",
            "blocks": [{
                "index": 1, "heading": "Стратегия запуска", "summary": SOURCE,
                "key_points": [SOURCE], "facts": [],
            }],
            "key_messages": [SOURCE], "facts": [],
        },
        "plan": {"slides": [{
            "template_slide_index": 1, "title": "Стратегия запуска",
            "content": SOURCE, "purpose": "Раскрыть стратегию", "key_message": SOURCE,
            "source_block_indices": [1],
        }]},
    })
    calls = _install_candidates(fast, monkeypatch, {"field_0000": [bad_text] * 3})

    with pytest.raises(fast.ContentValidationError):
        asyncio.run(fast._request_content_alternatives(
            state, draft, fields, {"field_0000": bad_text}, ["Слайд 1: плохой контент"],
        ))

    assert len(calls) == 2
    assert all(bad_text not in prompt for prompt, _, _ in calls)
    assert all(SOURCE in prompt for prompt, _, _ in calls)
