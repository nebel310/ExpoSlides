from __future__ import annotations

import asyncio
from pathlib import Path

from pptx import Presentation as PPTXPresentation
from pptx.util import Inches

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PARSING_SERVICE_ROOT = REPOSITORY_ROOT / "services" / "parsing-service"


def _write_test_presentation(path: Path) -> None:
    presentation = PPTXPresentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    text_box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    text_box.text = "Stable parser output"
    presentation.save(path)


def _element_ids(presentation) -> list[str]:
    layout_ids = [element.id for layout in presentation.layouts for element in layout.elements]
    slide_ids = [element.id for slide in presentation.slides for element in slide.elements]
    return layout_ids + slide_ids


def test_element_ids_are_stable_and_unique(tmp_path: Path, service_importer) -> None:
    input_path = tmp_path / "input.pptx"
    _write_test_presentation(input_path)
    parser = service_importer(PARSING_SERVICE_ROOT, "app.parsers.pptx_parser").PPTXParser

    first_result = asyncio.run(parser.parse(input_path))
    second_result = asyncio.run(parser.parse(input_path))
    first_ids = _element_ids(first_result)
    second_ids = _element_ids(second_result)

    assert first_ids == second_ids
    assert len(first_ids) == len(set(first_ids))
    assert all(element_id.startswith(("layout-", "slide-")) for element_id in first_ids)


def test_theme_xml_is_read_from_related_part(tmp_path: Path, service_importer) -> None:
    input_path = tmp_path / "input.pptx"
    _write_test_presentation(input_path)
    parser = service_importer(PARSING_SERVICE_ROOT, "app.parsers.pptx_parser").PPTXParser

    result = asyncio.run(parser.parse(input_path))

    assert result.theme is not None
    assert result.theme.colors
    assert result.theme.fonts
