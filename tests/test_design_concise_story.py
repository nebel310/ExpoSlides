from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from exposlides.design_content import source_excerpts, validate_story
from exposlides.design_models import ContentPlan, DesignRequest, StorySlide, VisualRequest
from tests.test_design_generation import Client

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
RICH_SOURCE = (
    "Агент выбирает инструменты для решения задачи. "
    "Оркестратор управляет графом состояний, переходами между узлами и условиями остановки. "
    "Трассировка сохраняет историю выполнения, результаты запросов и ошибки интеграции. "
    "Разработчик проверяет поведение, уточняет инструкции и анализирует журнал событий."
)


def _rich_story(*, sparse: bool) -> ContentPlan:
    return ContentPlan(title="Агенты", slides=[StorySlide(
        id="slide-1", title="Агент выбирает инструменты",
        paragraphs=["Агент выбирает инструменты для решения задачи."] if sparse else [
            "Агент выбирает инструменты для решения задачи.",
            "Оркестратор управляет графом состояний, переходами между узлами и условиями остановки.",
            "Трассировка сохраняет историю выполнения и ошибки интеграции.",
            "Разработчик проверяет поведение и анализирует журнал событий.",
        ],
        notes=RICH_SOURCE, source_ids=["source-1"],
    )])


@pytest.mark.parametrize("number_in_notes_only", [False, True])
def test_concise_story_keeps_explanations_in_notes_but_numbers_visible(
    service_importer, number_in_notes_only,
):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    source = "Команда сократила время обработки на 20%. Проверка данных выполняется автоматически."
    plan = {
        "title": "Автоматизация обработки",
        "slides": [{
            "id": "slide-1",
            "title": "Автоматизация обработки",
            "paragraphs": [
                "Команда сократила время обработки."
                if number_in_notes_only else "Команда сократила время обработки на 20%.",
            ],
            "notes": source,
            "source_ids": ["source-1"],
        }],
    }

    class Client:
        calls = 0

        async def generate_json(self, prompt, model):
            self.calls += 1
            return model.model_validate(plan)

    client = Client()
    request = DesignRequest(script=source, slide_count=1)
    if number_in_notes_only:
        with pytest.raises(module.ContentValidationError):
            asyncio.run(module.generate(request, client))
        assert client.calls <= module.role_config("story")["attempts"]
    else:
        result = asyncio.run(module.generate(request, client))
        assert result.slides[0].paragraphs == plan["slides"][0]["paragraphs"]
        assert result.slides[0].notes == source
        assert client.calls == 1


def test_short_source_does_not_need_padding(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    source = "Команда развивает платформу анализа данных."
    plan = ContentPlan(title="Платформа", slides=[StorySlide(
        id="slide-1", title="Платформа анализа данных", paragraphs=[source],
        source_ids=["source-1"],
    )])
    client = Client([plan.model_dump()])
    result = asyncio.run(module.generate(DesignRequest(script=source, slide_count=1), client))
    assert result == plan
    assert len(client.prompts) == 1


@pytest.mark.parametrize("repairs", [True, False])
def test_rich_source_with_notes_requires_visible_explanations(service_importer, repairs):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    sparse, detailed = _rich_story(sparse=True), _rich_story(sparse=False)
    responses = [sparse.model_dump(), detailed.model_dump()] if repairs else [
        sparse.model_dump()
    ] * module.role_config("story")["attempts"]
    client = Client(responses)
    request = DesignRequest(script=RICH_SOURCE, slide_count=1)
    if repairs:
        result = asyncio.run(module.generate(request, client))
        assert result == detailed
        assert len(client.prompts) == 2
    else:
        with pytest.raises(module.StoryValidationError, match="слишком краткое"):
            asyncio.run(module.generate(request, client))
        assert len(client.prompts) == module.role_config("story")["attempts"]
    assert "только исправленными слайдами" in client.prompts[1]
    assert "слишком краткое в видимом тексте" in client.prompts[1]
    assert '"source_fields"' not in client.prompts[1]


def test_duplicate_titles_and_paragraphs_do_not_fill_source_budget():
    plan = _rich_story(sparse=True)
    slide = plan.slides[0]
    slide.title = slide.paragraphs[0]
    slide.paragraphs *= 4
    plan.slides.append(slide.model_copy(update={"id": "slide-2"}))
    request = DesignRequest(script=RICH_SOURCE, slide_count=2)
    assert any("слишком краткое" in issue for issue in validate_story(
        plan, request, source_excerpts(RICH_SOURCE),
    ))


def test_source_budget_counts_content_across_cover_body_and_visual_labels():
    plan = _rich_story(sparse=False)
    slide = plan.slides[0]
    labels = slide.paragraphs[1:]
    slide.paragraphs = slide.paragraphs[:1]
    slide.visual = VisualRequest(kind="process", labels=labels)
    plan.slides.insert(0, StorySlide(
        id="cover", title="Агенты", paragraphs=["Инструменты и управление"],
        source_ids=["source-1"],
    ))
    request = DesignRequest(script=RICH_SOURCE, slide_count=2)
    assert not validate_story(plan, request, source_excerpts(RICH_SOURCE))


@pytest.mark.parametrize("same_paragraph", [False, True])
def test_neighbor_source_does_not_fill_missing_visible_explanations(same_paragraph):
    neighbor = (
        "Библиотека хранит книги, журналы, каталоги, рукописи и редкие издания. "
        "Посетители читают литературу в зале, заказывают экземпляры в каталоге "
        "и возвращают книги библиотекарю."
    )
    script = RICH_SOURCE + "\n\n" + neighbor
    plan = _rich_story(sparse=True)
    plan.slides[0].source_ids.append("source-2")
    if same_paragraph:
        plan.slides[0].paragraphs[0] += " " + neighbor
    else:
        plan.slides[0].paragraphs.append(neighbor)
    plan.slides[0].notes += "\n" + neighbor
    request = DesignRequest(script=script, slide_count=1)
    assert any("раздела source-1 слишком краткое" in issue for issue in validate_story(
        plan, request, source_excerpts(script),
    ))
