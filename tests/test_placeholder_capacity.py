from __future__ import annotations

from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTENT_SERVICE_ROOT = REPOSITORY_ROOT / "services" / "content-service"


@pytest.fixture
def parser(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.utils.presentation_parser")
    return module.PresentationParser


def text_element(
    *,
    width_pt: float = 360,
    height_pt: float = 120,
    font_size: float | None = 20,
    text: str = "Пример",
    placeholder_type: str = "BODY",
) -> dict:
    return {
        "type": "text",
        "placeholder_idx": 0,
        "placeholder_name": "Текст",
        "placeholder_type": placeholder_type,
        "bbox": {
            "left": 0,
            "top": 0,
            "width": round(width_pt * 12700),
            "height": round(height_pt * 12700),
        },
        "text": {
            "full_text": text,
            "paragraphs": [{"runs": [{"text": text, "style": {"size_pt": font_size}}]}],
        },
    }


def test_geometry_expands_short_title_sample(parser):
    element = text_element(
        width_pt=720, height_pt=72, font_size=28, text="Введение", placeholder_type="TITLE"
    )

    assert parser._estimate_max_length(element) == 66


def test_capacity_uses_emu_geometry_and_conservative_text_metrics(parser):
    # 324 pt usable width: 23 characters at 20 pt; 114 pt height: five lines.
    assert parser._estimate_max_length(text_element()) == 115


def test_capacity_increases_with_available_space(parser):
    narrow = parser._estimate_max_length(text_element(width_pt=180))
    wide = parser._estimate_max_length(text_element(width_pt=360))
    tall = parser._estimate_max_length(text_element(width_pt=360, height_pt=240))

    assert narrow < wide < tall


def test_larger_font_reduces_capacity(parser):
    small_font = parser._estimate_max_length(text_element(font_size=16))
    large_font = parser._estimate_max_length(text_element(font_size=32))

    assert large_font < small_font


def test_mixed_fonts_use_largest_resolved_size(parser):
    element = text_element(font_size=10)
    element["text"]["paragraphs"][0]["runs"].append(
        {"text": "Крупный текст", "style": {"size_pt": 20}}
    )

    assert parser._estimate_max_length(element) == 115


@pytest.mark.parametrize(
    ("placeholder_type", "expected"),
    [
        ("TITLE", 100),
        ("CENTER_TITLE", 100),
        ("VERTICAL_TITLE", 100),
        ("FOOTER", 80),
        ("HEADER", 80),
        ("DATE", 80),
        ("SLIDE_NUMBER", 80),
        ("SUBTITLE", 300),
        ("BODY", 1000),
        ("OBJECT", 1000),
    ],
)
def test_roomy_shapes_keep_semantic_limits(parser, placeholder_type, expected):
    element = text_element(
        width_pt=720, height_pt=540, font_size=10, placeholder_type=placeholder_type
    )

    assert parser._estimate_max_length(element) == expected


def test_normal_shape_does_not_reject_existing_sample_length(parser):
    element = text_element(text="Текст " * 25)

    assert parser._estimate_max_length(element) == len(element["text"]["full_text"])


def test_semantic_limit_does_not_shorten_existing_title(parser):
    element = text_element(
        width_pt=720, height_pt=200, font_size=20,
        text="Длинный заголовок " * 7, placeholder_type="TITLE",
    )

    assert parser._estimate_max_length(element) == len(element["text"]["full_text"])


@pytest.mark.parametrize(
    ("width_pt", "height_pt"), [(1, 120), (360, 1), (0.1, 0.1)]
)
def test_tiny_shapes_do_not_inherit_unusable_sample_capacity(parser, width_pt, height_pt):
    element = text_element(width_pt=width_pt, height_pt=height_pt, text="Текст " * 25)

    assert 1 <= parser._estimate_max_length(element) <= 2


def test_single_line_box_allows_typical_font_height(parser):
    element = text_element(width_pt=360, height_pt=24, font_size=20)

    assert parser._estimate_max_length(element) == 23


@pytest.mark.parametrize(
    ("width_pt", "height_pt", "font_size", "placeholder_type", "fitting_text", "expected"),
    [
        (402.9, 104.4, 44, "TITLE", "Структура презентации", 22),
        (398.1, 104.4, 44, "TITLE", "Содержание презентации", 22),
        (828, 104.4, 44, "TITLE", "От исходного материала к готовой презентации", 48),
        (147.8, 39.9, 18, "BODY", "Подготовка материала", 20),
        (147.8, 39.9, 18, "BODY", "Подготовка данных", 20),
    ],
)
def test_two_line_boxes_keep_capacity_confirmed_by_rendered_template(
    parser, width_pt, height_pt, font_size, placeholder_type, fitting_text, expected
):
    # Эти размеры проверены офлайн рендером: текст помещается в две строки
    # без изменения шрифта и без пересечения соседних блоков.
    element = text_element(
        width_pt=width_pt,
        height_pt=height_pt,
        font_size=font_size,
        placeholder_type=placeholder_type,
        text="Пример",
    )

    capacity = parser._estimate_max_length(element)

    assert capacity == expected
    assert len(fitting_text) <= capacity


def test_extra_line_requires_space_for_its_baseline(parser):
    below_boundary = text_element(width_pt=147.8, height_pt=39, font_size=18)
    above_boundary = text_element(width_pt=147.8, height_pt=39.9, font_size=18)

    assert parser._estimate_max_length(below_boundary) == 10
    assert parser._estimate_max_length(above_boundary) == 20


@pytest.mark.parametrize("key", ["width", "height"])
@pytest.mark.parametrize("invalid", [None, 0, -1, True, "360", float("nan"), float("inf")])
def test_unknown_geometry_preserves_legacy_fallback(parser, key, invalid):
    element = text_element(text="Пример текста")
    element["bbox"][key] = invalid

    assert parser._estimate_max_length(element) == int(len("Пример текста") * 1.3)


@pytest.mark.parametrize("invalid", [None, 0, -1, True, "20", float("nan"), float("inf")])
def test_unknown_font_preserves_legacy_fallback(parser, invalid):
    element = text_element(text="Пример текста")
    element["text"]["paragraphs"][0]["runs"][0]["style"]["size_pt"] = invalid

    assert parser._estimate_max_length(element) == int(len("Пример текста") * 1.3)


def test_legacy_json_without_geometry_or_runs_keeps_previous_limit(parser):
    element = {"text": {"full_text": "Пример текста"}, "placeholder_type": "BODY"}

    assert parser._estimate_max_length(element) == int(len("Пример текста") * 1.3)


def test_empty_sample_uses_known_geometry(parser):
    assert parser._estimate_max_length(text_element(text="")) == 115


def test_empty_sample_and_unknown_font_keep_unbounded_fallback(parser):
    assert parser._estimate_max_length(text_element(text="", font_size=None)) is None


def test_parse_exposes_capacity_without_changing_placeholder_contract(parser):
    element = text_element(text="Коротко")
    presentation = parser.parse({"slides": [{"index": 1, "elements": [element]}]})

    placeholder = presentation.slides[0].placeholders[0]
    assert placeholder.model_dump() == {
        "idx": 0,
        "name": "Текст",
        "placeholder_type": "BODY",
        "text": "Коротко",
        "max_length": 115,
    }


def peer_element(
    *, element_type: str, left_pt: float, top_pt: float, width_pt: float,
    height_pt: float, z_order: int | None = 3,
) -> dict:
    return {
        "type": element_type,
        "z_order": z_order,
        "bbox": {
            "left": round(left_pt * 12700),
            "top": round(top_pt * 12700),
            "width": round(width_pt * 12700),
            "height": round(height_pt * 12700),
        },
    }


def overlapping_title() -> dict:
    element = text_element(
        width_pt=773.5, height_pt=104.4, font_size=44,
        text="Сводка", placeholder_type="TITLE",
    )
    element["bbox"].update(left=round(40.7 * 12700), top=round(196.7 * 12700))
    element["z_order"] = 2
    return element


def test_title_capacity_stops_before_overlapping_body_and_photo(parser):
    title = overlapping_title()
    body = peer_element(
        element_type="text", left_pt=40.7, top_pt=256.2, width_pt=407.1, height_pt=184.3,
    )
    photo = peer_element(
        element_type="other", left_pt=590, top_pt=41.7, width_pt=334.6, height_pt=372.5,
        z_order=4,
    )
    decoration = peer_element(
        element_type="image", left_pt=512.1, top_pt=238.5, width_pt=123.7, height_pt=141.5,
        z_order=5,
    )
    # Рамка 773.5 × 104.4 pt физически свободна лишь на 549.3 × 59.5 pt:
    # на исходном шаблоне длинный заголовок скрывался под фото и основным текстом.
    presentation = parser.parse({
        "slides": [{"index": 1, "elements": [title, body, photo, decoration]}]
    })

    assert parser._estimate_max_length(title) == 44
    assert presentation.slides[0].placeholders[0].max_length == 16


@pytest.mark.parametrize("element_type", ["image", "other"])
def test_front_photo_crops_title_width(parser, element_type):
    title = overlapping_title()
    photo = peer_element(
        element_type=element_type, left_pt=590, top_pt=41.7, width_pt=334.6, height_pt=372.5,
    )

    assert parser._estimate_max_length(title, [title, photo]) == 32


def test_text_below_title_crops_height(parser):
    title = overlapping_title()
    body = peer_element(
        element_type="text", left_pt=40.7, top_pt=256.2, width_pt=407.1, height_pt=184.3,
    )

    assert parser._estimate_max_length(title, [title, body]) == 22


def test_table_below_title_reserves_space_without_changing_cells(parser):
    title = text_element(
        width_pt=857.5, height_pt=111.7, font_size=44,
        text="Области роста", placeholder_type="TITLE",
    )
    title["bbox"].update(left=round(45.8 * 12700), top=round(56.8 * 12700))
    title["z_order"] = 2
    table = peer_element(
        element_type="table", left_pt=45.8, top_pt=127.1, width_pt=857.5, height_pt=200.1,
    )
    table["table"] = {"rows": 1, "cols": 1, "cells": [["Исходное значение"]]}

    assert parser._estimate_max_length(title) == 50
    assert parser._estimate_max_length(title, [title, table]) == 25
    assert table["table"]["cells"] == [["Исходное значение"]]


@pytest.mark.parametrize("element_type", ["text", "image", "other"])
@pytest.mark.parametrize("z_order", [1, 2, None])
def test_title_ignores_peers_behind_it_or_with_unknown_layer(parser, element_type, z_order):
    title = overlapping_title()
    peer = peer_element(
        element_type=element_type, left_pt=590, top_pt=256.2, width_pt=100, height_pt=100,
        z_order=z_order,
    )

    assert parser._estimate_max_length(title, [title, peer]) == 44


@pytest.mark.parametrize("element_type", ["text", "image", "other"])
def test_title_ignores_containing_background(parser, element_type):
    title = overlapping_title()
    background = peer_element(
        element_type=element_type, left_pt=0, top_pt=0, width_pt=960, height_pt=540,
    )

    assert parser._estimate_max_length(title, [title, background]) == 44


def test_title_ignores_photo_with_insignificant_vertical_overlap(parser):
    title = overlapping_title()
    photo = peer_element(
        element_type="image", left_pt=590, top_pt=300, width_pt=300, height_pt=150,
    )

    assert parser._estimate_max_length(title, [title, photo]) == 44


def test_title_ignores_text_to_the_side(parser):
    title = overlapping_title()
    text = peer_element(
        element_type="text", left_pt=820, top_pt=256.2, width_pt=100, height_pt=100,
    )

    assert parser._estimate_max_length(title, [title, text]) == 44


def test_peer_heuristic_only_applies_to_titles(parser):
    body = overlapping_title()
    body["placeholder_type"] = "BODY"
    photo = peer_element(
        element_type="image", left_pt=590, top_pt=41.7, width_pt=334.6, height_pt=372.5,
    )

    assert parser._estimate_max_length(body, [body, photo]) == 44


def test_unknown_title_font_retains_legacy_fallback_with_neighbors(parser):
    title = overlapping_title()
    title["text"]["paragraphs"][0]["runs"][0]["style"]["size_pt"] = None
    photo = peer_element(
        element_type="image", left_pt=590, top_pt=41.7, width_pt=334.6, height_pt=372.5,
    )

    assert parser._estimate_max_length(title, [title, photo]) == int(len("Сводка") * 1.3)


def test_title_geometry_excludes_portrait_edge(parser):
    title = text_element(
        width_pt=307.9, height_pt=314.4, font_size=37,
        text="Короткий заголовок", placeholder_type="TITLE",
    )
    title["bbox"].update(left=round(40.1 * 12700), top=round(157.8 * 12700))
    title["z_order"] = 2
    portrait = peer_element(
        element_type="other", left_pt=333.5, top_pt=157.8, width_pt=92.4, height_pt=106.9,
    )

    width, height = parser._available_title_box(
        title, [title, portrait], title["bbox"]["width"], title["bbox"]["height"], 37
    )

    assert width / 12700 == pytest.approx(293.4)
    assert height / 12700 == pytest.approx(314.4)
