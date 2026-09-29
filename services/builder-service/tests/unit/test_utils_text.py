from pathlib import Path

from app.utils.text import get_text_placeholder_key, replace_placeholder_text
from pptx import Presentation


def _make_pptx(tmp_path: Path) -> Path:
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    for shape in slide.placeholders:
        if shape.placeholder_format.idx == 0:
            shape.text = "Original title"
        elif shape.placeholder_format.idx == 1:
            shape.text = "Original body"
    path = tmp_path / "sample.pptx"
    prs.save(str(path))
    return path


def test_get_text_placeholder_key_returns_idx(tmp_path):
    """Ключом становится строковый idx"""
    path = _make_pptx(tmp_path)
    prs = Presentation(str(path))
    keys = {get_text_placeholder_key(shape) for shape in prs.slides[0].shapes}
    keys.discard(None)
    assert "0" in keys
    assert "1" in keys


def test_get_text_placeholder_key_returns_none_for_non_text(tmp_path):
    """Не текстовый shape возвращает None"""
    path = _make_pptx(tmp_path)
    prs = Presentation(str(path))
    slide = prs.slides[0]
    box = slide.shapes.add_textbox(0, 0, 100, 100)
    assert get_text_placeholder_key(box) is None


def test_replace_placeholder_text_success(tmp_path):
    """Заменяет текст по ключу"""
    path = _make_pptx(tmp_path)
    prs = Presentation(str(path))
    slide = prs.slides[0]
    assert replace_placeholder_text(slide, "0", "New title")
    assert slide.shapes.title.text == "New title"


def test_replace_placeholder_text_missing(tmp_path):
    """Возвращает False, если placeholder отсутствует"""
    path = _make_pptx(tmp_path)
    prs = Presentation(str(path))
    slide = prs.slides[0]
    assert replace_placeholder_text(slide, "missing", "X") is False


def test_replace_placeholder_text_multiline(tmp_path):
    """Многострочный текст превращается в отдельные параграфы"""
    path = _make_pptx(tmp_path)
    prs = Presentation(str(path))
    slide = prs.slides[0]
    replace_placeholder_text(slide, "1", "Line 1\nLine 2\nLine 3")
    body = [s for s in slide.shapes if s.is_placeholder and s.placeholder_format.idx == 1][0]
    assert len(body.text_frame.paragraphs) == 3
    assert body.text_frame.paragraphs[0].text == "Line 1"
    assert body.text_frame.paragraphs[2].text == "Line 3"


def test_replace_placeholder_text_preserves_run_properties(tmp_path):
    """Стиль первого run не теряется"""
    from pptx.util import Pt
    path = _make_pptx(tmp_path)
    prs = Presentation(str(path))
    slide = prs.slides[0]
    title = slide.shapes.title
    title.text_frame.paragraphs[0].runs[0].font.size = Pt(42)
    title.text_frame.paragraphs[0].runs[0].font.bold = True

    replace_placeholder_text(slide, "0", "Changed")
    new_run = title.text_frame.paragraphs[0].runs[0]
    assert new_run.font.size == Pt(42)
    assert new_run.font.bold is True
    assert new_run.text == "Changed"