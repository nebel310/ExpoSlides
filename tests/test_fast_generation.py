from __future__ import annotations

import asyncio
import copy
import importlib
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
SOURCE = "Команда готовит запуск продукта и описывает стратегию развития."
TEXT = "Команда готовит запуск продукта"


def _load(service_importer):
    fast = service_importer(CONTENT_SERVICE_ROOT, "app.graph.fast")
    graph = importlib.import_module("app.models.graph_state")
    presentation = importlib.import_module("app.models.presentation")
    return fast, graph, presentation


def _state(graph, presentation, count=2, *, source=SOURCE, mapping=None):
    return graph.ContentGraphState(
        script=source,
        user_mapping=mapping,
        presentation=presentation.PresentationData(slides=[
            presentation.SlideData(index=index, placeholders=[
                presentation.PlaceholderData(
                    idx=0, name="Заголовок", placeholder_type="TITLE", max_length=80,
                ),
                presentation.PlaceholderData(
                    name="Основной текст", placeholder_type="BODY", max_length=120,
                ),
            ])
            for index in range(1, count + 1)
        ]),
    )


def _outline(indices=(2, 1), *, fact=""):
    message = TEXT + (f" {fact}" if fact else "")
    return {
        "analysis": {
            "topic": "Запуск продукта",
            "audience": "",
            "objective": "",
            "blocks": [{
                "index": 1,
                "heading": "Стратегия запуска",
                "summary": message,
                "key_points": [message],
                "facts": [fact] if fact else [],
            }],
            "key_messages": [message],
            "facts": [fact] if fact else [],
        },
        "plan": {
            "slides": [{
                "template_slide_index": index,
                "title": "Стратегия запуска продукта",
                "content": message,
                "purpose": "Раскрыть стратегию",
                "key_message": message,
                "source_block_indices": [1],
            } for index in indices],
        },
    }


class FakeClient:
    def __init__(self, outlines, batches, *, valid_alternatives=False):
        self.outlines = iter(outlines)
        self.batches = iter(batches)
        self.valid_alternatives = valid_alternatives
        self.calls = []
        self.last_batch = {}

    async def generate_json(self, prompt, model, strict=True):
        self.calls.append(("outline", prompt, model))
        response = next(self.outlines)
        if isinstance(response, Exception):
            raise response
        if "slides" in model.model_fields and "plan" in response:
            response = response["plan"]
        return model.model_validate(response)

    async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
        self.calls.append(("batch", prompt, schema))
        if any(field.get("type") == "array" for field in schema["properties"].values()):
            return {
                alias: (
                    [self.last_batch.get(alias, "")] * 3
                    if self.valid_alternatives else [self.last_batch.get(alias, ""), "", ""]
                )
                for alias in schema["required"]
            }
        response = next(self.batches)
        if isinstance(response, Exception):
            raise response
        response = response(schema) if callable(response) else response
        self.last_batch.update(response)
        return response


def _valid_batch(schema):
    return {alias: TEXT for alias in schema["required"]}


def test_fifteen_slides_use_two_requests_and_preserve_plan_order(
    monkeypatch, service_importer,
):
    fast, graph, presentation = _load(service_importer)
    indices = list(range(15, 0, -1))
    state = _state(graph, presentation, 15)
    client = FakeClient([_outline(indices)], [_valid_batch])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast.generate_fast(state))

    assert len(client.calls) == 2
    assert list(result["content"]) == indices
    assert result["validation"].ok
    assert result["content"][15].placeholders == {"0": TEXT, "Основной текст": TEXT}
    batch_prompt, schema = client.calls[1][1:]
    assert batch_prompt.count(f"<SOURCE_SCRIPT>\n{SOURCE}\n</SOURCE_SCRIPT>") == 1
    assert list(schema["properties"]) == [f"field_{index:04d}" for index in range(30)]
    assert schema["properties"]["field_0001"]["maxLength"] == 120
    assert schema["additionalProperties"] is False


def test_batch_prompt_omits_original_template_text(service_importer):
    fast, graph, presentation = _load(service_importer)
    state = _state(graph, presentation, count=1)
    state.presentation.slides[0].placeholders[0].text = "Такума Хаяши"
    private_template_text = "Закрытый пример: компания Образец обещает фантастический рост."
    state.presentation.slides[0].placeholders[1].text = private_template_text
    draft = fast.CombinedDraft.model_validate(_outline([1]))
    fields = fast._batch_fields(state, draft.plan)

    prompt = fast._batch_prompt(state, draft, fields, fields, {}, [])

    assert private_template_text not in prompt
    assert "Такума Хаяши" not in prompt
    assert '"example"' not in prompt
    assert '"type":"TITLE"' in prompt
    assert '"max_length":80' in prompt
    assert '"target_chars":60' in prompt
    assert SOURCE in prompt


def test_outline_lists_every_required_fact_and_short_source_quotes(service_importer):
    fast, graph, presentation = _load(service_importer)
    source = (
        "Во втором квартале 2026 года выручка составила 42 млн рублей, рост — 18%. "
        "Валовая маржа достигла 27%.\n\n" + SOURCE
    )
    prompt = fast._outline_prompt(_state(graph, presentation, source=source))

    assert '<REQUIRED_FACT_TOKENS>["18%","2026","27%","42"]' in prompt
    assert "Валовая маржа достигла 27%." in prompt.split("<FACT_SENTENCES>", 1)[1]
    assert "analysis.facts" in prompt
    assert "content хотя бы одного слайда plan.slides" in prompt
    assert "не смешивай проценты разных показателей" in prompt
    assert prompt.count(source) == 1


def test_outline_repair_keeps_fact_checklist_and_names_missing_fact(monkeypatch, service_importer):
    fast, graph, presentation = _load(service_importer)
    source = SOURCE + " Валовая маржа достигла 27%."
    draft = _outline(fact="27%")
    client = FakeClient([_outline(), draft], [
        lambda schema: {alias: TEXT + " 27%" for alias in schema["required"]},
    ])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast.generate_fast(_state(graph, presentation, source=source)))

    assert result["validation"].ok
    assert len(client.calls) == 3
    repair_prompt = client.calls[1][1]
    assert '<REQUIRED_FACT_TOKENS>["27%"]</REQUIRED_FACT_TOKENS>' in repair_prompt
    assert "не сохранены факты из источника: 27%" in repair_prompt
    assert "план не распределил факты: 27%" in repair_prompt


@pytest.mark.parametrize("bad_value", ["", "   ", "д" * 121, 5, "+ Первый пункт"])
def test_schema_repair_only_requests_bad_field_and_preserves_others(
    monkeypatch, service_importer, bad_value,
):
    fast, graph, presentation = _load(service_importer)
    first = {f"field_{index:04d}": TEXT for index in range(4)}
    first["field_0001"] = bad_value
    client = FakeClient([_outline()], [first, {"field_0001": "Стратегия развития продукта"}])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast.generate_fast(_state(graph, presentation)))

    assert len(client.calls) == 3
    assert client.calls[2][2]["required"] == ["field_0001"]
    assert result["content"][2].placeholders == {
        "0": TEXT, "Основной текст": "Стратегия развития продукта",
    }
    assert result["content"][1].placeholders == {"0": TEXT, "Основной текст": TEXT}
    assert '"preserved_fields":{"0":' in client.calls[2][1]


def test_missing_field_repair_does_not_regenerate_valid_slide(monkeypatch, service_importer):
    fast, graph, presentation = _load(service_importer)
    first = {f"field_{index:04d}": TEXT for index in (0, 2, 3)}
    client = FakeClient([_outline()], [first, {"field_0001": TEXT}])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast.generate_fast(_state(graph, presentation)))

    assert client.calls[-1][2]["required"] == ["field_0001"]
    assert list(result["content"]) == [2, 1]
    assert result["validation"].ok


def test_batch_rejects_unknown_alias_and_requires_corrected_response(monkeypatch, service_importer):
    fast, graph, presentation = _load(service_importer)
    first = {f"field_{index:04d}": TEXT for index in range(4)}
    first["unknown"] = TEXT
    client = FakeClient([_outline()], [first, {"unknown": TEXT}])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    with pytest.raises(fast.ContentValidationError, match="unexpected properties"):
        asyncio.run(fast.generate_fast(_state(graph, presentation)))

    assert len(client.calls) == 3


def test_bad_field_after_repair_raises_without_partial_success(monkeypatch, service_importer):
    fast, graph, presentation = _load(service_importer)
    response = {f"field_{index:04d}": TEXT for index in range(4)}
    response["field_0001"] = ""
    client = FakeClient([_outline()], [response, {"field_0001": ""}])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    with pytest.raises(fast.ContentValidationError, match="нужны три текстовых варианта"):
        asyncio.run(fast.generate_fast(_state(graph, presentation)))

    assert len(client.calls) == 4
    assert "nonblank text" in client.calls[2][1]


@pytest.mark.parametrize("stage", ["analysis", "plan", "batch"])
def test_grounding_remains_required_at_every_stage(monkeypatch, service_importer, stage):
    fast, graph, presentation = _load(service_importer)
    state = _state(graph, presentation, source=SOURCE + " Выручка выросла на 18%.")
    draft = _outline(fact="18%")
    if stage == "analysis":
        draft["analysis"]["facts"].append("27%")
        expected_error = fast.AnalysisValidationError
    elif stage == "plan":
        draft["plan"]["slides"][0]["content"] += " 27%"
        expected_error = fast.PlanValidationError
    else:
        expected_error = fast.ContentValidationError
    client = FakeClient(
        [draft, draft],
        [lambda schema: {alias: TEXT + " 27%" for alias in schema["required"]}] * 3,
        valid_alternatives=True,
    )
    monkeypatch.setattr(fast, "fast_llm_client", client)

    expected_message = "нет короткого текста" if stage == "batch" else "27%"
    with pytest.raises(expected_error, match=expected_message):
        asyncio.run(fast.generate_fast(state))

    assert len(client.calls) == (5 if stage == "batch" else 2)
    if stage == "batch":
        assert "добавлены факты не из источника: 27%" in client.calls[2][1]


def test_grounding_retry_preserves_other_slides_and_filters_feedback(monkeypatch, service_importer):
    fast, graph, presentation = _load(service_importer)
    state = _state(graph, presentation, source=SOURCE + " Выручка выросла на 18%.")
    first = {f"field_{index:04d}": TEXT + " 18%" for index in range(4)}
    first["field_0001"] = TEXT + " 27%"
    client = FakeClient([_outline(fact="18%")], [
        first,
        lambda schema: {alias: TEXT + " 18%" for alias in schema["required"]},
    ])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast.generate_fast(state))

    assert client.calls[-1][2]["required"] == ["field_0001"]
    assert "Слайд 2:" in client.calls[-1][1]
    assert "Слайд 1:" not in client.calls[-1][1]
    assert result["content"][1].placeholders["0"] == first["field_0002"]


def test_outline_and_batch_have_independent_single_repairs(monkeypatch, service_importer):
    fast, graph, presentation = _load(service_importer)
    bad_outline = _outline()
    bad_outline["analysis"]["facts"] = ["27%"]
    first = {f"field_{index:04d}": TEXT for index in range(4)}
    first["field_0000"] = ""
    client = FakeClient([bad_outline, _outline()], [first, {"field_0000": TEXT}])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast.generate_fast(_state(graph, presentation)))

    assert result["validation"].ok
    assert [call[0] for call in client.calls] == ["outline", "outline", "batch", "batch"]
    assert client.calls[-1][2]["required"] == ["field_0000"]


def test_failed_batch_repair_stops_after_one_final_alternatives_round(monkeypatch, service_importer):
    fast, graph, presentation = _load(service_importer)
    bad_outline = _outline()
    bad_outline["analysis"]["facts"] = ["27%"]
    client = FakeClient([bad_outline, _outline()], [{"field_0000": ""}] * 2)
    monkeypatch.setattr(fast, "fast_llm_client", client)

    with pytest.raises(fast.ContentValidationError):
        asyncio.run(fast.generate_fast(_state(graph, presentation)))

    assert [call[0] for call in client.calls] == ["outline", "outline", "batch", "batch", "batch"]


@pytest.mark.parametrize("stage", ["outline", "batch"])
def test_invalid_json_has_only_one_retry_per_stage(monkeypatch, service_importer, stage):
    fast, graph, presentation = _load(service_importer)
    error = fast.LLMGenerationError("invalid JSON")
    error.invalid_response = True
    client = FakeClient(
        [error, _outline()] if stage == "outline" else [_outline()],
        [error, _valid_batch] if stage == "batch" else [_valid_batch],
    )
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast.generate_fast(_state(graph, presentation)))

    assert result["validation"].ok
    assert len(client.calls) == 3


def test_transport_error_is_not_retried(monkeypatch, service_importer):
    fast, graph, presentation = _load(service_importer)
    client = FakeClient([fast.LLMGenerationError("unauthorized")], [])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    with pytest.raises(fast.LLMGenerationError, match="unauthorized"):
        asyncio.run(fast.generate_fast(_state(graph, presentation)))

    assert len(client.calls) == 1


@pytest.mark.parametrize("mapping", [{"99": {"0": TEXT}}, {"1": {"missing": TEXT}}])
def test_invalid_mapping_fails_before_request(monkeypatch, service_importer, mapping):
    fast, graph, presentation = _load(service_importer)
    client = FakeClient([], [])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    with pytest.raises(fast.UserMappingValidationError):
        asyncio.run(fast.generate_fast(_state(graph, presentation, mapping=mapping)))

    assert client.calls == []


def test_strict_mapping_requires_slide_in_plan(monkeypatch, service_importer):
    fast, graph, presentation = _load(service_importer)
    client = FakeClient([_outline([1]), _outline([1])], [])
    monkeypatch.setattr(fast, "fast_llm_client", client)
    state = _state(graph, presentation, mapping={"2": {"0": TEXT}})

    with pytest.raises(fast.PlanValidationError, match="пользовательской разметки"):
        asyncio.run(fast.generate_fast(state))

    assert len(client.calls) == 2


def test_valid_mapping_overrides_batch_and_is_checked_against_source(monkeypatch, service_importer):
    fast, graph, presentation = _load(service_importer)
    mapped_text = "Стратегия развития продукта"
    client = FakeClient([_outline()], [_valid_batch])
    monkeypatch.setattr(fast, "fast_llm_client", client)
    state = _state(graph, presentation, mapping={"2": {"0": mapped_text}})

    result = asyncio.run(fast.generate_fast(state))

    assert result["content"][2].placeholders["0"] == mapped_text
    assert list(result["content"]) == [2, 1]


@pytest.mark.parametrize("change", ["duplicate", "unknown", "limit", "block"])
def test_invalid_plan_contract_is_rejected(monkeypatch, service_importer, change):
    fast, graph, presentation = _load(service_importer)
    state = _state(graph, presentation)
    draft = _outline()
    if change == "duplicate":
        draft["plan"]["slides"][1] = copy.deepcopy(draft["plan"]["slides"][0])
        # Свободный образец несовместим: автоматическая замена здесь недопустима.
        state.presentation.slides[0].placeholders[1].placeholder_type = "SUBTITLE"
    elif change == "unknown":
        draft["plan"]["slides"][0]["template_slide_index"] = 99
    elif change == "limit":
        state.settings.max_slides = 1
    else:
        draft["plan"]["slides"][0]["source_block_indices"] = [99]
    client = FakeClient([draft, draft], [])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    with pytest.raises(fast.PlanValidationError):
        asyncio.run(fast.generate_fast(state))

    assert len(client.calls) == 2


def test_final_content_rejects_unsupported_comparison(monkeypatch, service_importer):
    fast, graph, presentation = _load(service_importer)
    client = FakeClient([_outline()], [
        lambda schema: {alias: TEXT + " втрое" for alias in schema["required"]},
    ] * 3, valid_alternatives=True)
    monkeypatch.setattr(fast, "fast_llm_client", client)

    with pytest.raises(fast.ContentValidationError, match="нет короткого текста"):
        asyncio.run(fast.generate_fast(_state(graph, presentation)))

    assert len(client.calls) == 5
    assert "неподтверждённые" in client.calls[2][1]
    assert "втрое" in client.calls[2][1]


@pytest.mark.parametrize("field_error", ["overlong", "missing", "blank", "nonstring"])
@pytest.mark.parametrize("claim", ["27%", "втрое"])
def test_schema_error_does_not_hide_existing_unsupported_claim(
    monkeypatch, service_importer, field_error, claim,
):
    fast, graph, presentation = _load(service_importer)
    state = _state(graph, presentation)
    first = {f"field_{index:04d}": TEXT for index in range(4)}
    first["field_0000"] += " " + claim
    if field_error == "missing":
        del first["field_0001"]
    else:
        first["field_0001"] = {
            "overlong": "д" * 121, "blank": "   ", "nonstring": 3,
        }[field_error]
    client = FakeClient([_outline()], [
        first, {"field_0000": TEXT, "field_0001": TEXT},
    ])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast.generate_fast(state))

    assert result["validation"].ok
    assert client.calls[-1][2]["required"] == ["field_0000", "field_0001"]
    assert claim in client.calls[-1][1]
    assert result["content"][1].placeholders == {"0": TEXT, "Основной текст": TEXT}
    if claim == "27%":
        assert "добавлены факты не из источника: 27%" in client.calls[-1][1]
    else:
        assert "неподтверждённые оценки или сравнения: втрое" in client.calls[-1][1]


def test_overlong_field_does_not_defer_missing_required_facts(monkeypatch, service_importer):
    fast, graph, presentation = _load(service_importer)
    state = _state(graph, presentation, source=SOURCE + " Рост — 18%.")
    first = {
        "field_0000": TEXT,
        "field_0001": "д" * 121,
        "field_0002": TEXT + " 18%",
        "field_0003": TEXT,
    }
    client = FakeClient([_outline(fact="18%")], [
        first, {"field_0000": TEXT + " 18%", "field_0001": TEXT},
    ])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast.generate_fast(state))

    assert result["validation"].ok
    assert client.calls[-1][2]["required"] == ["field_0000", "field_0001"]
    assert "Слайд 2: обязательные факты отсутствуют: 18%" in client.calls[-1][1]
    assert result["content"][1].placeholders["0"] == TEXT + " 18%"


@pytest.mark.parametrize("field_error", ["missing", "blank", "nonstring"])
def test_incomplete_field_defers_only_absence_checks(monkeypatch, service_importer, field_error):
    fast, graph, presentation = _load(service_importer)
    state = _state(graph, presentation, count=1, source=SOURCE + " Рост — 18%.")
    first = {"field_0000": TEXT}
    if field_error != "missing":
        first["field_0001"] = " " if field_error == "blank" else 0
    client = FakeClient([_outline([1], fact="18%")], [
        first, {"field_0001": TEXT + " 18%"},
    ])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast.generate_fast(state))

    assert result["validation"].ok
    assert client.calls[-1][2]["required"] == ["field_0001"]
    assert "обязательные факты отсутствуют" not in client.calls[-1][1]
    assert "Исходные числовые факты отсутствуют" not in client.calls[-1][1]


def test_overlong_field_does_not_defer_source_coverage(monkeypatch, service_importer):
    fast, graph, presentation = _load(service_importer)
    state = _state(graph, presentation, count=1)
    client = FakeClient([_outline([1])], [
        {"field_0000": "Посторонняя тема", "field_0001": "д" * 121},
        _valid_batch,
    ])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast.generate_fast(state))

    assert result["validation"].ok
    assert "Текст слайдов недостаточно связан" in client.calls[-1][1]
    assert client.calls[-1][2]["required"] == ["field_0000", "field_0001"]


def test_hundred_heterogeneous_short_fields_repair_only_invalid_values(
    monkeypatch, service_importer,
):
    fast, graph, presentation = _load(service_importer)
    source = "Команда готовит запуск продукта, описывает стратегию, задачи, подходы и развитие."
    state = _state(graph, presentation, count=15, source=source)
    limits = (7, 10, 14, 20)
    types = ("TITLE", "BODY", "OBJECT", "SUBTITLE")
    field_number = 0
    for slide in state.presentation.slides:
        slide.placeholders = []
        for index in range(7 if slide.index <= 10 else 6):
            slide.placeholders.append(presentation.PlaceholderData(
                idx=index,
                name=f"Поле {index}",
                placeholder_type=types[field_number % len(types)],
                max_length=limits[field_number % len(limits)],
            ))
            field_number += 1
    assert field_number == 100
    words = ("Команда", "запуск", "задачи", "подходы")
    expected = {f"field_{index:04d}": words[index % len(words)] for index in range(100)}
    first = expected.copy()
    first.update({"field_0000": "Слишком длинный заголовок", "field_0039": ""})
    first["field_0085"] = "- запуск"
    client = FakeClient([_outline(range(1, 16))], [
        first,
        {alias: expected[alias] for alias in ("field_0000", "field_0039")},
    ])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast.generate_fast(state))

    assert result["validation"].ok
    assert len(client.calls) == 3
    assert len(client.calls[1][2]["required"]) == 100
    assert client.calls[2][2]["required"] == ["field_0000", "field_0039"]
    fields = fast._batch_fields(state, result["plan"])
    actual = {
        alias: result["content"][field.slide_index].placeholders[field.key]
        for alias, field in fields.items()
    }
    assert actual == expected


def test_fast_feedback_reaches_outline_batch_and_repair(monkeypatch, service_importer):
    fast, graph, presentation = _load(service_importer)
    state = _state(graph, presentation)
    state.feedback = "Сократи вводную часть, сохрани основные тезисы."
    first = {f"field_{index:04d}": TEXT for index in range(4)}
    first["field_0001"] = ""
    client = FakeClient([_outline()], [first, {"field_0001": TEXT}])
    monkeypatch.setattr(fast, "fast_llm_client", client)
    result = asyncio.run(fast.generate_fast(state))
    assert result["validation"].ok
    assert len(client.calls) == 3
    for _, prompt, _ in client.calls:
        assert state.feedback in prompt
        assert "Это не источник фактов" in prompt
    assert state.script == SOURCE
