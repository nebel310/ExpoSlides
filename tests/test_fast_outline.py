from __future__ import annotations

import asyncio
import copy
import importlib
import json
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
SOURCE = "Команда готовит запуск продукта и описывает стратегию развития."


def _load(service_importer):
    fast = service_importer(CONTENT_SERVICE_ROOT, "app.graph.fast")
    graph = importlib.import_module("app.models.graph_state")
    presentation = importlib.import_module("app.models.presentation")
    state = graph.ContentGraphState(
        script=SOURCE,
        user_mapping={str(index): {} for index in range(1, 16)},
        presentation=presentation.PresentationData(slides=[
            presentation.SlideData(index=index, placeholders=[
                presentation.PlaceholderData(idx=0, placeholder_type="TITLE", max_length=100),
            ]) for index in range(1, 16)
        ]),
    )
    state.settings.max_slides = 15
    return fast, state


def _outline(count):
    return {
        "analysis": {
            "topic": "Запуск продукта", "audience": "", "objective": "",
            "blocks": [{
                "index": 1, "heading": "Стратегия запуска", "summary": SOURCE,
                "key_points": [SOURCE], "facts": [],
            }],
            "key_messages": [SOURCE], "facts": [],
        },
        "plan": {"slides": [{
            "template_slide_index": index, "title": "Стратегия запуска",
            "content": SOURCE, "purpose": "Раскрыть стратегию", "key_message": SOURCE,
            "source_block_indices": [1],
        } for index in range(1, count + 1)]},
    }


class OutlineClient:
    def __init__(self, counts):
        self.counts = iter(counts)
        self.calls = []

    async def generate_json(self, prompt, model, strict=True):
        self.calls.append((prompt, model.model_json_schema()))
        data = _outline(next(self.counts))
        return model.model_validate(data["plan"] if "slides" in model.model_fields else data)


def _slides_schema(schema):
    if "slides" in schema["properties"]:
        return schema["properties"]["slides"]
    plan_name = schema["properties"]["plan"]["$ref"].rsplit("/", 1)[-1]
    return schema["$defs"][plan_name]["properties"]["slides"]


def test_auto_keyed_outline_preserves_order_across_different_layouts(
    monkeypatch, service_importer,
):
    fast, state = _load(service_importer)
    state.user_mapping = None
    state.settings.max_slides = None
    state.presentation.slides[2].placeholders[0].placeholder_type = "BODY"
    original = _outline(15)
    entries = original["plan"]["slides"]
    original["plan"]["slides"] = {
        str(index): {key: value for key, value in entries[index - 1].items()
                     if key != "template_slide_index"}
        for index in (15, 3, 1)
    }
    calls = []

    class Client:
        async def generate_json(self, prompt, model, strict=True):
            schema = _slides_schema(model.model_json_schema())
            assert schema["type"] == "object"
            assert schema["additionalProperties"] is False
            assert schema["maxProperties"] == 15
            calls.append(prompt)
            return model.model_validate(original)

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    result = asyncio.run(fast._generate_outline(state, fast._RepairBudget()))

    assert [item.template_slide_index for item in result.plan.slides] == [15, 3, 1]
    assert len(calls) == 1
    assert isinstance(result.plan.model_dump()["slides"], list)


def test_empty_strict_mapping_requires_all_fifteen_slides_in_prompt_and_schema(
    monkeypatch, service_importer,
):
    fast, state = _load(service_importer)
    client = OutlineClient([14, 15])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast._generate_outline(state, fast._RepairBudget()))

    assert len(result.plan.slides) == 15
    assert len(client.calls) == 2
    for prompt, schema in client.calls:
        assert "РОВНО 15 элементов" in prompt
        assert "Обязательные template_slide_index: [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15]" in prompt
        assert "Пустой объект {}" in prompt
        assert "ровно один раз" in prompt
        assert _slides_schema(schema)["minProperties"] == 15
        assert _slides_schema(schema)["maxProperties"] == 15
        assert _slides_schema(schema)["required"] == [str(index) for index in range(1, 16)]
    assert "план не использовал слайды из пользовательской разметки: 15" in client.calls[1][0]


def test_local_validation_still_rejects_missing_mapped_slide_when_provider_ignores_schema(
    monkeypatch, service_importer,
):
    fast, state = _load(service_importer)
    client = OutlineClient([14, 9])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    with pytest.raises(fast.PlanValidationError, match="пользовательской разметки"):
        asyncio.run(fast._generate_outline(state, fast._RepairBudget()))

    assert len(client.calls) == 2


def test_strict_subset_bounds_count_without_forcing_unmapped_slides(monkeypatch, service_importer):
    fast, state = _load(service_importer)
    state.user_mapping = {"2": {}, "5": {}}
    state.settings.max_slides = 5
    client = OutlineClient([5])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast._generate_outline(state, fast._RepairBudget()))

    assert len(result.plan.slides) == 5
    prompt, schema = client.calls[0]
    assert "от 2 до 5 элементов" in prompt
    assert _slides_schema(schema)["minProperties"] == 2
    assert _slides_schema(schema)["maxProperties"] == 5
    assert _slides_schema(schema)["required"] == ["2", "5"]


def test_non_strict_mapping_keeps_optional_slide_count(monkeypatch, service_importer):
    fast, state = _load(service_importer)
    state.settings.strict_user_mapping = False
    client = OutlineClient([2])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast._generate_outline(state, fast._RepairBudget()))

    assert len(result.plan.slides) == 2
    prompt, schema = client.calls[0]
    assert "РОВНО 15 элементов" not in prompt
    assert _slides_schema(schema)["minProperties"] == 1
    assert _slides_schema(schema)["maxProperties"] == 15
    assert not _slides_schema(schema).get("required")


def test_impossible_strict_mapping_fails_before_llm_request(monkeypatch, service_importer):
    fast, state = _load(service_importer)
    state.settings.max_slides = 10
    client = OutlineClient([])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    with pytest.raises(fast.UserMappingValidationError, match="требует 15 слайдов"):
        asyncio.run(fast._generate_outline(state, fast._RepairBudget()))

    assert client.calls == []


@pytest.mark.parametrize("valid_repair", [False, True])
def test_plan_only_repair_freezes_analysis_and_constrains_existing_indices(
    monkeypatch, service_importer, valid_repair,
):
    fast, state = _load(service_importer)
    first = _outline(15)
    first["analysis"]["blocks"][0]["index"] = 3
    second_block = copy.deepcopy(first["analysis"]["blocks"][0])
    second_block["index"] = 7
    first["analysis"]["blocks"].append(second_block)
    for slide in first["plan"]["slides"]:
        slide["source_block_indices"] = [3]
    first["plan"]["slides"][-1]["source_block_indices"] = [15]
    corrected = copy.deepcopy(first["plan"])
    corrected["slides"][-1]["source_block_indices"] = [7 if valid_repair else 15]
    calls = []
    accepted_analysis = []

    class Client:
        async def generate_json(self, prompt, model, strict=True):
            calls.append((prompt, model.model_json_schema()))
            if len(calls) == 1:
                result = model.model_validate(first)
                accepted_analysis.append(result.analysis)
                return result
            assert "analysis" not in model.model_fields
            return model.model_validate(corrected)

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    if valid_repair:
        result = asyncio.run(fast._generate_outline(state, fast._RepairBudget()))
        assert result.analysis is accepted_analysis[0]
        assert result.analysis.model_dump() == first["analysis"]
        assert len(result.plan.slides) == 15
        assert result.plan.slides[-1].source_block_indices == [7]
    else:
        with pytest.raises(fast.PlanValidationError, match="отсутствуют в анализе: 15"):
            asyncio.run(fast._generate_outline(state, fast._RepairBudget()))

    assert len(calls) == 2
    prompt, schema = calls[1]
    assert set(schema["properties"]) == {"slides"}
    slides_schema = _slides_schema(schema)
    item_name = slides_schema["properties"]["1"]["$ref"].rsplit("/", 1)[-1]
    item = schema["$defs"][item_name]["properties"]
    assert slides_schema["minProperties"] == slides_schema["maxProperties"] == 15
    assert item["source_block_indices"]["items"]["enum"] == [3, 7]
    assert "template_slide_index" not in item
    assert list(slides_schema["properties"]) == [str(index) for index in range(1, 16)]
    assert "<ACCEPTED_ANALYSIS>" in prompt
    assert "<REJECTED_PLAN>" in prompt
    assert "Это индексы блоков анализа, а не номера слайдов" in prompt
    assert "Единственные допустимые source_block_indices: [3,7]" in prompt
    assert prompt.count(f"<SOURCE_SCRIPT>\n{state.script}\n</SOURCE_SCRIPT>") == 1


def test_plan_repair_does_not_get_extra_budget_after_analysis_repair(
    monkeypatch, service_importer,
):
    fast, state = _load(service_importer)
    invalid_analysis = _outline(15)
    invalid_analysis["analysis"]["facts"] = ["27%"]
    invalid_plan = _outline(15)
    invalid_plan["plan"]["slides"][-1]["source_block_indices"] = [15]
    responses = iter([invalid_analysis, invalid_plan])
    calls = []

    class Client:
        async def generate_json(self, prompt, model, strict=True):
            calls.append(prompt)
            assert "analysis" in model.model_fields
            return model.model_validate(next(responses))

    monkeypatch.setattr(fast, "fast_llm_client", Client())

    with pytest.raises(fast.PlanValidationError, match="отсутствуют в анализе: 15"):
        asyncio.run(fast._generate_outline(state, fast._RepairBudget()))

    assert len(calls) == 2


def test_outline_and_plan_repair_never_receive_template_example_facts_or_names(
    monkeypatch, service_importer,
):
    fast, state = _load(service_importer)
    private_example = "Демонстрационное имя Татьяна Петрова и выручка 912 млн"
    for slide in state.presentation.slides:
        slide.layout_name = private_example
        slide.notes = private_example
        slide.placeholders[0].text = private_example
        slide.placeholders[0].name = private_example
    client = OutlineClient([14, 15])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast._generate_outline(state, fast._RepairBudget()))

    assert len(result.plan.slides) == 15
    assert len(client.calls) == 2
    for prompt, _ in client.calls:
        assert private_example not in prompt
        assert "Татьяна" not in prompt
        assert "912" not in prompt
        assert SOURCE in prompt
    descriptors = json.loads(fast._outline_slides_info(state.presentation))
    assert len(descriptors) == 15
    assert set(descriptors[0]) == {"index", "layout_type", "placeholders"}
    assert descriptors[0]["placeholders"] == [{"placeholder_type": "TITLE", "max_length": 100}]


@pytest.mark.parametrize("repair_keeps_numbers", [False, True])
def test_plan_repair_explicitly_removes_unfounded_numbers_from_rejected_draft(
    monkeypatch, service_importer, repair_keeps_numbers,
):
    fast, state = _load(service_importer)
    invalid = _outline(15)
    for ordinal, slide in enumerate(invalid["plan"]["slides"][:5], 1):
        slide["title"] = f"Стратегия запуска: {ordinal} команда"
    corrected = invalid["plan"] if repair_keeps_numbers else _outline(15)["plan"]
    calls = []

    class Client:
        async def generate_json(self, prompt, model, strict=True):
            calls.append(prompt)
            return model.model_validate(invalid if len(calls) == 1 else corrected)

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    if repair_keeps_numbers:
        with pytest.raises(fast.PlanValidationError, match="факты не из источника: 1, 2, 3, 4, 5"):
            asyncio.run(fast._generate_outline(state, fast._RepairBudget()))
    else:
        result = asyncio.run(fast._generate_outline(state, fast._RepairBudget()))
        assert len(result.plan.slides) == 15
        assert all(slide.title == "Стратегия запуска" for slide in result.plan.slides)

    assert len(calls) == 2
    assert "ошибочный черновик, а не источник фактов" in calls[1]
    assert "Удали числа и нумерацию" in calls[1]
    assert "удали ВСЕ цифры из текстовых полей" in calls[1]
    assert "Числовые индексы JSON сохрани" in calls[1]
    assert "не меняй числовые значения" not in calls[1]


@pytest.mark.parametrize("repair_needed", [False, True])
def test_automatic_plan_normalizes_real_inline_numbering_before_grounding(
    monkeypatch, service_importer, repair_needed,
):
    fast, state = _load(service_importer)
    state.user_mapping = None
    state.settings.max_slides = None
    numbered = _outline(3)
    texts = [
        "1. Входные данные → 2. Рассуждение (анализ задачи) → "
        "3. Действие (выбор инструмента) → 4. Повтор цикла до завершения задачи.",
        "1. Определение задачи. 2. Выбор архитектуры. 3. Подбор инструментов. "
        "4. Настройка модели. 5. Итеративная разработка и тестирование.",
        "1. Анализ запроса. 2. Поиск в хранилище. 3. Дополнительный поиск информации.",
    ]
    expected = [
        "Входные данные → Рассуждение (анализ задачи) → "
        "Действие (выбор инструмента) → Повтор цикла до завершения задачи.",
        "Определение задачи. Выбор архитектуры. Подбор инструментов. "
        "Настройка модели. Итеративная разработка и тестирование.",
        "Анализ запроса. Поиск в хранилище. Дополнительный поиск информации.",
    ]
    for slide, text in zip(numbered["plan"]["slides"], texts, strict=True):
        slide["content"] = text
    initial = copy.deepcopy(numbered)
    if repair_needed:
        initial["plan"]["slides"][0]["source_block_indices"] = [999]
    calls = []

    class Client:
        async def generate_json(self, prompt, model, strict=True):
            calls.append(prompt)
            return model.model_validate(initial if len(calls) == 1 else numbered["plan"])

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    result = asyncio.run(fast._generate_outline(state, fast._RepairBudget()))

    assert len(calls) == 1 + repair_needed
    assert [slide.content for slide in result.plan.slides] == expected
    assert [slide.template_slide_index for slide in result.plan.slides] == [1, 2, 3]
    assert all(slide.source_block_indices == [1] for slide in result.plan.slides)
    assert [slide["content"] for slide in numbered["plan"]["slides"]] == texts


def test_numbered_plan_does_not_hide_invented_amounts(monkeypatch, service_importer):
    fast, state = _load(service_importer)
    state.user_mapping = None
    state.settings.max_slides = None
    invalid = _outline(2)
    invalid["plan"]["slides"][0]["content"] = (
        "1. Выручка — 99 млн рублей. 2. Затраты — 7 млн рублей."
    )
    calls = []

    class Client:
        async def generate_json(self, prompt, model, strict=True):
            calls.append(prompt)
            return model.model_validate(invalid if len(calls) == 1 else invalid["plan"])

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    with pytest.raises(fast.PlanValidationError, match="факты не из источника: 7, 99"):
        asyncio.run(fast._generate_outline(state, fast._RepairBudget()))
    assert len(calls) == 2
