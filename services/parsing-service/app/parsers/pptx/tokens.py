from __future__ import annotations

import logging
from typing import Optional

from lxml import etree
from pptx.opc.constants import RELATIONSHIP_TYPE as RT

from app.models.presentation import (
    BBox,
    Component,
    ComponentOccurrence,
    ElementType,
    Grid,
    LayoutInfo,
    LayoutPattern,
    MasterInfo,
    PlaceholderKind,
    Slide,
    SlideElement,
    SlotSignature,
    ThemeInfo,
    TypographyEntry,
    TypographyScale,
)

logger = logging.getLogger(__name__)

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


# ---------- Тема ----------


def extract_theme(prs) -> ThemeInfo | None:
    """Извлекает цвета и шрифты из theme1.xml"""
    try:
        theme_part = _find_theme_part(prs)
        if theme_part is None:
            return None

        theme_element = etree.fromstring(theme_part.blob)
        nsmap = {"a": A_NS}

        colors = _parse_clr_scheme(theme_element, nsmap)
        fonts = _parse_font_scheme(theme_element, nsmap)

        return ThemeInfo(colors=colors, fonts=fonts)
    except Exception:
        logger.debug("Не удалось извлечь тему", exc_info=True)
        return None


def _find_theme_part(prs):
    """Ищет theme part сначала у презентации, потом у мастеров"""
    try:
        return prs.part.part_related_by(RT.THEME)
    except KeyError:
        pass

    for slide_master in prs.slide_masters:
        try:
            return slide_master.part.part_related_by(RT.THEME)
        except KeyError:
            continue
    return None


def _parse_clr_scheme(theme_element, nsmap) -> dict[str, str]:
    """Парсит clrScheme в словарь токен -> HEX"""
    colors: dict[str, str] = {}
    clrScheme = theme_element.find(".//a:clrScheme", namespaces=nsmap)
    if clrScheme is None:
        return colors
    for entry in clrScheme:
        token = etree.QName(entry).localname
        hex_val = _extract_scheme_color(entry, nsmap)
        if hex_val:
            colors[token] = hex_val
    return colors


def _extract_scheme_color(entry, nsmap) -> str | None:
    """Достаёт HEX из srgbClr или sysClr"""
    srgb = entry.find("a:srgbClr", namespaces=nsmap)
    if srgb is not None and srgb.get("val"):
        return srgb.get("val")
    sys_clr = entry.find("a:sysClr", namespaces=nsmap)
    if sys_clr is not None:
        return sys_clr.get("lastClr") or sys_clr.get("val")
    return None


def _parse_font_scheme(theme_element, nsmap) -> dict[str, str]:
    """Парсит fontScheme в словарь major/minor"""
    fonts: dict[str, str] = {}
    fontScheme = theme_element.find(".//a:fontScheme", namespaces=nsmap)
    if fontScheme is None:
        return fonts
    major = fontScheme.find("a:majorFont/a:latin", namespaces=nsmap)
    minor = fontScheme.find("a:minorFont/a:latin", namespaces=nsmap)
    if major is not None and major.get("typeface"):
        fonts["major"] = major.get("typeface")
    if minor is not None and minor.get("typeface"):
        fonts["minor"] = minor.get("typeface")
    return fonts


# ---------- Мастера ----------


def extract_masters(prs, layout_indices_by_partname: dict[str, int]) -> list[MasterInfo]:
    """Собирает информацию о slide masters"""
    masters: list[MasterInfo] = []
    for idx, master in enumerate(prs.slide_masters, start=1):
        layout_indices: list[int] = []
        for layout in master.slide_layouts:
            li = layout_indices_by_partname.get(str(layout.part.partname))
            if li is not None:
                layout_indices.append(li)
        masters.append(
            MasterInfo(
                index=idx,
                name=getattr(master, "name", None),
                layout_indices=layout_indices,
            )
        )
    return masters


# ---------- Паттерны ----------


def compute_patterns(
    layouts: list[LayoutInfo],
    signatures: dict[int, list[PlaceholderKind]],
) -> list[LayoutPattern]:
    """Группирует макеты по сигнатуре placeholder'ов"""
    groups: dict[tuple, list[int]] = {}
    for layout in layouts:
        sig = tuple(sorted(signatures.get(layout.index, []), key=lambda x: x.value))
        groups.setdefault(sig, []).append(layout.index)

    patterns: list[LayoutPattern] = []
    for idx, (sig, layout_indices) in enumerate(groups.items(), start=1):
        slots: list[SlotSignature] = []
        primary = next((l for l in layouts if l.index == layout_indices[0]), None)
        if primary:
            for ph in primary.placeholders:
                slots.append(
                    SlotSignature(
                        kind=ph.kind or PlaceholderKind.OTHER,
                        bbox=ph.bbox,
                        idx=ph.idx,
                    )
                )
        name = "+".join(k.value for k in sig) if sig else "blank"
        patterns.append(
            LayoutPattern(
                id=f"pattern-{idx}",
                name=name,
                layout_indices=layout_indices,
                slots=slots,
            )
        )
    return patterns


def map_layouts_to_patterns(
    layouts: list[LayoutInfo],
    patterns: list[LayoutPattern],
) -> dict[int, str]:
    """Строит отображение layout_index -> pattern_id"""
    mapping: dict[int, str] = {}
    for pattern in patterns:
        for layout_idx in pattern.layout_indices:
            mapping[layout_idx] = pattern.id
    return mapping


# ---------- Компоненты ----------


def compute_components(slides: list[Slide]) -> list[Component]:
    """Находит элементы, повторяющиеся на 2+ слайдах, и делает их компонентами"""
    buckets: dict[str, list[ComponentOccurrence]] = {}
    templates: dict[str, SlideElement] = {}

    for slide in slides:
        for elem in slide.elements:
            sig = element_signature(elem)
            if sig is None:
                continue
            buckets.setdefault(sig, []).append(
                ComponentOccurrence(slide_index=slide.index, element_id=elem.id)
            )
            templates.setdefault(sig, elem)

    components: list[Component] = []
    idx = 0
    for sig, occurrences in buckets.items():
        if len(occurrences) < 2:
            continue
        idx += 1
        components.append(
            Component(
                id=f"component-{idx}",
                signature=sig,
                element_template=templates[sig],
                occurrences=occurrences,
            )
        )
    return components


def element_signature(element: SlideElement) -> str | None:
    """Строит сигнатуру элемента для поиска повторов"""
    if element.type not in (ElementType.SHAPE, ElementType.IMAGE, ElementType.CONNECTOR):
        return None
    parts = [
        element.type.value,
        str(element.bbox.width),
        str(element.bbox.height),
        element.geometry.shape_type if element.geometry else "",
        element.fill.color_hex if element.fill else "",
        element.image.asset_id if element.image else "",
    ]
    return "|".join(parts)


# ---------- Типографика ----------


def build_layout_size_map(
    prs,
    layout_indices_by_partname: dict[str, int],
) -> dict[tuple[int, int], list[float]]:
    """Собирает доступные размеры шрифта из placeholder'ов макетов.

    Ключ: (layout_index, placeholder_idx). Значение: список size_pt.
    Нужна для fallback, когда у run на слайде размер не задан явно.
    """
    result: dict[tuple[int, int], list[float]] = {}
    for idx, layout in enumerate(prs.slide_layouts, start=1):
        for shape in layout.shapes:
            if not shape.is_placeholder:
                continue
            if not getattr(shape, "has_text_frame", False):
                continue
            sizes: list[float] = []
            try:
                for para in shape.text_frame.paragraphs:
                    if para.font and para.font.size:
                        sizes.append(float(para.font.size.pt))
                    for run in para.runs:
                        if run.font and run.font.size:
                            sizes.append(float(run.font.size.pt))
            except Exception:
                continue
            if sizes:
                result[(idx, shape.placeholder_format.idx)] = sizes
    return result


def collect_all_fonts(slides: list[Slide]) -> list[str]:
    """Собирает уникальные имена шрифтов, встречающиеся в runs"""
    fonts: set[str] = set()

    def visit(element: SlideElement) -> None:
        if element.text:
            for p in element.text.paragraphs:
                for r in p.runs:
                    if r.style.font_name:
                        fonts.add(r.style.font_name)
        if element.group:
            for child in element.group.children:
                visit(child)

    for slide in slides:
        for elem in slide.elements:
            visit(elem)
    return sorted(fonts)


def compute_typography(slides: list[Slide]) -> TypographyScale:
    """Собирает все кегли и присваивает роли по ранжированию"""
    sizes: dict[float, int] = {}

    def visit(element: SlideElement) -> None:
        if element.text:
            for p in element.text.paragraphs:
                for r in p.runs:
                    if r.style.size_pt is not None:
                        sizes[r.style.size_pt] = sizes.get(r.style.size_pt, 0) + 1
        if element.group:
            for child in element.group.children:
                visit(child)

    for slide in slides:
        for elem in slide.elements:
            visit(elem)

    if not sizes:
        return TypographyScale()

    sorted_sizes = sorted(sizes.items(), key=lambda x: -x[0])
    most_common = max(sizes.items(), key=lambda x: x[1])[0]

    role_names = [
        "display",
        "title",
        "subtitle",
        "heading",
        "subheading",
        "body",
        "caption",
    ]
    entries: list[TypographyEntry] = []
    for rank, (size, count) in enumerate(sorted_sizes):
        if size == most_common:
            role = "body"
        elif rank < len(role_names):
            role = role_names[rank]
        else:
            role = "small"
        entries.append(
            TypographyEntry(size_pt=size, role=role, occurrences=count)
        )

    return TypographyScale(
        entries=entries,
        min_pt=min(sizes),
        max_pt=max(sizes),
    )


# ---------- Сетка ----------


GRID_STEP_EMU = 45720  # ~0.5 см


def compute_grid(
    layouts: list[LayoutInfo],
    slide_width: int,
    slide_height: int,
) -> Grid:
    """Определяет поля и позиции колонок по placeholder'ам макетов"""
    lefts: list[int] = []
    tops: list[int] = []
    rights: list[int] = []
    bottoms: list[int] = []

    for layout in layouts:
        for ph in layout.placeholders:
            lefts.append(ph.bbox.left)
            tops.append(ph.bbox.top)
            rights.append(ph.bbox.left + ph.bbox.width)
            bottoms.append(ph.bbox.top + ph.bbox.height)

    if not lefts:
        return Grid()

    margin_left = min(lefts)
    margin_top = min(tops)
    margin_right = slide_width - max(rights)
    margin_bottom = slide_height - max(bottoms)

    column_positions = sorted(set(_snap(l) for l in lefts))
    row_positions = sorted(set(_snap(t) for t in tops))

    return Grid(
        margin_left=margin_left if margin_left >= 0 else None,
        margin_right=margin_right if margin_right >= 0 else None,
        margin_top=margin_top if margin_top >= 0 else None,
        margin_bottom=margin_bottom if margin_bottom >= 0 else None,
        column_positions=column_positions,
        row_positions=row_positions,
    )


def _snap(value: int) -> int:
    """Округляет координату до сетки GRID_STEP_EMU"""
    return round(value / GRID_STEP_EMU) * GRID_STEP_EMU