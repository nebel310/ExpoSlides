"""Выбор выразительных композиций из всего каталога без потери вместимости."""

from exposlides.design_audit import capacity_risk
from exposlides.design_layout import create_variants
from exposlides.design_models import Box
from exposlides.template_layout import composition_brief, native_layout
from tests.test_template_design import _profile, _story


def _columns(pattern, index, count):
    result = pattern.model_copy(deep=True)
    result.source_slide_index = index
    result.name = f"Смысловые блоки {count}"
    title, body = result.slots
    gap = 12700 * 12
    width = (body.box.width - gap * (count - 1)) // count
    bodies = []
    for number in range(count):
        slot = body.model_copy(deep=True)
        slot.shape_id = 3 + number
        slot.element_id = f"body-{number}"
        slot.box.left += number * (width + gap)
        slot.box.width = width
        bodies.append(slot)
    result.slots = [title, *bodies]
    result.mutable_shape_ids = [slot.shape_id for slot in result.slots]
    return result


def _photo(pattern, index):
    result = pattern.model_copy(deep=True)
    result.source_slide_index = index
    result.name = "Текст и фото"
    body = result.slots[1]
    original_width = body.box.width
    body.box.width = int(original_width * .46)
    image = Box(
        left=body.box.left + int(original_width * .52),
        top=body.box.top,
        width=int(original_width * .48),
        height=int(body.box.height * 1.25),
    )
    result.protected_regions = [image]
    result.protected_shape_ids = [90]
    result.replaceable_images = {90: image}
    return result


def test_short_deck_brief_reaches_rich_layouts_after_duplicate_plain_samples(tmp_path):
    profile = _profile(tmp_path)
    plain = profile.patterns[0]
    three = _columns(plain, 31, 3)
    four = _columns(plain, 32, 4)
    duplicates = [
        plain.model_copy(update={"source_slide_index": index}, deep=True)
        for index in range(2, 31)
    ]
    profile.patterns = [plain, *duplicates, three, four]
    before = profile.model_dump()

    crowded_brief = composition_brief(profile, 4)
    unique = profile.model_copy(update={"patterns": [plain, three, four]})
    unique_brief = composition_brief(unique, 4)

    assert {3, 4} <= set(crowded_brief["paragraph_counts"].values())
    assert crowded_brief["paragraph_counts"] == unique_brief["paragraph_counts"]
    assert profile.model_dump() == before


def test_story_prefers_fitting_photo_over_source_order_when_its_cost_is_lower(tmp_path):
    profile = _profile(tmp_path)
    photo = _photo(profile.patterns[0], 20)
    profile.patterns.append(photo)
    source = _story().slides[0]
    before = profile.model_dump()

    selected, blocks = native_layout(profile, source, "story", 1)

    assert selected.source_slide_index == 20
    assert not any(capacity_risk(block) for block in blocks)
    assert [text for block in blocks for text in block.items] == source.paragraphs
    assert profile.model_dump() == before


def test_short_decks_mix_families_before_exhausting_plain_geometry_variations(tmp_path):
    profile = _profile(tmp_path)
    plain = profile.patterns[0]
    variations = []
    for index in range(2, 9):
        candidate = plain.model_copy(deep=True)
        candidate.source_slide_index = index
        candidate.slots[1].box.width -= index * 12700 * 4
        variations.append(candidate)
    columns = _columns(plain, 9, 2)
    photo = _photo(plain, 10)
    profile.patterns = [plain, *variations, columns, photo]
    source = _story(["One grounded observation.", "Another independent observation."])
    source.slides = [source.slides[0].model_copy(update={"id": f"slide-{index}"})
                     for index in range(3)]
    patterns = {pattern.source_slide_index: pattern for pattern in profile.patterns}
    before = profile.model_dump()

    plans = create_variants(profile, source)

    for plan in plans:
        chosen = {slide.source_slide_index for slide in plan.slides}
        assert {9, 10} <= chosen
        assert chosen.intersection(range(1, 9))
        for slide, story_slide in zip(plan.slides, source.slides, strict=True):
            assert not any(capacity_risk(block) for block in slide.blocks)
            assert [text for block in slide.blocks for text in block.items] == story_slide.paragraphs
            pattern = patterns[slide.source_slide_index]
            slots = {slot.shape_id: slot for slot in pattern.slots}
            assert all(block.box == slots[block.source_shape_id].box for block in slide.blocks)
    assert profile.model_dump() == before


def test_fake_llm_sees_late_rich_layouts_but_retries_fabricated_filler(
    tmp_path, service_importer, monkeypatch,
):
    import asyncio
    import json
    from copy import deepcopy
    from pathlib import Path

    from exposlides.design_models import DesignRequest
    from tests.test_design_generation import Client

    # Конфигурация импортируется из пустого каталога, без локальных секретов.
    monkeypatch.chdir(tmp_path)
    service = Path(__file__).resolve().parents[1] / "services" / "content-service"
    module = service_importer(service, "app.design_main")
    profile = _profile(tmp_path)
    plain = profile.patterns[0]
    plain.slots[1].text = "Секретный текст образца 999%"
    profile.patterns = [
        plain.model_copy(update={"source_slide_index": index}, deep=True)
        for index in range(1, 31)
    ] + [_columns(plain, 31, 3), _columns(plain, 32, 4)]
    facts = [
        ["Команда сократила обработку на 20%.", "Данные проверяются автоматически."],
        ["Данные остаются на сервере компании."],
        ["Оператор подтверждает результат проверки."],
    ]
    source = "\n\n".join(" ".join(paragraphs) for paragraphs in facts)
    good = {
        "title": "Обработка данных",
        "slides": [
            {"id": f"slide-{index}", "title": title, "paragraphs": paragraphs,
             "source_ids": [f"source-{index}"]}
            for index, (title, paragraphs) in enumerate(zip(
                ["Автоматизация обработки", "Данные компании", "Проверка оператором"], facts,
                strict=True,
            ), 1)
        ],
    }
    bad = deepcopy(good)
    bad["slides"][0]["paragraphs"][0] = "Команда сократила обработку на 40%."
    client = Client([bad, good])

    result = asyncio.run(module.generate(
        DesignRequest(script=source, slide_count=3), client, profile=profile,
    ))

    assert len(client.prompts) == 2
    payload = json.loads(client.prompts[0].split("<DATA>\n", 1)[1].split("\n</DATA>", 1)[0])
    assert {3, 4} <= set(payload["template_layout"]["paragraph_counts"].values())
    assert "Секретный текст образца" not in client.prompts[0]
    assert "999%" not in client.prompts[0]
    assert "Не дополняй содержание догадками" in client.prompts[0]
    assert "При нехватке материала оставь меньше тезисов" in client.prompts[0]
    # Число карточек не превращается в квоту и не ослабляет проверку фактов.
    assert [slide.paragraphs for slide in result.slides] == facts
    assert "20%" in result.slides[0].paragraphs[0]
    assert "40%" not in result.model_dump_json()


def test_spacious_single_body_catalog_does_not_limit_content_to_one_paragraph(tmp_path):
    profile = _profile(tmp_path)
    plain = profile.patterns[0]
    for index in range(2, 9):
        candidate = plain.model_copy(deep=True)
        candidate.source_slide_index = index
        candidate.slots[1].box.width -= index * 12700 * 4
        profile.patterns.append(candidate)
    before = profile.model_dump()

    brief = composition_brief(profile, 8)

    assert 1 not in brief.get("paragraph_counts", {}).values()
    assert profile.model_dump() == before


def test_long_decks_balance_families_across_many_unused_plain_variations(tmp_path):
    profile = _profile(tmp_path)
    plain = profile.patterns[0]
    for index in range(2, 9):
        candidate = plain.model_copy(deep=True)
        candidate.source_slide_index = index
        candidate.slots[1].box.width -= index * 12700 * 4
        profile.patterns.append(candidate)
    profile.patterns.extend([_columns(plain, 9, 2), _photo(plain, 10)])
    source = _story(["One grounded observation.", "Another independent observation."])
    source.slides = [source.slides[0].model_copy(update={"id": f"slide-{index}"})
                     for index in range(10)]

    for plan in create_variants(profile, source):
        chosen = [slide.source_slide_index for slide in plan.slides]
        assert chosen.count(9) >= 3
        assert chosen.count(10) >= 3
        assert any(index in range(1, 9) for index in chosen)
        for slide, story_slide in zip(plan.slides, source.slides, strict=True):
            assert not any(capacity_risk(block) for block in slide.blocks)
            assert [text for block in slide.blocks for text in block.items] == story_slide.paragraphs
