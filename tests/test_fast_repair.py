from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
SOURCE = "Команда готовит запуск продукта и описывает стратегию развития."
SHORT_TEXT = "Команда готовит запуск продукта"


def _load(service_importer):
    fast = service_importer(CONTENT_SERVICE_ROOT, "app.graph.fast")
    graph = importlib.import_module("app.models.graph_state")
    presentation = importlib.import_module("app.models.presentation")
    return fast, graph, presentation


def _state(graph, presentation, *, slide_count=15, fact=""):
    message = SHORT_TEXT + (f" {fact}" if fact else "")
    source = SOURCE + (f" Выручка выросла на {fact}." if fact else "")
    state = graph.ContentGraphState(
        script=source,
        presentation=presentation.PresentationData(slides=[
            presentation.SlideData(index=index, placeholders=[
                presentation.PlaceholderData(
                    idx=field,
                    name=f"Поле {field}",
                    placeholder_type="BODY",
                    max_length=40,
                )
                for field in range(7 if index <= 10 else 6)
            ])
            for index in range(1, slide_count + 1)
        ]),
    )
    draft = {
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
        "plan": {"slides": [{
            "template_slide_index": index,
            "title": "Стратегия запуска продукта",
            "content": message,
            "purpose": "Раскрыть стратегию",
            "key_message": message,
            "source_block_indices": [1],
        } for index in range(1, slide_count + 1)]},
    }
    return state, draft


class RepairClient:
    def __init__(self, draft, *, invalid_count=55, corrected=SHORT_TEXT):
        self.draft = draft
        self.invalid_count = invalid_count
        self.corrected = corrected
        self.calls = []
        self.models = []
        self.active = 0
        self.peak_active = 0
        self.initial_values = {}

    async def generate_json(self, prompt, model, strict=True):
        return model.model_validate(self.draft)

    async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
        self.calls.append((prompt, schema))
        self.models.append(model)
        if len(self.calls) == 1:
            self.initial_values = {
                alias: SOURCE if index < self.invalid_count else SHORT_TEXT
                for index, alias in enumerate(schema["required"])
            }
            return self.initial_values.copy()
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        try:
            await asyncio.sleep(0)
            if isinstance(self.corrected, Exception):
                raise self.corrected
            if any(field.get("type") == "array" for field in schema["properties"].values()):
                return {alias: [self.corrected] * 3 for alias in schema["required"]}
            return {alias: self.corrected for alias in schema["required"]}
        finally:
            self.active -= 1


def test_many_overflows_use_small_parallel_repairs_and_preserve_valid_fields(
    monkeypatch, service_importer,
):
    fast, graph, presentation = _load(service_importer)
    state, draft = _state(graph, presentation)
    client = RepairClient(draft)
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast.generate_fast(state))

    assert result["validation"].ok
    assert len(client.calls[0][1]["required"]) == 100
    repair_calls = client.calls[1:]
    assert len(repair_calls) == 4
    assert client.models == [None] + ["GigaChat-2-Pro"] * 4
    assert client.peak_active == 1
    requested_aliases = [alias for _, schema in repair_calls for alias in schema["required"]]
    assert len(requested_aliases) == len(set(requested_aliases)) == 55
    assert set(requested_aliases) == {f"field_{index:04d}" for index in range(55)}
    fields = fast._batch_fields(state, result["plan"])
    aliases_by_key = {(field.slide_index, field.key): alias for alias, field in fields.items()}
    for prompt, schema in repair_calls:
        assert 1 <= len(schema["required"]) <= 16
        assert "<SOURCE_SCRIPT>" not in prompt
        assert "раскрывай тезис деталями" not in prompt
        assert "Пользовательская разметка:" not in prompt
        assert schema["additionalProperties"] is False
        slide_contexts = json.loads(prompt.split("<SLIDE_CONTEXT>")[1].split("</SLIDE_CONTEXT>")[0])
        for slide in slide_contexts:
            for key in slide["preserved_fields"]:
                assert aliases_by_key[slide["slide_index"], key] not in requested_aliases
    for alias, field in fields.items():
        actual = result["content"][field.slide_index].placeholders[field.key]
        assert actual == SHORT_TEXT
        if alias not in requested_aliases:
            assert actual == client.initial_values[alias]


def test_length_prompt_keeps_fact_and_preserved_context_without_full_brief(service_importer):
    fast, graph, presentation = _load(service_importer)
    state, data = _state(graph, presentation, slide_count=1, fact="18%")
    draft = fast.CombinedDraft.model_validate(data)
    fields = fast._batch_fields(state, draft.plan)
    values = {alias: SHORT_TEXT for alias in fields}
    values["field_0000"] = "Выручка выросла на 18%. " + SOURCE
    values["field_0001"] = "Стратегия развития продукта"

    prompt = fast._length_repair_prompt(
        draft, {"field_0000": fields["field_0000"]}, fields, values,
    )

    assert "18%" in prompt
    assert values["field_0000"] in prompt
    assert values["field_0001"] in prompt
    assert "field_0000" in prompt
    assert "40" in prompt
    assert "<SOURCE_SCRIPT>" not in prompt
    assert "Анализ:" not in prompt


@pytest.mark.parametrize("length_only", [False, True])
def test_repair_prompt_keeps_editable_text_flat_and_separates_metadata(
    service_importer, length_only,
):
    fast, graph, presentation = _load(service_importer)
    state, data = _state(graph, presentation, slide_count=1, fact="18%")
    draft = fast.CombinedDraft.model_validate(data)
    fields = fast._batch_fields(state, draft.plan)
    values = {alias: SHORT_TEXT for alias in fields}
    values["field_0000"] = SOURCE + " Выручка выросла на 18%."
    requested = {"field_0000": fields["field_0000"]}
    if length_only:
        prompt = fast._length_repair_prompt(draft, requested, fields, values)
    else:
        prompt = fast._content_repair_prompt(
            state, draft, requested, fields, values,
            ["Слайд 1, поле 0: текст длиннее максимума"],
        )

    def block(name):
        return json.loads(prompt.split(f"<{name}>")[1].split(f"</{name}>")[0])

    assert block("REJECTED_RESPONSE") == {"field_0000": values["field_0000"]}
    assert all(isinstance(value, str) for value in block("REJECTED_RESPONSE").values())
    assert block("CHARACTER_LIMITS") == {"field_0000": 40}
    assert block("TARGET_LENGTHS") == {"field_0000": 24}
    assert '"field_XXXX":"Краткая подпись"' in prompt
    assert "current_text" not in prompt
    assert "max_chars" not in prompt
    assert "готовый текст" in prompt
    assert "не являются" in prompt
    assert "18%" in prompt
    if not length_only:
        assert prompt.count(f"<SOURCE_SCRIPT>\n{state.script}\n</SOURCE_SCRIPT>") == 1


def test_length_repair_does_not_accept_still_overlong_text(monkeypatch, service_importer):
    fast, graph, presentation = _load(service_importer)
    state, draft = _state(graph, presentation, slide_count=1)
    client = RepairClient(draft, invalid_count=1, corrected=SOURCE)
    monkeypatch.setattr(fast, "fast_llm_client", client)

    with pytest.raises(fast.ContentValidationError, match="нет короткого текста"):
        asyncio.run(fast.generate_fast(state))

    assert len(client.calls) == 4


def test_length_repair_still_rejects_missing_fact(monkeypatch, service_importer):
    fast, graph, presentation = _load(service_importer)
    state, draft = _state(graph, presentation, slide_count=1, fact="18%")

    class FactClient(RepairClient):
        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            response = await super().generate_json_object(prompt, schema, strict, model=model)
            if len(self.calls) == 1:
                response["field_0000"] += " Выручка выросла на 18%."
            return response

    client = FactClient(draft, invalid_count=1)
    monkeypatch.setattr(fast, "fast_llm_client", client)

    with pytest.raises(fast.ContentValidationError, match="18%"):
        asyncio.run(fast.generate_fast(state))

    assert len(client.calls) == 3
    assert "<SOURCE_SCRIPT>" not in client.calls[-1][0]


def test_length_repair_transport_error_is_typed_and_does_not_retry_forever(
    monkeypatch, service_importer,
):
    fast, graph, presentation = _load(service_importer)
    state, draft = _state(graph, presentation)
    client = RepairClient(draft, corrected=fast.LLMGenerationError("service unavailable"))
    monkeypatch.setattr(fast, "fast_llm_client", client)

    with pytest.raises(fast.LLMGenerationError, match="service unavailable"):
        asyncio.run(fast.generate_fast(state))

    assert len(client.calls) <= 5
    assert client.active == 0


def test_length_repair_cannot_overwrite_a_valid_field(monkeypatch, service_importer):
    fast, graph, presentation = _load(service_importer)
    state, draft = _state(graph, presentation, slide_count=1)

    class UnexpectedAliasClient(RepairClient):
        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            response = await super().generate_json_object(prompt, schema, strict, model=model)
            if len(self.calls) > 1:
                response["field_0001"] = "Изменение сохранённого поля"
            return response

    client = UnexpectedAliasClient(draft, invalid_count=1)
    monkeypatch.setattr(fast, "fast_llm_client", client)

    with pytest.raises(fast.ContentValidationError, match="неверные поля вариантов"):
        asyncio.run(fast.generate_fast(state))

    assert len(client.calls) == 3


@pytest.mark.parametrize("retain_unsupported_fact", [False, True])
def test_mixed_length_and_fact_errors_use_bounded_grouped_repairs(
    monkeypatch, service_importer, retain_unsupported_fact,
):
    fast, graph, presentation = _load(service_importer)
    state, draft = _state(graph, presentation)

    class MixedErrorsClient(RepairClient):
        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            initial = not self.calls
            response = await super().generate_json_object(prompt, schema, strict, model=model)
            if initial:
                response["field_0080"] = SHORT_TEXT + " 20"
            return response

    corrected = SHORT_TEXT + (" 20" if retain_unsupported_fact else "")
    client = MixedErrorsClient(draft, invalid_count=56, corrected=corrected)
    monkeypatch.setattr(fast, "fast_llm_client", client)

    if retain_unsupported_fact:
        with pytest.raises(fast.ContentValidationError, match="нет короткого текста"):
            asyncio.run(fast.generate_fast(state))
        assert any("не из источника: 20" in prompt for prompt, _ in client.calls[1:5])
    else:
        result = asyncio.run(fast.generate_fast(state))
        assert result["validation"].ok
        assert all(
            text == SHORT_TEXT
            for slide in result["content"].values()
            for text in slide.placeholders.values()
        )

    repair_calls = client.calls[1:5]
    assert len(repair_calls) == 4
    assert client.peak_active == 1
    # Все группы вариантов проверяются; массовый отказ не запускает micro-retry.
    assert len(client.calls) == (9 if retain_unsupported_fact else 5)
    assert client.models == [None] + ["GigaChat-2-Pro"] * (len(client.calls) - 1)
    requested = [alias for _, schema in repair_calls for alias in schema["required"]]
    assert len(requested) == len(set(requested)) == 57
    assert set(requested) == {f"field_{index:04d}" for index in range(56)} | {"field_0080"}
    fields = fast._batch_fields(state, fast.CombinedDraft.model_validate(draft).plan)
    aliases_by_key = {(field.slide_index, field.key): alias for alias, field in fields.items()}
    for prompt, schema in repair_calls:
        assert 1 <= len(schema["required"]) <= 16
        assert prompt.count(f"<SOURCE_SCRIPT>\n{state.script}\n</SOURCE_SCRIPT>") == 1
        assert "раскрывай тезис деталями" not in prompt
        assert "Анализ:" not in prompt
        assert "Пользовательская разметка:" not in prompt
        contexts = json.loads(prompt.split("<SLIDE_CONTEXT>")[1].split("</SLIDE_CONTEXT>")[0])
        for slide in contexts:
            for key in slide["preserved_fields"]:
                assert aliases_by_key[slide["slide_index"], key] not in requested
