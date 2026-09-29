"""Длинные пояснения не должны становиться видимым дополнительным абзацем."""

import asyncio
from pathlib import Path

import pytest

from exposlides.design_content import source_excerpts, validate_story
from exposlides.design_layout import story_layout_issues
from exposlides.design_models import ContentPlan, DesignRequest, StorySlide
from exposlides.design_pipeline import DesignPipeline
from tests.test_design_generation import Client
from tests.test_template_design import _profile

SERVICE = Path(__file__).resolve().parents[1] / "services/content-service"
SOURCE = (
    "Агент выбирает инструменты для решения задачи. "
    "Оркестратор управляет графом состояний, переходами между узлами и условиями остановки. "
    "Трассировка сохраняет историю выполнения, результаты запросов и ошибки интеграции. "
    "Разработчик проверяет поведение, уточняет инструкции и анализирует журнал событий."
)


def _story():
    return ContentPlan(title="Агенты", slides=[StorySlide(
        id="slide-1", title="Агент выбирает инструменты",
        paragraphs=[
            "Агент выбирает инструменты для задачи; оркестратор управляет состояниями и переходами. "
            "Трассировка сохраняет историю выполнения и ошибки, разработчик проверяет поведение и журнал."
        ],
        source_ids=["source-1"], notes=SOURCE,
    )])


def test_long_explanations_in_notes_keep_visible_source_coverage():
    request = DesignRequest(script=SOURCE, slide_count=1)
    assert validate_story(_story(), request, source_excerpts(SOURCE)) == []
    request.required_messages = ["Результаты запросов и ошибки интеграции."]
    assert validate_story(_story(), request, source_excerpts(SOURCE))


def test_visible_content_repair_rewrites_slide_without_appending_transcript(service_importer):
    module = service_importer(SERVICE, "app.design_main")
    initial = _story()
    initial.slides[0].paragraphs = ["Агент выбирает инструменты для решения задачи."]
    repaired = _story()
    client = Client([initial.model_dump(), repaired.model_dump()])
    result = asyncio.run(module.generate(DesignRequest(script=SOURCE, slide_count=1), client))
    assert len(client.prompts) == 2
    assert result.slides[0].paragraphs == repaired.slides[0].paragraphs
    assert SOURCE not in result.slides[0].paragraphs
    assert result.slides[0].notes == SOURCE


def test_overflow_retries_only_bad_slide_and_rejects_after_limit(service_importer, tmp_path):
    module = service_importer(SERVICE, "app.design_main")
    profile = _profile(tmp_path)
    profile.patterns[0].slots[1].box.height = 12700 * 95
    good = _story()
    bad = good.model_copy(deep=True)
    bad.slides[0].paragraphs = [SOURCE * 4]
    assert story_layout_issues(profile, bad)
    assert not story_layout_issues(profile, good)
    request = DesignRequest(script=SOURCE, slide_count=1)
    client = Client([bad.model_dump(), good.model_dump()])
    result = asyncio.run(module.generate(request, client, profile=profile))
    assert len(client.prompts) == 2
    assert result.slides[0].paragraphs == good.slides[0].paragraphs
    assert "не помещается" in client.prompts[1]
    client = Client([bad.model_dump()] * 3)
    with pytest.raises(module.StoryValidationError, match="не помещается"):
        asyncio.run(module.generate(request, client, profile=profile))
    assert len(client.prompts) == 3


def test_extractive_build_rejects_overflow_before_images_or_publication(tmp_path, monkeypatch):
    profile = _profile(tmp_path)
    story = _story()
    story.slides[0].paragraphs = [SOURCE * 15]
    pipeline = DesignPipeline(tmp_path / "job")
    monkeypatch.setattr(pipeline, "generate_images", lambda *args: pytest.fail("Image API reached"))
    try:
        with pytest.raises(ValueError, match="не помещается"):
            pipeline.build(tmp_path / "template.pptx", DesignRequest(
                script=SOURCE, slide_count=1, mode="extractive"),
                           profile, story)
    finally:
        pipeline.close()
    assert not (tmp_path / "job" / "variants").exists()
