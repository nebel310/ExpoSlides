from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
SOURCE = "Паттерн «Маршрутизатор» распределяет запросы по агентам."


@pytest.mark.parametrize("needs_shortening", [False, True])
def test_list_formatting_preserves_content_and_recovers_overlong_topic(
    monkeypatch, service_importer, needs_shortening,
):
    fast = service_importer(SERVICE_ROOT, "app.graph.fast")
    graph = importlib.import_module("app.models.graph_state")
    presentation = importlib.import_module("app.models.presentation")
    state = graph.ContentGraphState(
        script=SOURCE,
        presentation=presentation.PresentationData(slides=[presentation.SlideData(
            index=7, placeholders=[
                presentation.PlaceholderData(idx=0, placeholder_type="BODY", max_length=100),
                presentation.PlaceholderData(idx=28, placeholder_type="BODY", max_length=30),
            ],
        )]),
    )
    calls = []

    class Client:
        async def generate_json(self, prompt, model, strict=True):
            return model.model_validate({
                "analysis": {
                    "topic": "Архитектурные паттерны", "audience": "", "objective": "",
                    "blocks": [{
                        "index": 1, "heading": "Паттерны", "summary": SOURCE,
                        "key_points": [SOURCE], "facts": [],
                    }], "key_messages": [SOURCE], "facts": [],
                },
                "plan": {"slides": [{
                    "template_slide_index": 7, "title": "Архитектурные паттерны",
                    "content": SOURCE, "purpose": "Раскрыть тему", "key_message": SOURCE,
                    "source_block_indices": [1],
                }]},
            })

        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append((prompt, schema))
            if len(calls) == 1:
                return {
                    "field_0000": "- " + SOURCE,
                    "field_0001": "- Маршрутизатор — распределение запросов по агентам."
                    if needs_shortening else "- Маршрутизатор",
                }
            assert schema["required"] == ["field_0001"]
            if len(calls) == 2:
                assert "Сократи значения" in prompt
                return {
                    "field_0001": "- Паттерн 'Маршрутизатор': автоматическое распределение запросов.",
                }
            if len(calls) == 3:
                assert "Паттерн 'Маршрутизатор'" in prompt
                return {"field_0001": ["Паттерны мульти-агентных архитектур"] * 3}
            assert len(calls) == 4
            return {"field_0001": "Паттерны мульти-агентных архитектур"}

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    result = asyncio.run(fast.generate_fast(state))

    assert result["validation"].ok
    assert result["content"][7].placeholders == {
        "0": SOURCE,
        "28": "Паттерн 'Маршрутизатор'" if needs_shortening else "Маршрутизатор",
    }
    assert len(calls) == (4 if needs_shortening else 1)
