from pathlib import Path

import pytest
from app.builder import (
    _contains_blank_lines,
    _slide_placeholders_by_key,
    _template_placeholder_keys,
    _validate_content_response,
    _validate_placeholder_mappings,
    _validate_requested_indices,
    _validate_template_data,
)
from app.errors import BuilderInputError
from app.models.content import GeneratedContent, SlideContent
from app.models.presentation import Presentation as PresentationModel
from pptx import Presentation
from tests.helpers import build_template_dict, make_pptx


def _make_slide(tmp_path: Path):
    """Возвращает (pptx_path, parsed PresentationModel, slides_by_index)"""
    pptx_path = tmp_path / "t.pptx"
    make_pptx(pptx_path)
    template_dict = build_template_dict(pptx_path)
    template_data = PresentationModel.model_validate(template_dict)
    prs = Presentation(str(pptx_path))
    slides_by_index = {i: s for i, s in enumerate(prs.slides, start=1)}
    return pptx_path, template_data, prs, slides_by_index


def test_contains_blank_lines_positive():
    """Пустая строка внутри текста детектится"""
    assert _contains_blank_lines("a\n\nb") is True
    assert _contains_blank_lines("a\r\n\r\nb") is True


def test_contains_blank_lines_negative():
    """Одна строка или строки без пропусков — ok"""
    assert _contains_blank_lines("single line") is False
    assert _contains_blank_lines("a\nb") is False


def test_validate_content_response_error():
    """error в ответе content-service отклоняется"""
    with pytest.raises(BuilderInputError, match="ошибку"):
        _validate_content_response(GeneratedContent(error="boom"))


def test_validate_content_response_empty():
    """Пустой content отклоняется"""
    with pytest.raises(BuilderInputError, match="ни одного слайда"):
        _validate_content_response(GeneratedContent())


def test_validate_content_response_validation_failed():
    """validation_report.ok=False отклоняется"""
    content = GeneratedContent(
        content={1: SlideContent(placeholders={"0": "a"})},
        validation_report={"ok": False, "issues": ["x"]},
    )
    with pytest.raises(BuilderInputError, match="валидацию"):
        _validate_content_response(content)


def test_validate_content_response_ok():
    """Корректный ответ проходит"""
    content = GeneratedContent(
        content={1: SlideContent(placeholders={"0": "a"})},
        validation_report={"ok": True},
    )
    _validate_content_response(content)


def test_template_placeholder_keys_unique():
    """Одинаковые placeholder-ключи в слайде отклоняются"""
    from app.models.presentation import BBox, Slide, SlideElement
    element = SlideElement(
        id="a", type="text", bbox=BBox(left=0, top=0, width=1, height=1),
        placeholder_type="TITLE", placeholder_idx=0,
    )
    duplicate = element.model_copy(update={"id": "b"})
    slide = Slide(index=1, elements=[element, duplicate])
    with pytest.raises(BuilderInputError, match="повторяющиеся"):
        _template_placeholder_keys(slide)


def test_validate_template_data_size_mismatch(tmp_path):
    """Несовпадение размеров слайда отклоняется"""
    _, template_data, prs, slides_by_index = _make_slide(tmp_path)
    template_data = template_data.model_copy(update={"slide_width": 1})
    with pytest.raises(BuilderInputError, match="Размер"):
        _validate_template_data(prs, template_data, slides_by_index)


def test_validate_template_data_missing_slide(tmp_path):
    """Отсутствующий слайд в PPTX отклоняется"""
    _, template_data, prs, slides_by_index = _make_slide(tmp_path)
    broken = template_data.model_copy(update={"slides": template_data.slides + [
        template_data.slides[0].model_copy(update={"index": 99})
    ]})
    with pytest.raises(BuilderInputError, match="Состав слайдов"):
        _validate_template_data(prs, broken, slides_by_index)


def test_validate_template_data_layout_mismatch(tmp_path):
    """Несовпадение layout отклоняется"""
    _, template_data, prs, slides_by_index = _make_slide(tmp_path)
    slide = template_data.slides[0].model_copy(update={"layout_name": "WrongLayout"})
    broken = template_data.model_copy(update={"slides": [slide]})
    with pytest.raises(BuilderInputError, match="layout"):
        _validate_template_data(prs, broken, slides_by_index)


def test_validate_template_data_ok(tmp_path):
    """Согласованный шаблон проходит"""
    _, template_data, prs, slides_by_index = _make_slide(tmp_path)
    _validate_template_data(prs, template_data, slides_by_index)


def test_validate_requested_indices_duplicates():
    """Повторные индексы отклоняются"""
    with pytest.raises(BuilderInputError, match="Повторное"):
        _validate_requested_indices([1, 1], {1: object()})


def test_validate_requested_indices_unknown():
    """Неизвестный индекс отклоняется"""
    with pytest.raises(BuilderInputError, match="нет слайдов"):
        _validate_requested_indices([1, 5], {1: object()})


def test_validate_requested_indices_ok():
    """Существующие индексы проходят"""
    _validate_requested_indices([1, 2], {1: object(), 2: object()})


def test_validate_placeholder_mappings_empty(tmp_path):
    """Пустой набор placeholders отклоняется"""
    _, _, prs, slides_by_index = _make_slide(tmp_path)
    content = GeneratedContent(content={1: SlideContent(placeholders={})})
    with pytest.raises(BuilderInputError, match="пустой набор"):
        _validate_placeholder_mappings([1], slides_by_index, content)


def test_validate_placeholder_mappings_empty_value(tmp_path):
    """Пустое значение отклоняется"""
    _, _, prs, slides_by_index = _make_slide(tmp_path)
    content = GeneratedContent(content={1: SlideContent(placeholders={"0": " "})})
    with pytest.raises(BuilderInputError, match="без текста"):
        _validate_placeholder_mappings([1], slides_by_index, content)


def test_validate_placeholder_mappings_missing_key(tmp_path):
    """Пропущенный ключ отклоняется"""
    _, _, prs, slides_by_index = _make_slide(tmp_path)
    content = GeneratedContent(content={1: SlideContent(placeholders={"0": "x"})})
    with pytest.raises(BuilderInputError, match="отсутствуют"):
        _validate_placeholder_mappings([1], slides_by_index, content)


def test_validate_placeholder_mappings_unknown_key(tmp_path):
    """Лишний ключ отклоняется"""
    _, _, prs, slides_by_index = _make_slide(tmp_path)
    content = GeneratedContent(content={1: SlideContent(placeholders={
        "0": "a", "1": "b", "999": "c",
    })})
    with pytest.raises(BuilderInputError, match="неизвестные ключи"):
        _validate_placeholder_mappings([1], slides_by_index, content)


def test_validate_placeholder_mappings_ok(tmp_path):
    """Согласованный контент проходит"""
    _, _, prs, slides_by_index = _make_slide(tmp_path)
    content = GeneratedContent(content={1: SlideContent(placeholders={"0": "a", "1": "b"})})
    _validate_placeholder_mappings([1], slides_by_index, content)


def test_slide_placeholders_by_key_unique(tmp_path):
    """Ключи в реальном слайде уникальны"""
    _, _, prs, slides_by_index = _make_slide(tmp_path)
    placeholders = _slide_placeholders_by_key(slides_by_index[1])
    assert set(placeholders) == {"0", "1"}