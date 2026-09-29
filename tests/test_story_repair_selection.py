"""Правка заметок не должна подменять восстановление видимого содержания."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services/content-service"
SOURCE = "Команда развивает платформу анализа данных."
SECOND = "Каталог помогает читателям выбирать книги."


class Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.schemas = []

    async def generate_json(self, prompt, model):
        self.schemas.append(model.__name__)
        return model.model_validate(next(self.responses))


def _slide(identifier, text, source_id):
    return {"id": identifier, "title": "Обзор", "paragraphs": [text],
            "source_ids": [source_id]}


def test_missing_visible_topic_repairs_slide_and_preserves_valid_slides(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    good = _slide("slide-1", SOURCE, "source-1")
    missing = _slide("slide-2", "Введение", "source-2") | {"notes": SECOND}
    initial = {"title": "Обзор", "slides": [good, missing]}
    repaired = _slide("slide-2", SECOND, "source-2")
    client = Client([initial, {"title": "Обзор", "slides": [repaired]}])
    request = module.DesignRequest(script=SOURCE + "\n\n" + SECOND, slide_count=2)

    result = asyncio.run(module.generate(request, client))

    assert client.schemas == ["ContentPlan", "ContentPlan"]
    assert result.slides[0].model_dump() == module.ContentPlan.model_validate(initial).slides[0].model_dump()
    assert result.slides[1].paragraphs == [SECOND]
    assert module.validate_story(result, request, module.source_excerpts(request.script)) == []


def test_missing_explanations_still_use_compact_notes_repair(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    source = (SOURCE + " Проверка документов устраняет ошибки отчётности. "
              "Каталог заявок распределяет задачи между исполнителями.")
    initial = {"title": "Обзор", "slides": [_slide("slide-1", SOURCE, "source-1")]}
    client = Client([initial, {"source_0": source}])
    request = module.DesignRequest(script=source, slide_count=1)

    result = asyncio.run(module.generate(request, client))

    assert client.schemas == ["ContentPlan", "EditorialRepairs"]
    assert result.slides[0].paragraphs == [SOURCE]
    assert result.slides[0].notes == source
    assert module.validate_story(result, request, module.source_excerpts(source)) == []


def test_missing_visible_required_message_cannot_use_notes_repair(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    source = SECOND + " Следующий этап — собрать отзывы и улучшить каталог."
    plan = module.ContentPlan.model_validate({
        "title": "Обзор", "slides": [_slide("slide-1", SECOND, "source-1")],
    })
    payload = {"sources": [{"id": "source-1", "text": source}]}

    assert module._local_repairs(
        ["Содержание раздела source-1 раскрыто не полностью"], payload, plan,
    ) is None


def test_visible_repair_still_rejects_invented_numbers(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    initial = {"title": "Обзор", "slides": [
        _slide("slide-1", "Введение", "source-1") | {"notes": SOURCE},
    ]}
    invented = {"title": "Обзор", "slides": [
        _slide("slide-1", SOURCE + " Выручка выросла на 99%.", "source-1"),
    ]}
    client = Client([initial, invented, invented])

    with pytest.raises(module.StoryValidationError, match="Неподтверждённые числа"):
        asyncio.run(module.generate(module.DesignRequest(script=SOURCE, slide_count=1), client))

    assert client.schemas == ["ContentPlan", "ContentPlan", "ContentPlan"]
