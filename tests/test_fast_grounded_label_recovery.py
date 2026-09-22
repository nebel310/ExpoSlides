from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
SOURCE = (
    "LangGraph управляет состоянием агента в рабочей среде. "
    "LangSmith помогает наблюдать за выполнением и исследовать ошибки."
)
TITLE = "Подготовка агентов к рабочей среде"
BAD_PROMISE = "LangGraph гарантирует стабильную работу агента в рабочей среде."
OVERLONG = "Подготовка и наблюдение за агентами в рабочей среде"
ALIAS = "field_0001"


def _load(service_importer, source=SOURCE):
    fast = service_importer(CONTENT_SERVICE_ROOT, "app.graph.fast")
    graph = importlib.import_module("app.models.graph_state")
    presentation = importlib.import_module("app.models.presentation")
    placeholders = [
        presentation.PlaceholderData(idx=0, placeholder_type="BODY", max_length=300),
        presentation.PlaceholderData(
            idx=28, placeholder_type="BODY", text="Имя докладчика", max_length=30,
        ),
    ]
    state = graph.ContentGraphState(
        script=source,
        presentation=presentation.PresentationData(slides=[presentation.SlideData(
            index=1, placeholders=placeholders,
        )]),
    )
    draft = fast.CombinedDraft.model_validate({
        "analysis": {
            "topic": TITLE, "audience": "", "objective": "", "blocks": [{
                "index": 1, "heading": TITLE, "summary": source,
                "key_points": [source], "facts": [],
            }], "key_messages": [source], "facts": [],
        },
        "plan": {"slides": [{
            "template_slide_index": 1, "title": TITLE, "content": source,
            "purpose": "Описать подготовку агентов", "key_message": source,
            "source_block_indices": [1],
        }]},
    })
    field = fast._Field(1, "28", placeholders[1])
    return fast, state, draft, field


def _capture_fallback(monkeypatch, fast):
    calls = []
    original_fallback = fast._source_label_fallback

    def capture(field, original, **kwargs):
        calls.append((original, kwargs))
        return original_fallback(field, original, **kwargs)

    monkeypatch.setattr(fast, "_source_label_fallback", capture)
    return calls


def _install_overlong_answers(monkeypatch, fast):
    prompts = []

    class Client:
        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            prompts.append(prompt)
            assert schema["required"] == [ALIAS]
            assert len(prompts) <= 2
            return {ALIAS: [OVERLONG] * 3 if len(prompts) == 1 else OVERLONG}

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    return prompts


def test_grounding_failure_replaces_bad_promise_with_trusted_plan_before_label_fallback(
    monkeypatch, service_importer,
):
    fast, state, draft, field = _load(service_importer)
    prompts = _install_overlong_answers(monkeypatch, fast)
    fallback_calls = _capture_fallback(monkeypatch, fast)

    result = asyncio.run(fast._request_content_alternatives(
        state, draft, {ALIAS: field}, {ALIAS: BAD_PROMISE},
        [
            "Текст слайдов недостаточно связан с исходным материалом "
            "(совпадение значимых слов результата 30%, общих слов 109)",
            "Слайд 1, placeholder 28: текст длиннее максимума (63 > 30)",
        ],
    ))

    assert result == {ALIAS: "LangGraph"}
    assert len(prompts) == 2
    assert all("гарантирует" not in prompt for prompt in prompts)
    assert len(fallback_calls) == 1
    fallback_input, options = fallback_calls[0]
    assert fallback_input == TITLE + "\n" + SOURCE
    assert BAD_PROMISE not in fallback_input
    assert options["require_exact_facts"] is False
    assert options["trusted_plan_input"] is True


def test_graph_recovers_unconfirmed_numeric_promise_and_preserves_valid_body(
    monkeypatch, service_importer,
):
    fast, state, draft, _ = _load(service_importer)
    bad_value = "LangGraph гарантирует 100% стабильности в рабочей среде."
    calls = []
    fallback_calls = _capture_fallback(monkeypatch, fast)

    class Client:
        async def generate_json(self, prompt, model, strict=True):
            return model.model_validate(draft.model_dump())

        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append((prompt, schema))
            if len(calls) == 1:
                assert schema["required"] == ["field_0000", ALIAS]
                return {"field_0000": SOURCE, ALIAS: bad_value}
            assert schema["required"] == [ALIAS]
            if len(calls) == 2:
                return {ALIAS: bad_value}
            if len(calls) == 3:
                return {ALIAS: [OVERLONG] * 3}
            assert len(calls) == 4
            return {ALIAS: OVERLONG}

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    result = asyncio.run(fast.generate_fast(state))

    assert result["validation"].ok
    assert result["content"][1].placeholders == {"0": SOURCE, "28": "LangGraph"}
    assert len(calls) == 4
    assert len(fallback_calls) == 1
    assert "100%" not in fallback_calls[0][0]
    assert "гарантирует" not in fallback_calls[0][0]
    assert fallback_calls[0][1]["trusted_plan_input"] is True
    assert all("100%" not in prompt for prompt, _ in calls[2:])


@pytest.mark.parametrize("source", [
    "LangGraph обрабатывает 18 запросов во время выполнения агента.",
    "LangGraph использует GPT4 для обработки запросов агента.",
    "LangGraph не выполняет запросы без подтверждения пользователя.",
    "LangGraph недоступен в текущей конфигурации рабочей среды.",
    "LangGraph обрабатывает запросы вдвое быстрее предыдущей системы.",
])
def test_trusted_plan_input_does_not_bypass_fact_or_negation_guards(
    monkeypatch, service_importer, source,
):
    fast, state, draft, field = _load(service_importer, source)
    prompts = _install_overlong_answers(monkeypatch, fast)
    fallback_calls = _capture_fallback(monkeypatch, fast)

    with pytest.raises(fast.ContentValidationError, match="нет короткого текста"):
        asyncio.run(fast._request_content_alternatives(
            state, draft, {ALIAS: field}, {ALIAS: "FOOTER"},
            ["Слайд 1, поле 28: вместо содержания использовано служебное имя поля"],
        ))

    assert len(prompts) == 2
    assert len(fallback_calls) == 1
    assert "FOOTER" not in fallback_calls[0][0]
    assert fallback_calls[0][1]["trusted_plan_input"] is True


def test_inexact_standalone_fallback_requires_explicit_plan_trust(service_importer):
    fast, _, _, field = _load(service_importer)

    assert fast._source_label_fallback(
        field, TITLE + "\n" + SOURCE,
        source_text=SOURCE, require_exact_facts=False,
    ) is None


def test_explicit_plan_trust_does_not_allow_terms_absent_from_source(service_importer):
    fast, _, _, field = _load(service_importer)

    assert fast._source_label_fallback(
        field, "InventedSDK управляет состоянием агента в рабочей среде.",
        source_text=SOURCE, require_exact_facts=False, trusted_plan_input=True,
    ) is None
