"""Заполнение настоящих текстовых областей шаблона без перестройки композиции."""

from __future__ import annotations

import itertools
import math
import re

from exposlides.design_geometry import overlap
from exposlides.design_models import PlacedBlock, SlidePattern, Slot, StorySlide, TemplateProfile


def _slots(pattern: SlidePattern, role: str) -> list[Slot]:
    return sorted(
        (slot for slot in pattern.slots if slot.role == role),
        key=lambda slot: (round(slot.box.top / 100000), slot.box.left),
    )


def _block(slot: Slot, source: StorySlide, items: list[str], kind: str) -> PlacedBlock:
    style = slot.style.model_copy()
    if slot.paragraph_font_sizes:
        lines = sum(len(text.splitlines()) for text in items) if items else 1
        style.size = max(slot.paragraph_font_sizes[:max(1, lines)])
    block = PlacedBlock(
        id=f"{source.id}-{kind}-{slot.shape_id}", kind=kind,
        source_shape_id=slot.shape_id, box=slot.box.model_copy(),
        style=style, source_ids=source.source_ids,
        text=source.title if kind == "title" else "", items=items,
    )
    minimum = min(style.size, max(14, style.size * 0.8))
    while _load(block) > 1 and block.style.size > minimum:
        block.style.size = max(minimum, block.style.size - 1)
    return block


def _load(block: PlacedBlock) -> float:
    # Оцениваем каждый исходный слот отдельно, а не пустоту между ними.
    width = max(1, block.box.width / 12700 - 32)
    columns = max(1, int(width / (block.style.size * 0.60)))
    lines = sum(max(1, math.ceil(len(line) / columns))
                for text in (block.items or [block.text]) for line in text.splitlines())
    return (lines * block.style.size * 1.25 + 12) / (block.box.height / 12700)


def _assign(pattern: SlidePattern, source: StorySlide) -> list[PlacedBlock] | None:
    titles, bodies = _slots(pattern, "title"), _slots(pattern, "body")
    if len(titles) != 1 or not bodies or len(bodies) > 12:
        return None
    slots = [*titles, *bodies]
    if any(overlap(slot.box, region) for slot in slots for region in pattern.protected_regions):
        return None
    if any(overlap(first.box, second.box)
           for index, first in enumerate(slots) for second in slots[index + 1:]):
        return None
    count = min(len(bodies), len(source.paragraphs))
    # Непрерывные группы сохраняют порядок тезисов. Все исходные области
    # заполняются или очищаются, служебный текст не остаётся в результате.
    best = None
    for cuts in itertools.combinations(range(1, len(source.paragraphs)), count - 1):
        edges = (0, *cuts, len(source.paragraphs))
        groups = [source.paragraphs[a:b] for a, b in zip(edges, edges[1:])]
        groups.extend([] for _ in range(len(bodies) - count))
        blocks = [_block(slot, source, group, "text")
                  for slot, group in zip(bodies, groups, strict=True)]
        loads = [_load(block) for block in blocks]
        cost = sum(max(0, load - 1) ** 2 for load in loads) * 100
        cost += sum(load ** 2 for load in loads) * 0.1
        if best is None or cost < best[0]:
            best = cost, blocks
    return [_block(titles[0], source, [], "title"), *best[1]]


def _cover(pattern: SlidePattern) -> bool:
    name = pattern.name.lower()
    return any(word in name for word in ("титульный", "title slide", "cover")) and not any(
        word in name for word in ("раздел", "section", "финаль", "final")
    )


def _specialized(pattern: SlidePattern) -> bool:
    sample = " ".join([pattern.name, *[slot.text for slot in pattern.slots]]).lower()
    return bool(re.search(
        r"скриншот|мокап|оформление кода|телефон|qr|спикер|имя\s*фамилия|screenshot|mockup",
        sample,
    ))


def _overflow(profile: TemplateProfile, blocks: list[PlacedBlock]) -> float:
    title, *body = blocks
    below = min([b.box.top for b in body if b.box.top > title.box.top] + [profile.height])
    available = max(title.box.height, below - title.box.top)
    return sum(max(0, _load(block) - 1) ** 2 for block in body) + max(
        0, _load(title) * title.box.height / available - 1,
    ) ** 2


def cover_patterns(profile: TemplateProfile) -> list[SlidePattern]:
    """Только пригодные обложки; фото спикера не подставляется вместо нового автора."""
    sample = StorySlide(id="cover", title="Тема", paragraphs=["Подзаголовок"],
                        source_ids=["source-1"])
    return [pattern for pattern in profile.patterns
            if _cover(pattern) and not _specialized(pattern) and not pattern.visual_shape_ids
            and (blocks := _assign(pattern, sample)) is not None
            and _overflow(profile, blocks) == 0]


def cover_fits(profile: TemplateProfile, source: StorySlide) -> bool:
    return source.visual is None and any(
        (blocks := _assign(pattern, source)) is not None and _overflow(profile, blocks) == 0
        for pattern in cover_patterns(profile)
    )


def cover_brief(profile: TemplateProfile) -> dict:
    """Консервативный бюджет текста из геометрии обложки, без текста образца."""
    pattern = cover_patterns(profile)[0]
    title = _slots(pattern, "title")[0]
    body = _slots(pattern, "body")[0]

    def budget(slot: Slot, height: int) -> int:
        size = min(slot.style.size, max(14, slot.style.size * 0.8))
        columns = max(1, int((slot.box.width / 12700 - 32) / (size * 0.60)))
        lines = max(1, int((height / 12700 - 12) / (size * 1.25)))
        return max(1, int(columns * lines * 0.85))

    return {"first_slide": "cover",
            "title_max_characters": min(80, budget(title, max(
                title.box.height, body.box.top - title.box.top,
            ))),
            "subtitle_max_characters": min(120, budget(body, body.box.height))}


def native_layout(profile: TemplateProfile, source: StorySlide, variant: str,
                  index: int, previous: tuple[int, ...] = (),
                  ) -> tuple[SlidePattern, list[PlacedBlock]] | None:
    """Выбрать композицию по числу тезисов и вместимости реальных областей."""
    choices = []
    desired = {"story": 1, "evidence": 2, "cards": len(source.paragraphs)}[variant]
    for pattern in profile.patterns:
        # Макеты с диаграммами не превращаем в текстовые страницы.
        if pattern.visual_shape_ids:
            continue
        if _specialized(pattern):
            continue
        blocks = _assign(pattern, source)
        if blocks is None:
            continue
        body = [block for block in blocks if block.kind == "text"]
        overflow = _overflow(profile, blocks)
        empty = sum(not block.items for block in body)
        small = sum(max(0, 16 - block.style.size) for block in body) / len(body)
        cost = overflow * 100 + abs(len(body) - desired) * 2 + empty * 8 + small
        # Сохраняем фотографии и фирменную графику. Их площадь сама по себе
        # не делает макет хуже: пересечения и вместимость уже проверены выше.
        if any(region.width * region.height > profile.width * profile.height * 0.2
               for region in pattern.protected_regions):
            cost -= 2
        cost += previous.count(pattern.source_slide_index) * 5
        if previous and previous[-1] == pattern.source_slide_index:
            cost += 3
        # Специальные обложки подходят только началу и только при вместимом тексте.
        cover = _cover(pattern)
        if cover and index:
            cost += 30
        elif cover and overflow == 0:
            cost -= 20
        choices.append((cost, pattern.source_slide_index, pattern, blocks))
    if not choices:
        return None
    # Разнообразие не оправдывает переполнение: сначала выбираем вместимые макеты.
    fitting = [choice for choice in choices if _overflow(profile, choice[3]) == 0]
    _, _, pattern, blocks = min(fitting or choices, key=lambda item: item[:2])
    return pattern, blocks
