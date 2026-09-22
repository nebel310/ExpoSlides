from __future__ import annotations

import asyncio
import importlib
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
        presentation=presentation.PresentationData(slides=[presentation.SlideData(
            index=1, placeholders=[
                presentation.PlaceholderData(idx=index, placeholder_type="BODY", max_length=40)
                for index in range(2)
            ] + [presentation.PlaceholderData(idx=2, placeholder_type="BODY", max_length=120)],
        )]),
    )
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
            "purpose": "Раскрыть стратегию", "key_message": SOURCE,
            "source_block_indices": [1],
        }]},
    }
    return fast, state, draft


@pytest.mark.parametrize("final_failure", ["overlong", "wrong_keys", "wrong_type"])
def test_failed_final_repair_reports_only_current_failure(
    monkeypatch, service_importer, final_failure,
):
    fast, state, draft = _load(service_importer)
    calls = []

    class Client:
        async def generate_json(self, prompt, model, strict=True):
            return model.model_validate(draft)

        async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
            calls.append((prompt, schema))
            if len(calls) <= 2:
                old_values = {
                    "field_0000": SOURCE,
                    "field_0001": "- " + SOURCE,
                    "field_0002": SOURCE,
                }
                return {alias: old_values[alias] for alias in schema["required"]}
            if len(calls) == 3:
                assert schema["required"] == ["field_0000", "field_0001"]
                return {"field_0000": ["Запуск"] * 3, "field_0001": [SOURCE] * 3}
            assert len(calls) == 4
            assert schema["required"] == ["field_0001"]
            return {
                "overlong": {"field_0001": SOURCE},
                "wrong_keys": {"unknown": "Запуск"},
                "wrong_type": {"field_0001": ["Запуск"]},
            }[final_failure]

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    monkeypatch.setattr(fast, "_source_label_fallback", lambda *args, **kwargs: None)

    with pytest.raises(fast.ContentValidationError) as raised:
        asyncio.run(fast.generate_fast(state))

    message = str(raised.value)
    assert message.startswith("Контент не прошёл проверку: ")
    assert "поле 0" not in message
    assert "field_0000" not in message
    assert "ручных маркеров" not in message
    assert "maxLength" not in message
    if final_failure == "overlong":
        assert "Слайд 1, поле 1" in message
        assert "нет короткого текста" in message
    else:
        assert "неверные поля или типы" in message
    assert isinstance(raised.value.__cause__, fast.ContentValidationError)
    assert message == "Контент не прошёл проверку: " + str(raised.value.__cause__)
    assert len(calls) == 4
