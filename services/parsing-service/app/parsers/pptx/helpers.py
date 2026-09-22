from __future__ import annotations

import hashlib
import logging

from app.models.presentation import (
    LayoutType,
    PlaceholderKind,
    Slide,
    SlideElement,
)

logger = logging.getLogger(__name__)


def get_z_order(shape, element_id: str) -> int | None:
    """Возвращает индекс элемента среди соседей в родителе"""
    try:
        parent = shape._element.getparent()
        if parent is not None:
            return list(parent).index(shape._element)
    except Exception:
        logger.debug("Не удалось определить z-order %s", element_id, exc_info=True)
    return None


def get_rotation(shape) -> float | None:
    """Возвращает угол поворота фигуры, если он задан"""
    try:
        rot = shape.rotation
        return float(rot) if rot else None
    except Exception:
        return None


def map_placeholder_kind(placeholder_type) -> PlaceholderKind:
    """Приводит enum placeholder'а python-pptx к PlaceholderKind"""
    if placeholder_type is None:
        return PlaceholderKind.OTHER
    name = placeholder_type.name if hasattr(placeholder_type, "name") else str(placeholder_type)
    mapping = {
        "TITLE": PlaceholderKind.TITLE,
        "CENTER_TITLE": PlaceholderKind.TITLE,
        "SUBTITLE": PlaceholderKind.SUBTITLE,
        "BODY": PlaceholderKind.BODY,
        "OBJECT": PlaceholderKind.CONTENT,
        "CONTENT": PlaceholderKind.CONTENT,
        "PICTURE": PlaceholderKind.PICTURE,
        "TABLE": PlaceholderKind.TABLE,
        "CHART": PlaceholderKind.CHART,
        "DATE": PlaceholderKind.DATE,
        "FOOTER": PlaceholderKind.FOOTER,
        "SLIDE_NUMBER": PlaceholderKind.SLIDE_NUMBER,
        "SECTION_HEADER": PlaceholderKind.SECTION_HEADER,
    }
    return mapping.get(name, PlaceholderKind.OTHER)


def classify_layout(slide) -> LayoutType:
    """Классифицирует макет слайда по имени"""
    name = (slide.slide_layout.name if slide.slide_layout else "") or ""
    return classify_layout_by_name(name.lower())


def classify_layout_by_name(name: str) -> LayoutType:
    """Классифицирует макет по имени (англ. и рус.)"""
    if not name:
        return LayoutType.UNKNOWN

    # английские названия (Office Windows / Mac)
    if "title slide" in name:
        return LayoutType.TITLE
    if "section header" in name or "section break" in name:
        return LayoutType.SECTION_HEADER
    if "two content" in name or "comparison" in name:
        return LayoutType.TWO_CONTENT
    if "picture with caption" in name or "content with caption" in name:
        return LayoutType.IMAGE_TEXT
    if "title and content" in name:
        return LayoutType.BULLETS
    if "title only" in name:
        return LayoutType.TITLE
    if "blank" in name:
        return LayoutType.UNKNOWN
    if "thank you" in name:
        return LayoutType.THANK_YOU
    if "table" in name:
        return LayoutType.TABLE

    # русские названия
    if "титульный" in name:
        return LayoutType.TITLE
    if "заголовок раздела" in name:
        return LayoutType.SECTION_HEADER
    if "два объекта" in name or "сравнение" in name:
        return LayoutType.TWO_CONTENT
    if "рисунок с подписью" in name or "объект с подписью" in name:
        return LayoutType.IMAGE_TEXT
    if "заголовок и объект" in name or "заголовок и содержимое" in name:
        return LayoutType.BULLETS
    if "только заголовок" in name:
        return LayoutType.TITLE
    if (
        "заголовок и вертикальный текст" in name
        or "вертикальный заголовок и текст" in name
    ):
        return LayoutType.BULLETS
    if "пустой слайд" in name:
        return LayoutType.UNKNOWN

    return LayoutType.UNKNOWN


def theme_color_to_token(theme_color) -> str:
    """Преобразует MSO_THEME_COLOR в имя токена темы (dk1, accent1, ...)"""
    name = theme_color.name.lower()
    mapping = {
        "dark_1": "dk1",
        "light_1": "lt1",
        "dark_2": "dk2",
        "light_2": "lt2",
        "accent_1": "accent1",
        "accent_2": "accent2",
        "accent_3": "accent3",
        "accent_4": "accent4",
        "accent_5": "accent5",
        "accent_6": "accent6",
        "hyperlink": "hlink",
        "followed_hyperlink": "folHlink",
        "text_1": "tx1",
        "text_2": "tx2",
        "background_1": "bg1",
        "background_2": "bg2",
    }
    return mapping.get(name, name)


def content_hash(slide: Slide) -> str:
    """Стабильный хеш содержимого слайда для поиска дублей"""
    parts: list[str] = []
    for elem in slide.elements:
        _collect_element_parts(elem, parts)
    raw = "||".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _collect_element_parts(element: SlideElement, parts: list[str]) -> None:
    """Рекурсивно собирает строковые маркеры элемента в аккумулятор"""
    parts.append(f"{element.type.value}:{element.bbox.left}:{element.bbox.top}")
    if element.text:
        for p in element.text.paragraphs:
            for r in p.runs:
                parts.append(r.text)
    if element.image and element.image.asset_id:
        parts.append(element.image.asset_id)
    if element.group:
        for child in element.group.children:
            _collect_element_parts(child, parts)


PLACEHOLDER_IDX_INVALID = 4294967295


def normalize_placeholder_idx(idx: int | None) -> int | None:
    """Убирает мусорный placeholder_idx (0xFFFFFFFF)"""
    if idx is None:
        return None
    if idx == PLACEHOLDER_IDX_INVALID or idx < 0:
        return None
    return idx