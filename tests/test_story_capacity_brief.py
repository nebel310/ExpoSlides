"""Бюджет основного текста отражает геометрию макета, а не длину примера."""

import json

from pptx.util import Inches

from exposlides.template_layout import composition_brief
from tests.test_template_design import _profile


def test_same_block_count_still_reports_distinct_body_capacities(tmp_path):
    profile = _profile(tmp_path)
    narrow = profile.patterns[0].model_copy(deep=True)
    narrow.source_slide_index = 2
    narrow.slots[1].box.width //= 2
    profile.patterns.append(narrow)
    original = profile.model_dump()

    brief = composition_brief(profile, 4)
    budgets = {item["source_slide_index"]: item for item in brief["body_text_budgets"]}

    assert budgets.keys() == {1, 2}
    assert budgets[1]["paragraph_count"] == budgets[2]["paragraph_count"] == 1
    assert budgets[1]["max_characters"] > budgets[2]["max_characters"] > 0
    assert budgets[1]["max_words"] > budgets[2]["max_words"] > 0
    assert profile.model_dump() == original
    assert "не обязательный объём" in brief["body_text_guidance"]


def test_body_capacity_respects_largest_original_paragraph_font(tmp_path):
    profile = _profile(tmp_path)
    baseline = composition_brief(profile, 1)["body_text_budgets"][0]
    profile.patterns[0].slots[1].paragraph_font_sizes = [20, 32]

    larger_font = composition_brief(profile, 1)["body_text_budgets"][0]

    assert 0 < larger_font["max_characters"] < baseline["max_characters"]
    assert 0 < larger_font["max_words"] < baseline["max_words"]


def test_body_capacity_omits_covers_specialized_and_visual_layouts(tmp_path):
    profile = _profile(tmp_path)
    for index, name in enumerate(("Титульный слайд", "Скриншот продукта", "Диаграмма"), 2):
        pattern = profile.patterns[0].model_copy(deep=True)
        pattern.source_slide_index = index
        pattern.name = name
        if index == 4:
            pattern.visual_shape_ids = {"bar": [99]}
        profile.patterns.append(pattern)

    budgets = composition_brief(profile, 4)["body_text_budgets"]

    assert [item["source_slide_index"] for item in budgets] == [1]


def test_tiny_caption_does_not_set_body_text_budget(tmp_path):
    profile = _profile(tmp_path)
    profile.patterns[0].slots[1].box.height = 45 * 12700

    brief = composition_brief(profile, 1)

    assert "body_text_budgets" not in brief


def test_body_capacity_does_not_leak_or_depend_on_sample_text(tmp_path):
    profile = _profile(tmp_path)
    original = composition_brief(profile, 1)
    profile.patterns[0].slots[1].text = "SECRET SAMPLE 999% " * 100
    profile.patterns[0].name = "SECRET SAMPLE"

    brief = composition_brief(profile, 1)

    assert brief == original
    assert "SECRET SAMPLE" not in json.dumps(brief, ensure_ascii=False)
    assert "999%" not in json.dumps(brief, ensure_ascii=False)


def test_single_small_layout_gets_advisory_budget_without_minimum(tmp_path):
    profile = _profile(tmp_path)
    profile.patterns[0].slots[1].box.width = Inches(3)
    profile.patterns[0].slots[1].box.height = Inches(1.5)

    brief = composition_brief(profile, 1)

    assert 0 < brief["body_text_budgets"][0]["max_words"] < 50
    assert set(brief["body_text_budgets"][0]) == {
        "source_slide_index", "paragraph_count", "max_characters", "max_words",
    }
