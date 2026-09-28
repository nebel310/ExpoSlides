"""Профиль сохраняет стили и отличает текст от элементов оформления шаблона."""

from copy import deepcopy

import pytest

from exposlides.template_profile import profile_from_json


def _text(shape_id, text, box, *, kind=None, style=None):
    return {
        "id": f"slide-1-shape-{shape_id}", "shape_id": shape_id, "type": "text",
        "placeholder_kind": kind,
        "bbox": dict(zip(("left", "top", "width", "height"), box, strict=True)),
        "text": {"paragraphs": [{"runs": [{"text": text, "style": style or {
            "font_name": "Play", "size_pt": 20, "color_hex": "000000",
        }}]}]},
    }


def _data():
    return {
        "schema_version": "2.0.0", "slide_width": 12000000, "slide_height": 7000000,
        "theme": {"fonts": {"major": "Arial", "minor": "Arial"},
                  "colors": {"accent1": "0077FF", "dk1": "000000"}},
        "slides": [{"index": 1, "elements": [
            _text(1, "Заголовок", (1000000, 400000, 10000000, 700000), kind="title"),
            _text(2, "Содержание", (1000000, 2000000, 10000000, 4000000)),
        ]}],
    }


def _profile(tmp_path, data):
    template = tmp_path / "template.pptx"
    template.write_bytes(b"profile-only fixture")
    return profile_from_json(data, template).patterns[0]


def test_partial_run_style_keeps_inherited_font_size_and_explicit_false(tmp_path):
    data = _data()
    element = data["slides"][0]["elements"][1]
    element["default_text_style"] = {
        "font_name": "Play", "size_pt": 24, "color_hex": "FFFFFF", "bold": True,
    }
    element["text"]["paragraphs"][0]["runs"][0]["style"] = {
        "bold": False, "font_name": None, "color_token": "accent1",
    }
    original = deepcopy(data)
    pattern = _profile(tmp_path, data)
    assert pattern.body_style.font == "Play"
    assert pattern.body_style.size == 24
    assert pattern.body_style.color == "0077FF"
    assert pattern.body_style.bold is False
    assert data == original


def test_empty_runs_do_not_override_inherited_placeholder_style(tmp_path):
    data = _data()
    element = data["slides"][0]["elements"][0]
    element["default_text_style"] = {
        "font_name": "Play", "size_pt": 60, "color_hex": "FFFFFF",
    }
    element["text"]["paragraphs"][0]["runs"] = [{
        "text": " ", "style": {"font_name": "Times New Roman", "size_pt": 12},
    }]
    pattern = _profile(tmp_path, data)
    assert pattern.title_style.font == "Play"
    assert pattern.title_style.size == 60


@pytest.mark.parametrize("kind", ["picture", "bitmap", "chart", "table", "media_clip"])
def test_empty_visual_placeholder_is_never_a_text_slot(tmp_path, kind):
    data = _data()
    picture = _text(3, "", (8500000, 2000000, 2500000, 2000000), kind=kind)
    picture["has_text_frame"] = True
    data["slides"][0]["elements"].append(picture)
    pattern = _profile(tmp_path, data)
    assert 3 not in {slot.shape_id for slot in pattern.slots}
    assert 3 in pattern.protected_shape_ids
    assert 3 not in pattern.mutable_shape_ids


def _marker(shape_id, number, left):
    marker = _text(shape_id, str(number), (left, 2000000, 800000, 800000))
    marker.update(type="shape", geometry={"shape_type": "OVAL"},
                  fill={"type": "solid", "color_hex": "0077FF"})
    return marker


def test_numbered_circles_in_groups_are_preserved_without_becoming_content(tmp_path):
    data = _data()
    first, second = _marker(3, 1, 1000000), _marker(4, 2, 5500000)
    first.update(id="slide-1-shape-99-child-0", slide_bbox=first["bbox"])
    data["slides"][0]["elements"].append({"group": {"children": [first, second]}})
    pattern = _profile(tmp_path, data)
    assert {3, 4}.issubset(pattern.protected_shape_ids)
    assert not {3, 4, 99}.intersection(pattern.mutable_shape_ids)
    assert {slot.text for slot in pattern.slots if slot.role == "protected"} == {"1", "2"}
    assert [slot.shape_id for slot in pattern.slots if slot.role == "body"] == [2]


def test_numeric_fact_and_page_number_keep_their_original_roles(tmp_path):
    data = _data()
    data["slides"][0]["elements"].extend([
        _marker(3, 23, 1000000),
        _text(4, "01", (10500000, 6600000, 400000, 200000), kind="slide_number"),
    ])
    pattern = _profile(tmp_path, data)
    roles = {slot.shape_id: slot.role for slot in pattern.slots}
    assert roles[3] == "body"
    assert roles[4] == "page_number"
    assert 3 in pattern.mutable_shape_ids


def test_short_native_caption_is_kept_without_inventing_a_larger_content_area(tmp_path):
    data = _data()
    caption = data["slides"][0]["elements"][1]
    caption["bbox"] = dict(left=1000000, top=5200000, width=3400000, height=530000)
    caption["text"]["paragraphs"][0]["runs"][0]["style"]["size_pt"] = 14
    data["slides"][0]["elements"].append({
        "id": "slide-1-shape-3", "shape_id": 3, "type": "image",
        "bbox": dict(left=6000000, top=0, width=6000000, height=7000000),
    })
    pattern = _profile(tmp_path, data)
    assert pattern.content_box.model_dump() == caption["bbox"]
    assert pattern.body_style.size == 14
    assert 3 in pattern.protected_shape_ids


def test_short_caption_still_rejected_when_it_overlaps_protected_image(tmp_path):
    data = _data()
    caption = data["slides"][0]["elements"][1]
    caption["bbox"] = dict(left=1000000, top=5200000, width=3400000, height=530000)
    data["slides"][0]["elements"].append({
        "id": "slide-1-shape-3", "shape_id": 3, "type": "image",
        "bbox": dict(caption["bbox"]),
    })
    with pytest.raises(ValueError, match="безопасной области"):
        _profile(tmp_path, data)
