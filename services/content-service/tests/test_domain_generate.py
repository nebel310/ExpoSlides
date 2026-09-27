from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.domain.contract import ContentGenerationRequest
from app.domain.generate import generate_content
from app.errors import ContentValidationError
from app.models.graph_state import GeneratedSlideContent, ValidationReport
from app.models.presentation import PresentationData, SlideData


def _request() -> ContentGenerationRequest:
    """Собрать валидный запрос на генерацию"""
    return ContentGenerationRequest(
        structure={"slides": []},
        script="Пример исходного текста",
        feedback=None,
    )


def _presentation_with_slides(count: int = 1) -> PresentationData:
    """Собрать presentation с заданным числом слайдов"""
    return PresentationData(
        slides=[SlideData(index=i) for i in range(1, count + 1)],
    )


def _state_dict(content_slide_count: int = 1, ok: bool = True, issues=None):
    """Собрать валидный dict для ContentGraphState(**result)"""
    presentation = _presentation_with_slides(content_slide_count)
    content = {
        i: GeneratedSlideContent(placeholders={"0": f"текст {i}"})
        for i in range(1, content_slide_count + 1)
    }
    return {
        "presentation": presentation,
        "script": "Пример исходного текста",
        "content": content,
        "validation": ValidationReport(ok=ok, issues=issues or []),
    }


def _patch_graph(result_dict):
    """Собрать патч build_graph, возвращающий заданный dict"""
    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value=result_dict)
    return patch("app.domain.generate.build_graph", return_value=graph)


@pytest.mark.asyncio
async def test_generate_content_valid():
    """Проверить успешную генерацию контента"""
    with patch(
        "app.domain.generate.PresentationParser.parse",
        return_value=_presentation_with_slides(1),
    ), _patch_graph(_state_dict(content_slide_count=1, ok=True)):
        result = await generate_content(_request())
    assert result.passed is True
    assert result.reason is None
    assert result.validation_report == {"ok": True, "issues": []}
    assert 1 in result.content
    assert result.content[1]["placeholders"] == {"0": "текст 1"}


@pytest.mark.asyncio
async def test_generate_content_multiple_slides():
    """Проверить генерацию с несколькими слайдами"""
    with patch(
        "app.domain.generate.PresentationParser.parse",
        return_value=_presentation_with_slides(3),
    ), _patch_graph(_state_dict(content_slide_count=3, ok=True)):
        result = await generate_content(_request())
    assert len(result.content) == 3
    assert set(result.content.keys()) == {1, 2, 3}


@pytest.mark.asyncio
async def test_generate_content_empty_presentation_raises():
    """Проверить ошибку при пустой презентации"""
    with patch(
        "app.domain.generate.PresentationParser.parse",
        return_value=PresentationData(slides=[]),
    ):
        with pytest.raises(ContentValidationError):
            await generate_content(_request())


@pytest.mark.asyncio
async def test_generate_content_validation_failed_raises():
    """Проверить ошибку при провале валидации графа"""
    with patch(
        "app.domain.generate.PresentationParser.parse",
        return_value=_presentation_with_slides(1),
    ), _patch_graph(
        _state_dict(content_slide_count=1, ok=False, issues=["слайд 1: пусто"])
    ):
        with pytest.raises(ContentValidationError):
            await generate_content(_request())


@pytest.mark.asyncio
async def test_generate_content_empty_content_raises():
    """Проверить ошибку, когда граф не сгенерировал контент"""
    presentation = _presentation_with_slides(1)
    state = {
        "presentation": presentation,
        "script": "текст",
        "content": None,
        "validation": ValidationReport(ok=True, issues=[]),
    }
    with patch(
        "app.domain.generate.PresentationParser.parse",
        return_value=presentation,
    ), _patch_graph(state):
        with pytest.raises(ContentValidationError):
            await generate_content(_request())


@pytest.mark.asyncio
async def test_generate_content_with_feedback_passes_through():
    """Проверить, что feedback принимается и не ломает генерацию"""
    request = ContentGenerationRequest(
        structure={"slides": []},
        script="Пример исходного текста",
        feedback="Нужно добавить цифры по выручке",
    )
    with patch(
        "app.domain.generate.PresentationParser.parse",
        return_value=_presentation_with_slides(1),
    ), _patch_graph(_state_dict(content_slide_count=1, ok=True)):
        result = await generate_content(request)
    assert result.passed is True


@pytest.mark.asyncio
async def test_generate_content_empty_script_rejected():
    """Проверить, что пустой script отклоняется на уровне контракта"""
    with pytest.raises(Exception):
        ContentGenerationRequest(
            structure={"slides": []},
            script="",
            feedback=None,
        )


@pytest.mark.asyncio
async def test_generate_content_wraps_graph_technical_error():
    """Проверить проброс технической ошибки графа"""
    graph = MagicMock()
    graph.ainvoke = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    with patch(
        "app.domain.generate.PresentationParser.parse",
        return_value=_presentation_with_slides(1),
    ), patch("app.domain.generate.build_graph", return_value=graph):
        with pytest.raises(RuntimeError):
            await generate_content(_request())
