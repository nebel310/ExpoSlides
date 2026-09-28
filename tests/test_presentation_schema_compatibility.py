from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

CONTENT_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


@pytest.fixture
def parser(service_importer):
    return service_importer(CONTENT_ROOT, "app.utils.presentation_parser").PresentationParser


def presentation_v2(kind: str = "content") -> dict:
    return {
        "schema_version": "2.0.0",
        "slide_width": 9144000,
        "slide_height": 6858000,
        "tokens": {"theme": {"fonts": {"major": "Arial"}, "colors": {"accent1": "123456"}}},
        "layouts": [{
            "name": "Макет", "index": 1,
            "placeholders": [{"kind": kind, "idx": 0, "name": "Текст"}],
        }],
        "slides": [{"index": 1, "layout_type": "bullets", "elements": [{
            "type": "text", "placeholder_kind": kind, "placeholder_idx": 0,
            "placeholder_name": "Текст",
            "bbox": {"left": 0, "top": 0, "width": 4572000, "height": 1524000},
            "text": {"paragraphs": [
                {"runs": [
                    {"text": "Запуск ", "style": {"size_pt": 20}},
                    {"text": "продукта", "style": {"size_pt": 20}},
                ]},
                {"runs": [{"text": "Команда готова", "style": {"size_pt": 20}}]},
            ]},
        }, {"type": "shape", "text": {"paragraphs": [{"runs": [{"text": "Декор"}]}]}}]}],
    }


def test_v2_preserves_text_slots_capacity_theme_and_does_not_mutate_input(parser):
    payload = presentation_v2()
    original = deepcopy(payload)
    result = parser.parse(payload)

    assert payload == original
    assert len(result.slides[0].placeholders) == 1
    placeholder = result.slides[0].placeholders[0]
    assert placeholder.idx == 0
    assert placeholder.placeholder_type == "OBJECT"
    assert placeholder.text == "Запуск продукта\nКоманда готова"
    assert placeholder.max_length == 115
    assert result.layouts[0].placeholders[0].placeholder_type == "OBJECT"
    assert result.theme == payload["tokens"]["theme"]


@pytest.mark.parametrize("version", [None, "1.0.0"])
def test_v1_and_v2_yield_equivalent_generation_contract(parser, version):
    payload = presentation_v2()
    expected = parser.parse(payload)
    legacy = deepcopy(payload)
    legacy["schema_version"] = version
    legacy["theme"] = legacy.pop("tokens")["theme"]
    legacy["layouts"][0]["placeholders"][0].pop("kind")
    legacy["layouts"][0]["placeholders"][0]["placeholder_type"] = "OBJECT"
    element = legacy["slides"][0]["elements"][0]
    element.pop("placeholder_kind")
    element["placeholder_type"] = "OBJECT"
    element["text"]["full_text"] = "Запуск продукта\nКоманда готова"

    assert parser.parse(legacy) == expected


@pytest.mark.parametrize(("kind", "expected"), [
    ("title", "TITLE"), ("section_header", "TITLE"), ("subtitle", "SUBTITLE"),
    ("body", "BODY"), ("content", "OBJECT"), ("picture", "PICTURE"), ("table", "TABLE"),
    ("chart", "CHART"), ("date", "DATE"), ("footer", "FOOTER"),
    ("slide_number", "SLIDE_NUMBER"), ("other", "OTHER"),
])
def test_all_v2_placeholder_kinds_have_explicit_generation_types(parser, kind, expected):
    result = parser.parse(presentation_v2(kind))
    assert result.slides[0].placeholders[0].placeholder_type == expected
    assert result.layouts[0].placeholders[0].placeholder_type == expected


def test_v2_empty_placeholder_is_retained(parser):
    payload = presentation_v2()
    payload["slides"][0]["elements"][0].pop("text")
    result = parser.parse(payload)
    assert len(result.slides[0].placeholders) == 1
    assert result.slides[0].placeholders[0].text == ""


@pytest.mark.parametrize("version", ["3.0.0", "2.1.0", 2, ""])
def test_unknown_schema_version_is_rejected_before_generation(parser, version):
    with pytest.raises(ValueError, match="Неподдерживаемая версия Presentation JSON"):
        parser.parse({"schema_version": version})


@pytest.mark.parametrize("kind", ["future_slot", [], {}, 42])
def test_unknown_v2_kind_is_rejected_instead_of_losing_a_slot(parser, kind):
    with pytest.raises(ValueError, match="Неизвестный вид placeholder"):
        parser.parse(presentation_v2(kind))


def test_legacy_explicit_text_keeps_line_breaks_and_wins_over_runs(parser):
    payload = presentation_v2()
    element = payload["slides"][0]["elements"][0]
    element["text"]["full_text"] = "Первый\n\nПоследний"
    assert parser.parse(payload).slides[0].placeholders[0].text == "Первый\n\nПоследний"
