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
    # Короткий заголовок не дробим, если строка достижима при допустимом кегле.
    # Уменьшение, которое всё равно оставит перенос, само по себе не помогает.
    single_line = (kind == "title" and _short_title(source.title)
                   and _line_count(block, minimum) == 1)
    while block.style.size > minimum and (
        _load(block) > 1 or (single_line and _line_count(block) > 1)
    ):
        block.style.size = max(minimum, block.style.size - 1)
    return block


def _short_title(text: str) -> bool:
    return len(text) <= 32 and len(text.split()) <= 3 and len(text.splitlines()) == 1


def _line_count(block: PlacedBlock, size: float | None = None) -> int:
    # Оцениваем каждый исходный слот отдельно, а не пустоту между ними.
    width = max(1, block.box.width / 12700 - 32)
    columns = max(1, int(width / ((size if size is not None else block.style.size) * 0.60)))
    return sum(max(1, math.ceil(len(line) / columns))
               for text in (block.items or [block.text]) for line in text.splitlines())


def _load(block: PlacedBlock) -> float:
    if not block.text and not block.items:
        return 0.0
    return (_line_count(block) * block.style.size * 1.25 + 12) / (block.box.height / 12700)


def _assign(pattern: SlidePattern, source: StorySlide) -> list[PlacedBlock] | None:
    titles, bodies = _slots(pattern, "title"), _slots(pattern, "body")
    bodies = [slot for slot in bodies if not re.search(
        r"иконки можно брать|число разделов\s*=|точки используются для навигации",
        slot.text, re.I,
    )]
    if len(titles) != 1 or not bodies:
        return None
    if any(overlap(titles[0].box, region) for region in pattern.protected_regions):
        return None
    # Служебная подпись или пересекающийся неиспользуемый слот не должны
    # отбрасывать весь макет. Выбираем безопасные области, остальные очищает builder.
    available = [slot for slot in bodies
                 if not overlap(slot.box, titles[0].box)
                 and not any(overlap(slot.box, region) for region in pattern.protected_regions)]
    selected = []
    for slot in sorted(available, key=lambda slot: -slot.box.width * slot.box.height):
        if not any(overlap(slot.box, other.box) for other in selected):
            selected.append(slot)
        if len(selected) == 12:
            break
    bodies = sorted(selected, key=lambda slot: (round(slot.box.top / 100000), slot.box.left))
    if not bodies:
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
        r"скриншот|мокап|оформление кода|телефон|qr|спикер|имя\s*фамилия|screenshot|mockup|цитата|таймлайн|ганта|фактоид",
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


def composition_key(pattern: SlidePattern) -> tuple:
    """Геометрия и типографика, без номера слайда, id фигур и текста образца."""
    def box_key(box):
        return tuple(round(value / 12700) for value in box.model_dump().values())

    return (
        tuple(sorted((slot.role, box_key(slot.box), slot.style.font, round(slot.style.size, 1))
                     for slot in pattern.slots if slot.role in {"title", "body"})),
        tuple(sorted(box_key(box) for box in pattern.protected_regions)),
        tuple(sorted(box_key(box) for box in [*pattern.replaceable_images.values(),
                                             *pattern.layout_images.values()])),
    )


def composition_family(pattern: SlidePattern) -> tuple[int, bool]:
    """Число безопасных текстовых блоков и наличие крупной графики/фотографии."""
    sample = StorySlide(id="sample", title="Тема", paragraphs=["Тезис"],
                        source_ids=["source-1"])
    blocks = _assign(pattern, sample) or []
    count = sum(block.kind == "text" and block.box.width >= 100 * 12700
                and block.box.height >= 36 * 12700 for block in blocks)
    graphic = bool(pattern.replaceable_images or pattern.layout_images) or any(
        region.width * region.height >= pattern.content_box.width * pattern.content_box.height * .35
        for region in pattern.protected_regions
    )
    return count, graphic


def native_layout(profile: TemplateProfile, source: StorySlide, variant: str,
                  index: int, previous: tuple[int, ...] = (),
                  alternatives: tuple[int, ...] = (),
                  *, require_image: bool = False, prefer_cover: bool = True,
                  ) -> tuple[SlidePattern, list[PlacedBlock]] | None:
    """Выбрать композицию по числу тезисов и вместимости реальных областей."""
    choices = []
    desired = {"story": 1, "evidence": 2, "cards": len(source.paragraphs)}[variant]
    for pattern in profile.patterns:
        if require_image and not (pattern.replaceable_images or pattern.layout_images):
            continue
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
        cost += alternatives.count(pattern.source_slide_index) * 12
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
    fitting = [choice for choice in fitting if all(_load(b) <= 1 for b in choice[3])] or fitting
    complete = [choice for choice in fitting if not any(
        block.kind == "text" and not block.items
        and block.box.width >= 100 * 12700 and block.box.height >= 36 * 12700
        for block in choice[3]
    )]
    pool = complete or fitting or choices
    covers = ([choice for choice in fitting if _cover(choice[2])]
              if index == 0 and prefer_cover else [])
    if index:
        ordinary = [choice for choice in pool if not _cover(choice[2])]
        pool = ordinary or pool
    # Обложка сохраняет отдельную роль; содержательные слайды чередуют композиции.
    pool = covers or pool
    if fitting:
        # Разнообразие не должно дробить короткий заголовок. Если одна строка
        # недостижима во всех подходящих образцах, сохраняем допустимые переносы.
        if _short_title(source.title):
            single_line = [choice for choice in pool if _line_count(choice[3][0]) == 1]
            pool = single_line or pool
        keys = {pattern.source_slide_index: composition_key(pattern) for pattern in profile.patterns}
        # При наличии вместимой альтернативы не повторяем соседнюю композицию,
        # даже если глобальные счётчики семейств предпочитают её повторить.
        if previous and previous[-1] in keys:
            different_neighbor = [choice for choice in pool
                                  if keys[choice[1]] != keys[previous[-1]]]
            pool = different_neighbor or pool
        # Разные координаты одного текстового поля не дают разного ритма.
        # Множество простых образцов не должно вытеснять повтор подходящего фото.
        families = {pattern.source_slide_index: composition_family(pattern)
                    for pattern in profile.patterns}
        previous_families = [families[index] for index in previous if index in families]
        least_family = min(previous_families.count(families[choice[1]]) for choice in pool)
        pool = [choice for choice in pool
                if previous_families.count(families[choice[1]]) == least_family]
        # Внутри подходящего семейства сначала пробуем новую геометрию.
        # Другой source index сам по себе не означает новую композицию.
        previous_keys = [keys[index] for index in previous if index in keys]
        least = min(previous_keys.count(keys[choice[1]]) for choice in pool)
        pool = [choice for choice in pool if previous_keys.count(keys[choice[1]]) == least]
        alternative_keys = {keys[index] for index in alternatives if index in keys}
        different = [choice for choice in pool if keys[choice[1]] not in alternative_keys]
        pool = different or pool
        matching = [choice for choice in pool if sum(
            block.kind == "text" and bool(block.items) for block in choice[3]
        ) == len(source.paragraphs)]
        pool = matching or pool

    def key(item):
        # Если набор мал, меняем соседство, а не запускаем прежний круг макетов.
        transitions = sum(a == previous[-1] and b == item[1]
                          for a, b in zip(previous, previous[1:])) if previous else 0
        return (transitions, item[0], item[1])

    _, _, pattern, blocks = min(pool, key=key)
    return pattern, blocks


def composition_brief(profile: TemplateProfile, slide_count: int) -> dict:
    """Число смысловых блоков пригодных макетов; текст образцов не передаётся LLM."""
    sample = StorySlide(id="sample", title="Тема", paragraphs=["Короткий тезис"],
                        source_ids=["source-1"])
    candidates, title_budgets, seen = [], [], set()
    body_budgets = []
    for pattern in profile.patterns:
        if _cover(pattern) or _specialized(pattern) or pattern.visual_shape_ids:
            continue
        blocks = _assign(pattern, sample)
        if not blocks:
            continue
        bodies = [block for block in blocks if block.kind == "text"
                  and block.box.width >= 100 * 12700 and block.box.height >= 36 * 12700]
        count = len(bodies)
        if not 1 <= count <= 6:
            continue
        filled = _assign(pattern, sample.model_copy(update={"paragraphs": ["Короткий тезис"] * count}))
        if filled and _overflow(profile, filled) == 0:
            key = composition_key(pattern)
            if key in seen:
                continue
            seen.add(key)
            candidates.append((pattern, count))
            title = blocks[0]
            size = min(title.style.size, max(14, title.style.size * .8))
            columns = max(1, int((title.box.width / 12700 - 32) / (size * .60)))
            lines = max(1, int((title.box.height / 12700 - 12) / (size * 1.25)))
            title_budgets.append(max(1, int(columns * lines * .85)))
            # Оцениваем настоящие области при исходном кегле, не уменьшая шрифт
            # ради обещанного объёма. Запас учитывает переносы и разбиение на абзацы.
            characters = 0
            for block in bodies:
                slot = next(slot for slot in pattern.slots
                            if slot.shape_id == block.source_shape_id)
                size = max([slot.style.size, *slot.paragraph_font_sizes])
                columns = max(0, int((block.box.width / 12700 - 32) / (size * .60)))
                lines = max(0, int((block.box.height / 12700 - 12) / (size * 1.25)))
                # Однострочные подписи не задают бюджет содержательного слайда.
                if columns >= 8 and lines >= 2:
                    characters += int(columns * lines * .8)
            if characters:
                body_budgets.append({
                    "source_slide_index": pattern.source_slide_index,
                    "paragraph_count": count,
                    "max_characters": characters,
                    "max_words": max(1, characters // 7),
                })
    brief = {"content_title_max_characters": min(80, min(title_budgets))} if title_budgets else {}
    if body_budgets:
        brief.update(
            body_text_budgets=body_budgets,
            body_text_guidance="Бюджеты основного текста приблизительны: выбери вместимый макет "
                               "для содержательного раскрытия источника. Не сокращай все слайды "
                               "до бюджета самого узкого макета. Это не обязательный объём и не "
                               "гарантия вместимости: её отдельно проверяет приложение. Если "
                               "исходного материала мало, не добавляй текст ради заполнения.",
        )
    if not candidates:
        return brief
    has_cover = slide_count > 1 and bool(cover_patterns(profile))
    # Выбираем представителей всего каталога, а не первые страницы шаблона.
    # Дубликаты и множество одноколоночных образцов не вытесняют карточки/фото.
    counts, families = [], []
    family_by_index = {pattern.source_slide_index: composition_family(pattern)
                       for pattern, _ in candidates}
    while candidates and len(counts) < slide_count - int(has_cover):
        pattern, count = min(candidates, key=lambda item: (
            families.count(family_by_index[item[0].source_slide_index]),
            counts.count(item[1]), abs(item[1] - 3),
            -int(family_by_index[item[0].source_slide_index][1]),
            composition_key(item[0]),
        ))
        candidates.remove((pattern, count))
        counts.append(count)
        families.append(family_by_index[pattern.source_slide_index])
    # При нехватке макетов не навязываем повторение цикла.
    sequence = ([(1, True)] if has_cover else []) + [
        (count, family[1]) for count, family in zip(counts, families, strict=True)
    ]
    # Просторное одиночное поле вмещает несколько тезисов. Один физический слот
    # не должен заставлять модель сворачивать всё содержание в одно предложение.
    hints = {str(index + 1): count for index, (count, graphic) in enumerate(sequence)
             if count > 1 or graphic}
    if not hints:
        return brief
    return brief | {"paragraph_counts": hints,
            "instruction": "Распредели материал по числу смысловых блоков макетов. "
                           "Каждый блок — самостоятельная мысль с необходимым пояснением. "
                           "Не добавляй неподтверждённые сведения ради количества."}
