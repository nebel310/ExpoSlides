from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
ORIGINAL = "Суб-агенты — координация работой специализированных агентов."
SOURCE = "Суб-агенты выполняют специализированные задачи в общей архитектуре."


def _load(service_importer, limit=22):
    fast = service_importer(CONTENT_SERVICE_ROOT, "app.graph.fast")
    presentation = importlib.import_module("app.models.presentation")
    field = fast._Field(7, "56", presentation.PlaceholderData(
        idx=56, placeholder_type="BODY", max_length=limit,
    ))
    return fast, field


def test_source_label_recovers_one_character_overflow_after_micro_request(
    monkeypatch, service_importer,
):
    fast, field = _load(service_importer)
    micro_answer = "Координация суб-агентов"
    assert len(micro_answer) == 23
    calls = []

    class Client:
        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append(schema)
            if len(calls) == 1:
                return {"field_0026": [ORIGINAL, ORIGINAL, micro_answer]}
            assert len(calls) == 2
            return {"field_0026": micro_answer}

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    result = asyncio.run(fast._request_length_alternatives(
        {"field_0026": field}, {"field_0026": ORIGINAL}, source_text=SOURCE,
        exact_fact_aliases={"field_0026"},
    ))

    assert result == {"field_0026": "Суб-агенты"}
    assert len(calls) == 2


def test_sixteen_character_slot_uses_whole_source_attested_slide_title(
    monkeypatch, service_importer,
):
    fast, field = _load(service_importer, limit=16)
    original = "Агенты действуют автономно, проходя цикл наблюдение-рассуждение-действие."
    source = "Почему агенты? " + original
    calls = []

    class Client:
        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append(schema)
            return {"field_0001": [original] * 3 if len(calls) == 1 else "Автономные агенты"}

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    result = asyncio.run(fast._request_length_alternatives(
        {"field_0001": field}, {"field_0001": original}, source_text=source,
        exact_fact_aliases={"field_0001"}, label_contexts={"field_0001": "Почему агенты?"},
    ))
    assert result == {"field_0001": "Почему агенты?"}
    assert len(calls) == 2


@pytest.mark.parametrize("source,context", [
    ("Автономность расширяет возможности", "Почему агенты?"),
    ("Почему агенты?", "Почему агенты" + " исследуют сложные задачи"),
    ("Новые агенты-эксперты решают задачи", "Агенты"),
    ("Не все агенты действуют автономно", "Не все агенты"),
    ("Вдвое быстрее", "Вдвое быстрее"),
])
def test_whole_slide_title_fallback_stays_source_attested_and_preserves_claims(
    service_importer, source, context,
):
    fast, field = _load(service_importer, limit=16)
    assert fast._source_label_fallback(
        field, "Агенты действуют автономно, проходя цикл наблюдение-рассуждение-действие.",
        source_text=source, require_exact_facts=True, topic_context=context,
    ) is None


@pytest.mark.parametrize("original,source,limit,exact", [
    (ORIGINAL, "Агенты выполняют специализированные задачи.", 22, True),
    ("Суб-агенты — координация работы 18 агентов.", SOURCE, 22, True),
    ("Суб-агенты — координация работы через GPT4.", SOURCE, 22, True),
    ("Суб-агенты — не координируют работу других агентов.", SOURCE, 22, True),
    (ORIGINAL, SOURCE, 41, True),
    ("Суб-агенты координируют работу специализированных агентов.", SOURCE, 22, True),
    (ORIGINAL, SOURCE, 22, False),
    (ORIGINAL, None, 22, True),
    (ORIGINAL, "Мультисуб-агенты выполняют задачи.", 22, True),
    (ORIGINAL, "Суб-агенты-эксперты выполняют задачи.", 22, True),
    (ORIGINAL, "Суб-агенты‑эксперты выполняют задачи.", 22, True),
    (ORIGINAL, SOURCE, 7, True),
    ("Суб-агенты — задачи", SOURCE, 22, True),
    (
        "Тема из более чем четырёх слов: длинное подробное описание",
        "Тема из более чем четырёх слов", 40, True,
    ),
])
def test_source_label_requires_short_grounded_explicit_topic_without_facts_or_negation(
    service_importer, original, source, limit, exact,
):
    fast, field = _load(service_importer, limit)

    assert fast._source_label_fallback(
        field, original, source_text=source, require_exact_facts=exact,
    ) is None


@pytest.mark.parametrize("separator", [": ", " — ", " – "])
def test_source_label_accepts_explicit_separator_and_normalized_whole_phrase(
    service_importer, separator,
):
    fast, field = _load(service_importer)

    result = fast._source_label_fallback(
        field, "Общая архитектура" + separator + "координация специализированных агентов.",
        source_text="В докладе описана общая\nархитектура и её компоненты.",
        require_exact_facts=True,
    )

    assert result == "Общая архитектура"


def test_source_label_never_removes_semantic_negation_to_make_micro_answer_fit(
    monkeypatch, service_importer,
):
    fast, field = _load(service_importer)
    original = "Суб-агенты — не координируют специализированных агентов."
    calls = []

    class Client:
        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append(schema)
            assert len(calls) <= 2
            if len(calls) == 1:
                return {"field_0026": [original] * 3}
            return {"field_0026": "Суб-агенты"}

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    with pytest.raises(fast.ContentValidationError, match="нет короткого текста"):
        asyncio.run(fast._request_length_alternatives(
            {"field_0026": field}, {"field_0026": original}, source_text=SOURCE,
            exact_fact_aliases={"field_0026"},
        ))
    assert len(calls) == 2


def test_speaker_slot_uses_grounded_whole_term_after_all_free_text_repairs_overflow(
    monkeypatch, service_importer,
):
    fast, field = _load(service_importer, limit=16)
    original = "Проектирование AI-агентов на LangChain и LangGraph"
    source = "Сегодня рассматриваем проектирование AI-агентов на LangChain и LangGraph."
    field.placeholder.text = "Имя докладчика"
    calls = []

    class Client:
        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append(schema)
            assert len(calls) <= 2
            if len(calls) == 1:
                return {"field_0001": [original, "Создание AI-агентов", "LangChain и LangGraph"]}
            return {"field_0001": "LangChain и LangGraph"}

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    result = asyncio.run(fast._request_length_alternatives(
        {"field_0001": field}, {"field_0001": original}, source_text=source,
        exact_fact_aliases={"field_0001"},
    ))

    assert result == {"field_0001": "LangChain"}
    assert len(calls) == 2
    assert len(result["field_0001"]) <= field.placeholder.max_length


@pytest.mark.parametrize("original,source,exact", [
    ("Разработка с LangChain требует 18 специалистов", "LangChain и 18 специалистов", True),
    ("LangChain не выполняет эту задачу самостоятельно", "LangChain не выполняет задачу", True),
    ("Разработка приложений с LangChain", "Разработка приложений с LangGraph", True),
    ("Разработка приложений с LangChain", "Разработка приложений с LangChain", False),
    ("Разработка приложений с LangChain", None, True),
])
def test_technical_label_does_not_drop_facts_or_negation_or_use_untrusted_text(
    service_importer, original, source, exact,
):
    fast, field = _load(service_importer, limit=16)
    assert fast._source_label_fallback(
        field, original, source_text=source, require_exact_facts=exact,
    ) is None


@pytest.mark.parametrize("context_field", ["title", "key_message", "content"])
def test_speaker_label_can_use_term_from_validated_slide_topic(
    monkeypatch, service_importer, context_field,
):
    fast, field = _load(service_importer, limit=16)
    graph = importlib.import_module("app.models.graph_state")
    presentation = importlib.import_module("app.models.presentation")
    original = "Создание универсальных агентов для решения любых задач"
    source = original + " с использованием LangChain и LangGraph."
    state = graph.ContentGraphState(
        script=source,
        presentation=presentation.PresentationData(slides=[presentation.SlideData(
            index=field.slide_index, placeholders=[field.placeholder],
        )]),
    )
    draft = fast.CombinedDraft.model_validate({
        "analysis": {
            "topic": "LangChain", "audience": "", "objective": "", "blocks": [{
                "index": 1, "heading": "AI-агенты", "summary": source,
                "key_points": [source], "facts": [],
            }], "key_messages": [source], "facts": [],
        },
        "plan": {"slides": [{
            "template_slide_index": field.slide_index,
            "title": "Архитектурные паттерны агентов",
            "content": original, "purpose": "Описать тему", "key_message": original,
            "source_block_indices": [1],
        }]},
    })
    setattr(draft.plan.slides[0], context_field, source)
    calls = []

    class Client:
        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append(schema)
            return {"field_0001": [original] * 3 if len(calls) == 1 else original}

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    result = asyncio.run(fast._request_content_alternatives(
        state, draft, {"field_0001": field}, {"field_0001": original},
        ["Слайд 7, поле 56: текст длиннее максимума"],
    ))

    assert result == {"field_0001": "LangChain"}
    assert len(calls) == 2


@pytest.mark.parametrize("plan_context,source", [
    ("LangChain недоступен", "LangChain недоступен"),
    ("LangChain работает вдвое быстрее", "LangChain работает вдвое быстрее"),
    ("Используется LangChain", "Используется LangGraph"),
])
def test_plan_context_cannot_supply_ungrounded_or_qualified_fallback(
    service_importer, plan_context, source,
):
    fast, field = _load(service_importer, limit=16)
    assert fast._source_label_fallback(
        field, "Создание универсальных агентов", source_text=source, require_exact_facts=True,
        plan_context=plan_context,
    ) is None


@pytest.mark.parametrize("original,context,source", [
    ("Расходы составили 18 млн рублей", "Агенты LangChain", "LangChain, 18 млн рублей"),
    ("Агенты не умеют выполнять эту задачу", "Агенты LangChain", "LangChain"),
    ("Создание универсальных агентов", "Агенты LangChain", "Агенты LangGraph"),
    (
        "Создание универсальных агентов", "Создание агентов без LangChain",
        "Создание универсальных агентов без LangChain.",
    ),
])
def test_validated_topic_cannot_override_original_facts_or_source(
    service_importer, original, context, source,
):
    fast, field = _load(service_importer, limit=16)
    assert fast._source_label_fallback(
        field, original, source_text=source, require_exact_facts=True, topic_context=context,
    ) is None


@pytest.mark.parametrize("opening,closing", [("'", "'"), ("‘", "’"), ("„", "“"), ("“", "”")])
def test_explicit_topic_accepts_typographic_quote_difference_without_changing_words(
    service_importer, opening, closing,
):
    fast, field = _load(service_importer, limit=30)
    label = f"Паттерн {opening}Маршрутизатор{closing}"
    original = label + ": автоматическое распределение запросов."
    source = "Второй — паттерн «Маршрутизатор», где узел распределяет запросы."
    assert fast._source_label_fallback(
        field, original, source_text=source, require_exact_facts=True,
    ) == label
