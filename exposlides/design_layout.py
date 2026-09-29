"""Три разные композиции одной истории с сохранением фактов и правил шаблона."""

from __future__ import annotations

import math
from pathlib import Path

from exposlides.design_audit import capacity_risk
from exposlides.design_data import cell_text
from exposlides.design_geometry import clip, free_box
from exposlides.design_models import (
    Box,
    ContentPlan,
    Dataset,
    DeckPlan,
    PlacedBlock,
    SlideInstance,
    SlidePattern,
    StorySlide,
    TemplateProfile,
)
from exposlides.template_layout import native_layout

VARIANTS = {
    "story": ("История", "Последовательный рассказ в исходных макетах шаблона"),
    "evidence": ("Доказательства", "Макеты шаблона для сопоставления тезисов и данных"),
    "cards": ("Смысловые блоки", "Отдельные области исходного шаблона для ключевых тезисов"),
}


def _inset(box: Box, horizontal: float, vertical: float) -> Box:
    dx, dy = int(box.width * horizontal), int(box.height * vertical)
    return Box(
        left=box.left + dx,
        top=box.top + dy,
        width=max(1, box.width - 2 * dx),
        height=max(1, box.height - 2 * dy),
    )


def _luminance(color: str) -> float:
    values = [int(color[offset : offset + 2], 16) / 255 for offset in (0, 2, 4)]
    return sum(
        (value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4) * weight
        for value, weight in zip(values, (0.2126, 0.7152, 0.0722))
    )


def _surface(pattern: SlidePattern) -> str | None:
    foreground = _luminance(pattern.body_style.color)

    def contrast(color):
        background = _luminance(color)
        return (max(background, foreground) + 0.05) / (min(background, foreground) + 0.05)

    best = max(pattern.palette, key=contrast) if pattern.palette else None
    return best if best and contrast(best) >= 4.5 else None


def _accent(pattern: SlidePattern) -> str:
    def saturation(color):
        channels = [int(color[offset : offset + 2], 16) for offset in (0, 2, 4)]
        return max(channels) - min(channels)

    # Palette упорядочена: фактические цвета образца, затем accent1–6 темы.
    # Максимальная насыщенность иначе часто выбирает служебный синий hyperlink.
    return next((color for color in pattern.palette if saturation(color) >= 32),
                pattern.body_style.color)


def _pattern(
    profile: TemplateProfile, source: StorySlide, variant: str, index: int
) -> SlidePattern:
    candidates = profile.patterns
    if source.visual and source.visual.kind == "smartart":
        candidates = [
            pattern
            for pattern in candidates
            if pattern.visual_shape_ids.get("smartart")
            and (
                source.visual.source_shape_id is None
                or source.visual.source_shape_id in pattern.visual_shape_ids["smartart"]
            )
        ]
        if not candidates:
            raise ValueError("В шаблоне нет нативного SmartArt-образца для запрошенной схемы")

    def score(pattern):
        box = pattern.content_box
        area = box.width * box.height
        # Графики и схемы выигрывают от широких областей; обычный текст — от высоты.
        ratio = box.width / box.height
        preferred = 1.8 if source.visual else (1.3 if variant == "story" else 1.8)
        aspect = min(ratio / preferred, preferred / ratio)
        font = max(10, pattern.body_style.size)
        capacity = area / (font * 12700) ** 2
        return capacity * (0.8 + 0.2 * aspect)

    ranked = sorted(
        candidates, key=lambda candidate: (-score(candidate), candidate.source_slide_index)
    )
    # Чередование только среди почти равноценных образцов не жертвует вместимостью.
    near = [candidate for candidate in ranked if score(candidate) >= score(ranked[0]) * 0.9]
    return near[index % min(3, len(near))]


def _title_box(profile: TemplateProfile, pattern: SlidePattern) -> Box:
    content = pattern.content_box
    original = next(
        (slot.box for slot in pattern.slots if slot.role == "title"),
        Box(
            left=content.left,
            top=int(profile.height * 0.04),
            width=content.width,
            height=max(
                1, min(int(profile.height * 0.12), content.top - int(profile.height * 0.05))
            ),
        ),
    )
    clipped = clip(original, profile.width, profile.height)
    occupied = [
        *pattern.protected_regions,
        *[slot.box for slot in pattern.slots if slot.role == "page_number"],
        content,
    ]
    result = free_box(clipped, occupied) if clipped else None
    if result is None:
        raise ValueError(f"В образце {pattern.source_slide_index} нет места для заголовка")
    return result


def _text_height(paragraphs: list[str], width: int, size: float) -> int:
    capacity = max(1, int((width / 12700 - 16) / (size * 0.54)))
    lines = sum(max(1, math.ceil(len(line) / capacity))
                for paragraph in paragraphs for line in paragraph.splitlines())
    return math.ceil((lines * size * 1.25 + 12) * 12700)


def _row_weights(paragraphs, width, pattern, gap, maximum):
    columns = min(maximum, len(paragraphs), max(
        1, width // int(max(18, pattern.body_style.size) * 12700 * 12),
    ))
    cell_width = max(1, (width - gap * (columns - 1)) // columns)
    minimum_size = min(pattern.body_style.size, max(14, pattern.body_style.size * 0.8))
    weights = [max(_text_height([text], cell_width, minimum_size)
                   for text in paragraphs[index:index+columns])
               for index in range(0, len(paragraphs), columns)]
    return columns, cell_width, weights


def _text_cells(box, paragraphs, pattern, gap, variant):
    maximum = 2 if variant == "evidence" else 3
    area = _inset(box, 0.04, 0) if variant == "cards" else box
    columns, width, weights = _row_weights(paragraphs, area.width, pattern, gap, maximum)
    if variant == "cards":
        # Сначала резервируем место строкам. Декоративные отступы уменьшаются,
        # когда иначе пришлось бы переполнять блок или делать шрифт нечитаемым.
        spare = max(0, area.height-sum(weights)-gap*(len(weights)-1))
        inset = min(int(area.height*0.06), spare//2)
        area = area.model_copy(update={"top": area.top+inset, "height": area.height-2*inset})
    available = max(len(weights), area.height-gap*(len(weights)-1))
    boundaries = [0]
    cumulative = 0
    for weight in weights:
        cumulative += weight
        boundaries.append(round(available*cumulative/sum(weights)))
    return [Box(
        left=area.left+(index % columns)*(width+gap),
        top=area.top+boundaries[index//columns]+(index//columns)*gap,
        width=width, height=max(1, boundaries[index//columns+1]-boundaries[index//columns]),
    ) for index in range(len(paragraphs))]


def _split_visuals(box: Box, count: int, variant: str, gap: int,
                   source: StorySlide, pattern: SlidePattern) -> tuple[Box, list[Box]]:
    minimum_size = min(pattern.body_style.size, max(14, pattern.body_style.size * 0.8))
    minimum_caption = _text_height(source.paragraphs, box.width, minimum_size)
    preferred_caption = _text_height(source.paragraphs, box.width, pattern.body_style.size)
    # Длинная подпись не должна вытеснять область диаграммы до узкой полосы.
    # В этом случае story получает широкую текстовую колонку слева.
    stacked = count == 2 or (variant == "story" and minimum_caption <= box.height*0.34)
    if stacked:
        text_height = max(1, int(max(box.height*0.28, min(preferred_caption, box.height*0.42))))
        visual_top = box.top+text_height+gap
        visual_height = max(1, box.height-text_height-gap)
        width = max(1, (box.width-gap*(count-1))//count)
        visual_boxes = [Box(left=box.left+index*(width+gap), top=visual_top,
                            width=width, height=visual_height) for index in range(count)]
        if variant == "cards":
            visual_boxes.reverse()
        return Box(left=box.left, top=box.top, width=box.width, height=text_height), visual_boxes
    fraction = {"story": 0.50, "evidence": 0.34, "cards": 0.42}[variant]
    if variant == "evidence":
        # Текст таблицы не может забирать место у соседних исходных фактов.
        while fraction < 0.48:
            _, _, weights = _row_weights(source.paragraphs, int(box.width*fraction), pattern, gap, 2)
            if sum(weights)+gap*(len(weights)-1) <= box.height:
                break
            fraction += 0.02
    text_width = max(1, int(box.width*fraction))
    visual_width = max(1, box.width-text_width-gap)
    if variant in {"story", "evidence"}:
        return (
            Box(left=box.left, top=box.top, width=text_width, height=box.height),
            [Box(left=box.left+text_width+gap, top=box.top,
                 width=visual_width, height=box.height)],
        )
    return (
        Box(left=box.left+visual_width+gap, top=box.top, width=text_width, height=box.height),
        [Box(left=box.left, top=box.top, width=visual_width, height=box.height)],
    )


def _table_fits(dataset: Dataset, box: Box, font_size: float) -> bool:
    """Оценка ячеек с теми же равными колонками и отступами, что у builder."""
    width = box.width / 12700 / len(dataset.columns) - 12
    height = box.height / 12700 / (len(dataset.rows) + 1) - 8
    if width < font_size * 0.60 or height < font_size * 1.1:
        return False
    capacity = max(1, int(width / (font_size * 0.60)))
    for row in (dataset.columns, *dataset.rows):
        for value in row:
            lines = sum(max(1, math.ceil(len(line) / capacity))
                        for line in (cell_text(value).splitlines() or [""]))
            if lines * font_size * 1.1 > height:
                return False
    return True


def _visual_block(source: StorySlide, pattern: SlidePattern, box: Box, variant: str,
                  datasets: dict[str, Dataset]) -> PlacedBlock:
    visual = source.visual
    common = dict(
        id=f"{source.id}-visual",
        box=box,
        style=pattern.body_style,
        source_ids=source.source_ids,
        fill=_accent(pattern),
    )
    if visual.kind in {"table", "bar", "line", "pie"}:
        dataset = datasets.get(visual.dataset_id)
        if dataset is None:
            raise ValueError(f"{source.id}: неизвестный набор данных")
        fits = _table_fits(dataset, box, pattern.body_style.size)
        if visual.kind == "table" and not fits:
            raise ValueError(
                f"{source.id}: таблица «{dataset.name}» не помещается в области шаблона "
                "при читаемом размере текста. Выберите график или разделите данные "
                "на несколько таблиц; строки не обрезаются."
            )
        table = visual.kind == "table" or (variant == "evidence" and fits)
        return PlacedBlock(
            kind="table" if table else "chart",
            dataset_id=visual.dataset_id,
            chart_type=None if table else visual.kind,
            **common,
        )
    if visual.kind == "smartart":
        return PlacedBlock(
            kind="smartart",
            items=visual.labels,
            source_shape_id=visual.source_shape_id or pattern.visual_shape_ids["smartart"][0],
            **common,
        )
    if visual.kind == "icon":
        size = min(box.width, box.height)
        common["box"] = Box(
            left=box.left + (box.width - size) // 2,
            top=box.top + (box.height - size) // 2,
            width=size,
            height=size,
        )
        return PlacedBlock(kind="icon", icon=visual.icon, **common)
    return PlacedBlock(kind=visual.kind, items=visual.labels, **common)


def create_variants(
    profile: TemplateProfile,
    story: ContentPlan,
    datasets: list[Dataset] | None = None,
    *,
    generated_image: Path | None = None,
    image_slide_id: str | None = None,
    generated_images: dict[str, Path | list[Path]] | None = None,
    template_images_only: bool = False,
) -> list[DeckPlan]:
    """Варианты выбирают исходные композиции; текстовые слоты сохраняют оформление."""
    if image_slide_id and image_slide_id not in {slide.id for slide in story.slides}:
        raise ValueError("Для изображения указан отсутствующий слайд истории")
    image_target = image_slide_id or story.slides[0].id
    images = dict(generated_images or {})
    if generated_image is not None:
        if images:
            raise ValueError("Нельзя одновременно передать одиночное изображение и набор")
        images[image_target] = generated_image
    if images.keys() - {slide.id for slide in story.slides}:
        raise ValueError("Для изображения указан отсутствующий слайд истории")
    dataset_by_id = {dataset.id: dataset for dataset in datasets or []}
    results = []
    for variant, (name, description) in VARIANTS.items():
        slides = []
        for index, source in enumerate(story.slides):
            image = images.get(source.id)
            has_image = image is not None
            native = native_layout(profile, source, variant, index,
                                   tuple(slide.source_slide_index for slide in slides),
                                   tuple(plan.slides[index].source_slide_index for plan in results),
                                   require_image=has_image and not template_images_only,
                                   prefer_cover=len(story.slides) > 1) if not (
                source.visual
            ) else None
            # Автоиллюстрация заполняет только область фото выбранного шаблона.
            # Она не меняет композицию и не переводит текст в свободную верстку.
            if template_images_only and (native is None or not (
                native[0].replaceable_images or native[0].layout_images
            )):
                image, has_image = None, False
            if native is not None:
                pattern, blocks = native
                if has_image:
                    slide_images = image if isinstance(image, list) else [image]
                    photo_count = len(pattern.replaceable_images) + len(pattern.layout_images)
                    if len(slide_images) < photo_count:
                        raise ValueError("Для каждой фотообласти слайда нужна отдельная иллюстрация")
                    image_iterator = iter(slide_images)
                    for layer, photos in (("slide", pattern.replaceable_images),
                                          ("layout", pattern.layout_images)):
                        for shape_id, photo_box in photos.items():
                            blocks.append(PlacedBlock(
                                id=f"{source.id}-image-{layer}-{shape_id}", kind="image",
                                image_path=str(next(image_iterator)), image_fit="template", source_layer=layer,
                                source_shape_id=shape_id, box=photo_box.model_copy(),
                                style=pattern.body_style, source_ids=source.source_ids,
                            ))
                for slot in pattern.slots:
                    if slot.role == "page_number":
                        original = slot.text.strip()
                        digits = min(3, len(original)) if original.isdigit() else 1
                        number = f"{index + 1:0{digits}d}"
                        if "/" in original or "из" in original.lower():
                            separator = " из " if "из" in original.lower() else " / "
                            number = f"{index + 1}{separator}{len(story.slides)}"
                        blocks.append(PlacedBlock(
                            id=f"{source.id}-page-{slot.shape_id}", kind="page_number",
                            source_shape_id=slot.shape_id, box=slot.box.model_copy(),
                            style=slot.style.model_copy(), text=number,
                        ))
                bound = {block.source_shape_id for block in blocks}
                slides.append(SlideInstance(
                    id=f"{variant}-{source.id}", story_slide_id=source.id,
                    source_slide_index=pattern.source_slide_index, blocks=blocks,
                    remove_shape_ids=[sid for sid in pattern.mutable_shape_ids if sid not in bound],
                    notes=source.notes,
                ))
                continue
            if not (source.visual or has_image):
                raise ValueError(
                    "В шаблоне нет подходящих текстовых областей для этой истории. "
                    "Добавьте макет с заголовком и основным текстом."
                )
            pattern = _pattern(profile, source, variant, index)
            box = pattern.content_box
            blocks = [
                PlacedBlock(
                    id=f"{source.id}-title",
                    kind="title",
                    box=_title_box(profile, pattern),
                    style=pattern.title_style,
                    text=source.title,
                    source_ids=source.source_ids,
                )
            ]
            title_slot = next((slot for slot in pattern.slots
                               if slot.role == "title" and slot.box == blocks[0].box), None)
            if title_slot is not None:
                blocks[0].source_shape_id = title_slot.shape_id
            gap = max(1, min(int(profile.width * 0.02), box.width // 12, box.height // 12))
            visual_count = int(source.visual is not None) + int(has_image)
            text_box = box
            if visual_count:
                text_box, visual_boxes = _split_visuals(box, visual_count, variant, gap, source, pattern)
                if source.visual:
                    blocks.append(_visual_block(
                        source, pattern, visual_boxes.pop(0), variant, dataset_by_id,
                    ))
                if has_image:
                    blocks.append(
                        PlacedBlock(
                            id=f"{source.id}-image",
                            kind="image",
                            box=visual_boxes[0],
                            style=pattern.body_style,
                            image_path=str(image),
                            source_ids=source.source_ids,
                        )
                    )
            surface = _surface(pattern) if variant == "cards" else None
            if variant == "story":
                blocks.append(
                    PlacedBlock(
                        id=f"{source.id}-body",
                        kind="text",
                        box=text_box,
                        style=pattern.body_style,
                        items=source.paragraphs,
                        source_ids=source.source_ids,
                    )
                )
            elif len(source.paragraphs) == 1:
                if not visual_count:
                    text_box = (
                        _inset(text_box, 0.10, 0.10)
                        if variant == "cards"
                        else Box(
                            left=text_box.left,
                            top=text_box.top + int(text_box.height * 0.06),
                            width=max(1, int(text_box.width * 0.72)),
                            height=max(1, int(text_box.height * 0.88)),
                        )
                    )
                blocks.append(
                    PlacedBlock(
                        id=f"{source.id}-body",
                        kind="text",
                        box=text_box,
                        style=pattern.body_style,
                        text=source.paragraphs[0],
                        fill=surface,
                        source_ids=source.source_ids,
                    )
                )
            else:
                cells = _text_cells(text_box, source.paragraphs, pattern, gap, variant)
                for item_index, (paragraph, cell) in enumerate(zip(source.paragraphs, cells, strict=True)):
                    blocks.append(
                        PlacedBlock(
                            id=f"{source.id}-body-{item_index}", kind="text", box=cell,
                            style=pattern.body_style, text=paragraph, fill=surface,
                            source_ids=source.source_ids,
                        )
                    )
            # План сразу использует читаемый кегль в доступной области; аудит
            # сохраняет предупреждение, если даже нижняя граница не помогает.
            for block in blocks:
                if block.kind not in {"title", "text"}:
                    continue
                block.style = block.style.model_copy()
                minimum = min(
                    block.style.size,
                    max(18, pattern.body_style.size, block.style.size * 0.8)
                    if block.kind == "title"
                    else max(14, block.style.size * 0.8),
                )
                while capacity_risk(block) and block.style.size > minimum:
                    block.style.size = max(minimum, block.style.size - 1)
            for slot in pattern.slots:
                if slot.role == "page_number":
                    original = slot.text.strip()
                    digits = min(3, len(original)) if original.isdigit() else 1
                    number = f"{index + 1:0{digits}d}"
                    if "/" in original or "из" in original.lower():
                        separator = " из " if "из" in original.lower() else " / "
                        number = f"{index + 1}{separator}{len(story.slides)}"
                    blocks.append(
                        PlacedBlock(
                            id=f"{source.id}-page-{slot.shape_id}",
                            kind="page_number",
                            source_shape_id=slot.shape_id,
                            box=slot.box,
                            style=slot.style,
                            text=number,
                        )
                    )
            slides.append(
                SlideInstance(
                    id=f"{variant}-{source.id}",
                    story_slide_id=source.id,
                    source_slide_index=pattern.source_slide_index,
                    blocks=blocks,
                    remove_shape_ids=[sid for sid in [*pattern.mutable_shape_ids,
                        *(pattern.replaceable_images if has_image else [])] if sid not in {
                        block.source_shape_id for block in blocks
                        if block.kind in {"text", "title", "page_number"}
                    }],
                    notes=source.notes,
                )
            )
        results.append(
            DeckPlan(
                variant_id=variant,
                name=name,
                description=description,
                width=profile.width,
                height=profile.height,
                slides=slides,
                datasets=datasets or [],
            )
        )
    return results


def story_layout_issues(profile: TemplateProfile, story: ContentPlan,
                        datasets: list[Dataset] | None = None,
                        *, ignore_cover: bool = False) -> list[str]:
    """Переполнение тела слайда исправляется до генерации изображений и сборки."""
    from exposlides.design_audit import capacity_risk

    try:
        variants = create_variants(profile, story, datasets)
    except ValueError as error:
        return [f"История не помещается в шаблон: {error}"]
    overloaded = dict.fromkeys(
        slide.story_slide_id for plan in variants
        for slide in plan.slides[int(ignore_cover):]
        if any(block.kind == "text" and capacity_risk(block) for block in slide.blocks)
    )
    return [f"{slide_id}: текст не помещается в области шаблона. Перепишите тезисы "
            "короче, уберите повторы, перенесите пояснения в notes; сохраните "
            "числа и обязательные сообщения видимыми. Не добавляйте новые абзацы."
            for slide_id in overloaded]
