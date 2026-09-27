"""Профиль дизайна: редактируемые слоты, наследуемые стили и защищённые области."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

from exposlides.design_geometry import clip, free_box
from exposlides.design_models import Box, SlidePattern, Slot, TemplateProfile, TextStyle

PROTECTED_NAME = re.compile(r"logo|copyright|footer|attribution|логотип|колонтитул", re.I)
PAGE_NUMBER = re.compile(r"^\s*\d{1,3}\s*(?:(?:/|из)\s*\d{1,3})?\s*$")
HEX = re.compile(r"[a-fA-F0-9]{6}")
TEXT_KINDS = {
    "title",
    "center_title",
    "subtitle",
    "body",
    "object",
    "content",
    "footer",
    "header",
    "date",
    "slide_number",
    "section_header",
}


def elements(items: list[dict]) -> Iterator[dict]:
    for element in items:
        if element.get("group"):
            yield from elements(element["group"].get("children", []))
        else:
            yield element


def plain_text(element: dict) -> str:
    text = element.get("text") or {}
    if isinstance(text.get("full_text"), str):
        return text["full_text"].strip()
    return "\n".join(
        "".join(run.get("text", "") for run in paragraph.get("runs", []))
        if paragraph.get("runs")
        else paragraph.get("text", "")
        for paragraph in text.get("paragraphs", [])
    ).strip()


def _hex(value: Any) -> str | None:
    return value.upper() if isinstance(value, str) and HEX.fullmatch(value) else None


def _style(element: dict, theme: dict, fallback_size: float) -> TextStyle:
    candidates = [
        (run.get("style") or {}, max(1, len(run.get("text", ""))))
        for paragraph in (element.get("text") or {}).get("paragraphs", [])
        for run in paragraph.get("runs", [])
    ]
    if candidates:
        weights = Counter()
        sources = {}
        for style, weight in candidates:
            key = (
                style.get("font_name"),
                style.get("size_pt"),
                style.get("color_hex"),
                style.get("color_token"),
                bool(style.get("bold")),
            )
            weights[key] += weight
            sources[key] = style
        style = sources[weights.most_common(1)[0][0]]
    else:
        style = element.get("default_text_style") or {}
    color = _hex(style.get("color_hex")) or _hex(
        theme.get("colors", {}).get(style.get("color_token"))
    )
    color = color or _hex(theme.get("colors", {}).get("dk1")) or "202124"
    title = (
        "title"
        in str(element.get("placeholder_kind") or element.get("placeholder_type") or "").lower()
    )
    font = (
        style.get("font_name")
        or theme.get("fonts", {}).get("major" if title else "minor")
        or "Arial"
    )
    if font.startswith("+mj"):
        font = theme.get("fonts", {}).get("major") or "Arial"
    elif font.startswith("+mn"):
        font = theme.get("fonts", {}).get("minor") or "Arial"
    size = style.get("size_pt")
    if not isinstance(size, (int, float)) or not math.isfinite(size) or size <= 0:
        size = fallback_size
    return TextStyle(
        font=font, size=max(6, min(160, size)), color=color, bold=bool(style.get("bold", False))
    )


def _box(element: dict) -> Box | None:
    data = element.get("slide_bbox") or element.get("bbox")
    if not data or data.get("width", 0) <= 0 or data.get("height", 0) <= 0:
        return None
    return Box.model_validate(data)


def _shape_id(element: dict) -> int:
    if element.get("shape_id") is not None:
        return element["shape_id"]
    if "-child-" in element.get("id", ""):
        raise ValueError("Для безопасной замены текста группы нужен shape_id; обновите parser JSON")
    match = re.search(r"shape-(\d+)$", element.get("id", ""))
    if not match:
        raise ValueError("У элемента шаблона отсутствует стабильный shape_id")
    return int(match[1])


def _text_candidate(element: dict) -> bool:
    kind = str(element.get("placeholder_kind") or element.get("placeholder_type") or "").lower()
    return bool(element.get("text") or kind in TEXT_KINDS or element.get("type") == "text")


def _palette(theme: dict, source_elements: list[dict], slide: dict) -> list[str]:
    # Реально использованные цвета важнее неиспользуемой палитры темы.
    values = [((slide.get("background") or {}).get("fill") or {}).get("color_hex")]
    for element in source_elements:
        values.extend(
            (element.get(key) or {}).get("color_hex")
            for key in ("fill", "line", "default_text_style")
        )
        values.extend(
            run.get("style", {}).get("color_hex")
            for paragraph in (element.get("text") or {}).get("paragraphs", [])
            for run in paragraph.get("runs", [])
        )
    colors = theme.get("colors", {})
    values.extend(colors.get(f"accent{index}") for index in range(1, 7))
    values.extend(value for key, value in colors.items() if key not in {"hlink", "folHlink"})
    values.extend(colors.get(key) for key in ("hlink", "folHlink"))
    return list(dict.fromkeys(color for value in values if (color := _hex(value))))


def profile_from_json(data: dict[str, Any], template: Path) -> TemplateProfile:
    """Выделить слоты и найти свободную область, сохранив декор и повторяемые подписи."""
    version = str(data.get("schema_version", "1"))
    if version.split(".")[0] not in {"1", "2"}:
        raise ValueError(f"Неподдерживаемая версия Presentation JSON: {version}")
    width, height = int(data["slide_width"]), int(data["slide_height"])
    if width <= 0 or height <= 0:
        raise ValueError("Размер слайда должен быть положительным")
    slides = data.get("slides", [])
    frequencies = Counter(
        text
        for slide in slides
        for text in {plain_text(e) for e in elements(slide.get("elements", []))}
        if text
    )
    global_theme = (data.get("tokens") or {}).get("theme") or data.get("theme") or {}
    patterns, warnings = [], []
    for slide in slides:
        theme = slide.get("theme") or global_theme
        source_elements = list(elements(slide.get("elements", [])))
        layout = next(
            (
                layout
                for layout in data.get("layouts", [])
                if layout.get("index") == slide.get("layout_index")
            ),
            {},
        )
        master = next(
            (
                master
                for master in data.get("masters", [])
                if master.get("index") == (slide.get("master_index") or layout.get("master_index"))
            ),
            {},
        )
        inherited = [
            element
            for element in elements([*layout.get("elements", []), *master.get("elements", [])])
            if not element.get("placeholder_kind") and not element.get("placeholder_type")
        ]
        palette = _palette(theme, [*source_elements, *inherited], slide)
        slots, protected, mutable, regions = [], [], [], []
        visuals: dict[str, list[int]] = {}
        text_boxes = [
            box
            for element in source_elements
            if _text_candidate(element)
            and not element.get("hidden")
            and (box := _box(element)) is not None
        ]
        for element in source_elements:
            box = _box(element)
            if box is None or element.get("hidden"):
                continue
            shape_id = _shape_id(element)
            text = plain_text(element)
            name = element.get("shape_name") or element.get("placeholder_name") or ""
            kind = str(
                element.get("placeholder_kind") or element.get("placeholder_type") or ""
            ).lower()
            if not _text_candidate(element):
                if element.get("type") in {"chart", "table", "smartart"}:
                    mutable.append(shape_id)
                    visuals.setdefault(element["type"], []).append(shape_id)
                else:
                    protected.append(shape_id)
                    # Подложка текста сохраняется, но не исключает занимаемый ею контент.
                    container = element.get("type") == "shape" and any(
                        box.left <= text_box.left
                        and box.top <= text_box.top
                        and box.left + box.width >= text_box.left + text_box.width
                        and box.top + box.height >= text_box.top + text_box.height
                        for text_box in text_boxes
                    )
                    background = (
                        element.get("is_background")
                        or box.width * box.height >= width * height * 0.9
                    )
                    if not container and not background:
                        regions.append(box)
                continue
            small_edge = box.top > height * 0.84 or (
                box.top < height * 0.08 and box.height < height * 0.07
            )
            if "slide_number" in kind or (box.top > height * 0.9 and PAGE_NUMBER.fullmatch(text)):
                role = "page_number"
            elif (
                PROTECTED_NAME.search(name)
                or kind in {"footer", "header", "date"}
                or (small_edge and text and frequencies[text] >= max(2, len(slides) * 0.6))
            ):
                role = "protected"
            elif ("title" in kind and "subtitle" not in kind) or kind == "section_header":
                role = "title"
            else:
                role = "body"
            slot = Slot(
                element_id=element["id"],
                shape_id=shape_id,
                box=box,
                role=role,
                text=text,
                style=_style(element, theme, 30 if role == "title" else 20),
            )
            slots.append(slot)
            if role == "protected":
                protected.append(shape_id)
                regions.append(box)
            else:
                mutable.append(shape_id)
        # Фигуры master/layout не имеют ID в дереве слайда: защищаем их
        # геометрию, но никогда не добавляем их IDs к удаляемым фигурам.
        for element in inherited:
            box = _box(element)
            if box is None or element.get("hidden") or element.get("is_background"):
                continue
            container = (
                element.get("type") == "shape"
                and not plain_text(element)
                and any(
                    box.left <= text_box.left
                    and box.top <= text_box.top
                    and box.left + box.width >= text_box.left + text_box.width
                    and box.top + box.height >= text_box.top + text_box.height
                    for text_box in text_boxes
                )
            )
            if not container and box.width * box.height < width * height * 0.9:
                regions.append(box)
        if not any(slot.role in {"title", "body"} for slot in slots) and not visuals:
            continue
        if not any(slot.role == "title" for slot in slots):
            candidates = [
                slot for slot in slots if slot.role == "body" and slot.box.top < height * 0.4
            ]
            if candidates:
                min(candidates, key=lambda slot: (slot.box.top, -slot.style.size)).role = "title"
        titles = [slot for slot in slots if slot.role == "title"]
        bodies = [slot for slot in slots if slot.role == "body"]
        title_style = (
            titles[0].style if titles else _style({"placeholder_kind": "title"}, theme, 30)
        )
        body_style = (
            max(bodies, key=lambda slot: slot.box.width * slot.box.height).style
            if bodies
            else _style({}, theme, 20)
        )
        if bodies:
            left, top = min(slot.box.left for slot in bodies), min(slot.box.top for slot in bodies)
            right = max(slot.box.left + slot.box.width for slot in bodies)
            bottom = max(slot.box.top + slot.box.height for slot in bodies)
        else:
            left, right = int(width * 0.07), int(width * 0.93)
            top = max(
                [slot.box.top + slot.box.height for slot in titles] or [int(height * 0.16)]
            ) + int(height * 0.04)
            bottom = int(height * 0.88)
        if right <= left or bottom <= top:
            warnings.append(f"Образец {slide['index']}: нет области для основного содержания")
            continue
        bounds = clip(
            Box(left=left, top=top, width=right - left, height=bottom - top), width, height
        )
        obstacles = [
            *regions,
            *[slot.box for slot in slots if slot.role in {"title", "page_number"}],
        ]
        content = free_box(bounds, obstacles) if bounds else None
        if content is None or content.width < width * 0.12 or content.height < height * 0.08:
            warnings.append(f"Образец {slide['index']}: защищённые элементы перекрывают содержание")
            continue
        palette = list(dict.fromkeys([*palette, title_style.color, body_style.color]))
        patterns.append(
            SlidePattern(
                source_slide_index=slide["index"],
                layout_index=slide.get("layout_index"),
                name=slide.get("layout_name") or f"Образец {slide['index']}",
                slots=slots,
                content_box=content,
                palette=palette,
                font=body_style.font,
                title_style=title_style,
                body_style=body_style,
                visual_shape_ids=visuals,
                protected_shape_ids=sorted(set(protected)),
                mutable_shape_ids=sorted(set(mutable)),
                protected_regions=regions,
            )
        )
    if not patterns:
        raise ValueError("В шаблоне не найдено безопасной области для редактируемого содержания")
    return TemplateProfile(
        template_sha256=hashlib.sha256(template.read_bytes()).hexdigest(),
        width=width,
        height=height,
        patterns=patterns,
        warnings=warnings,
    )
