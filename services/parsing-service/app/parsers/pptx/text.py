from __future__ import annotations

import logging

from app.models.presentation import (
    Alignment,
    Paragraph,
    PlaceholderKind,
    Run,
    TextElement,
    TextStyle,
    ThemeInfo,
)
from app.parsers.pptx.helpers import theme_color_to_token
from app.parsers.text_style import inherited_font, inherited_run_properties

from pptx.enum.dml import MSO_COLOR_TYPE
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.shapes.base import BaseShape
from pptx.slide import Slide, SlideLayout

logger = logging.getLogger(__name__)


def parse_text_frame(
    text_frame,
    placeholder_kind: PlaceholderKind | None,
    theme: ThemeInfo | None,
    *,
    shape: BaseShape | None = None,
    owner: Slide | SlideLayout | None = None,
) -> TextElement | None:
    """Извлекает параграфы и runs с индивидуальными стилями"""
    paragraphs: list[Paragraph] = []

    for para in text_frame.paragraphs:
        inherited_size = None
        inherited_name = None
        inherited_properties = ()
        if shape is not None and owner is not None:
            inherited_size, inherited_name = inherited_font(shape, para, owner)
            inherited_properties = tuple(inherited_run_properties(shape, para, owner))
        runs: list[Run] = []
        for run in para.runs:
            runs.append(
                Run(
                    text=run.text,
                    style=extract_style(
                        run.font, para, placeholder_kind, theme, inherited_size, inherited_name,
                        inherited_properties,
                    ),
                    hyperlink=extract_hyperlink(run),
                )
            )

        if not runs:
            continue

        bullet, bullet_char = parse_bullet(para)
        paragraphs.append(
            Paragraph(
                level=para.level if para.level is not None else 0,
                bullet=bullet,
                bullet_char=bullet_char,
                runs=runs,
            )
        )

    if not paragraphs:
        return None
    return TextElement(paragraphs=paragraphs)


def parse_bullet(para) -> tuple[bool, str | None]:
    """Определяет наличие маркера и его символ"""
    pPr = para._p.find(qn("a:pPr"))
    if pPr is None:
        return False, None
    buChar = pPr.find(qn("a:buChar"))
    if buChar is not None:
        return True, buChar.get("char")
    buAutoNum = pPr.find(qn("a:buAutoNum"))
    if buAutoNum is not None:
        return True, buAutoNum.get("type")
    return False, None


def extract_hyperlink(run) -> str | None:
    """Возвращает адрес гиперссылки, если она есть"""
    try:
        if run.hyperlink and run.hyperlink.address:
            return run.hyperlink.address
    except Exception:
        pass
    return None


def extract_style(
    font,
    paragraph,
    placeholder_kind: PlaceholderKind | None,
    theme: ThemeInfo | None,
    inherited_size: float | None = None,
    inherited_name: str | None = None,
    inherited_properties: tuple = (),
) -> TextStyle:
    """Извлекает стиль текста с учётом темы и токенов"""
    font_name, _ = resolve_font(font, placeholder_kind, theme, inherited_name)
    color_hex, color_token = resolve_color(font, theme)
    inherited_flags = {}
    for properties in inherited_properties:
        for key in ("b", "i", "u"):
            if key not in inherited_flags and properties.get(key) is not None:
                inherited_flags[key] = properties.get(key)
        if color_hex is None:
            fill = properties.find(qn("a:solidFill"))
            if fill is not None:
                rgb = fill.find(qn("a:srgbClr"))
                scheme = fill.find(qn("a:schemeClr"))
                if rgb is not None:
                    color_hex = rgb.get("val")
                elif scheme is not None:
                    color_token = scheme.get("val")
                    color_token = {"tx1": "dk1", "tx2": "dk2", "bg1": "lt1", "bg2": "lt2"}.get(color_token, color_token)
                    color_hex = theme.colors.get(color_token) if theme else None

    size_pt = font.size.pt if font.size else inherited_size

    alignment = None
    if paragraph.alignment is not None:
        alignment_map = {
            PP_ALIGN.LEFT: Alignment.LEFT,
            PP_ALIGN.CENTER: Alignment.CENTER,
            PP_ALIGN.RIGHT: Alignment.RIGHT,
            PP_ALIGN.JUSTIFY: Alignment.JUSTIFY,
        }
        alignment = alignment_map.get(paragraph.alignment)

    line_spacing = paragraph.line_spacing if paragraph.line_spacing else None

    return TextStyle(
        font_name=font_name,
        size_pt=size_pt,
        bold=bool(font.bold) if font.bold is not None else inherited_flags.get("b") in {"1", "true"},
        italic=bool(font.italic) if font.italic is not None else inherited_flags.get("i") in {"1", "true"},
        underline=bool(font.underline) if font.underline is not None else inherited_flags.get("u", "none") != "none",
        color_hex=color_hex,
        color_token=color_token,
        alignment=alignment,
        line_spacing=line_spacing,
    )


def resolve_font(
    font,
    placeholder_kind: PlaceholderKind | None,
    theme: ThemeInfo | None,
    inherited_name: str | None = None,
) -> tuple[str | None, str | None]:
    """Разрешает шрифт: возвращает имя и токен (+mj-lt / +mn-lt)"""
    name = font.name or inherited_name

    if name is None:
        if theme is None:
            return None, None
        if placeholder_kind in (
            PlaceholderKind.TITLE,
            PlaceholderKind.SUBTITLE,
            PlaceholderKind.SECTION_HEADER,
        ):
            return theme.fonts.get("major"), "+mj-lt"
        return theme.fonts.get("minor"), "+mn-lt"

    if name.startswith("+mj"):
        return (theme.fonts.get("major") if theme else name), "+mj-lt"
    if name.startswith("+mn"):
        return (theme.fonts.get("minor") if theme else name), "+mn-lt"

    return name, None


def resolve_color(
    font,
    theme: ThemeInfo | None,
) -> tuple[str | None, str | None]:
    """Разрешает цвет в HEX и токен темы"""
    try:
        if font.color is None:
            return None, None
        if font.color.type == MSO_COLOR_TYPE.RGB:
            return str(font.color.rgb), None
        if font.color.type == MSO_COLOR_TYPE.SCHEME:
            theme_color = font.color.theme_color
            if theme_color is None:
                return None, None
            token = theme_color_to_token(theme_color)
            hex_val = theme.colors.get(token) if theme else None
            return hex_val, token
    except Exception:
        logger.debug("Не удалось извлечь цвет текста", exc_info=True)
    return None, None


def default_style(shape, theme, placeholder_kind, owner=None) -> TextStyle:
    """Сохраняет наследуемую типографику даже пустого текстового placeholder."""
    paragraph = shape.text_frame.paragraphs[0]
    size, name = (inherited_font(shape, paragraph, owner) if owner is not None else (None, None))
    properties = tuple(inherited_run_properties(shape, paragraph, owner)) if owner is not None else ()
    return extract_style(paragraph.font, paragraph, placeholder_kind, theme, size, name, properties)
