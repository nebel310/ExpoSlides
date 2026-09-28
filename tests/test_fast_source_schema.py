from __future__ import annotations

import asyncio
import copy
import importlib
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
SOURCE = "Команда готовит запуск продукта и описывает стратегию развития."


def _load(service_importer):
    return service_importer(CONTENT_SERVICE_ROOT, "app.graph.fast")


def _nodes(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _nodes(item)
    elif isinstance(value, list):
        for item in value:
            yield from _nodes(item)


def _assert_no_native_pattern(schema):
    strings = [node for node in _nodes(schema) if node.get("type") == "string"]
    assert strings
    for node in _nodes(schema):
        assert "pattern" not in node


@pytest.mark.parametrize("term", ["", "GPT4", "B2B", "HTML5", "OAuth2"])
@pytest.mark.parametrize("analysis_retry", [False, True])
def test_no_fast_request_sends_native_string_patterns(
    monkeypatch, service_importer, term, analysis_retry,
):
    fast = _load(service_importer)
    graph = importlib.import_module("app.models.graph_state")
    presentation = importlib.import_module("app.models.presentation")
    state = graph.ContentGraphState(
        script=SOURCE + (f" {term}" if term else ""),
        presentation=presentation.PresentationData(slides=[presentation.SlideData(
            index=1, placeholders=[presentation.PlaceholderData(
                idx=0, placeholder_type="TITLE", max_length=100,
            )],
        )]),
    )
    data = {
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
            "purpose": "Раскрыть стратегию", "key_message": SOURCE,
            "source_block_indices": [1],
        }]},
    }
    calls = []

    class Client:
        async def generate_json(self, prompt, model, strict=True):
            calls.append(model.model_json_schema())
            payload = copy.deepcopy(data)
            if analysis_retry and len(calls) == 1:
                payload["analysis"]["facts"] = ["27%"]
            return model.model_validate(
                payload["plan"] if "slides" in model.model_fields else payload,
            )

        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append(schema)
            if any(node.get("type") == "array" for node in schema["properties"].values()):
                return {alias: [SOURCE, "Запуск продукта", "Продукт"] for alias in schema["required"]}
            return {alias: SOURCE for alias in schema["required"]}

    monkeypatch.setattr(fast, "fast_llm_client", Client())

    async def run():
        result = await fast.generate_fast(state)
        draft = fast.CombinedDraft.model_validate(data)
        fields = fast._batch_fields(state, draft.plan)
        values = {alias: state.script for alias in fields}
        await fast._repair_plan(state, draft, ["Исправить ссылки"])
        await fast._request_repairs(state, draft, fields, fields, values, ["Исправить поле"])
        await fast._request_length_repairs(draft, fields, fields, values)
        await fast._request_length_alternatives(fields, values, source_text=state.script)
        return result

    assert asyncio.run(run())["validation"].ok
    assert len(calls) == 6 + analysis_retry
    for schema in calls:
        _assert_no_native_pattern(schema)
        _assert_no_native_pattern(fast.LLMClient._schema_for_generation(schema))
