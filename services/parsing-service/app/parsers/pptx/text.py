from __future__ import annotations

import logging

from pptx.enum.dml import MSO_COLOR_TYPE
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn

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

logger = logging.getLogger(__name__)


def parse_text_frame(
    text_frame,
    placeholder_kind: PlaceholderKind | None,
    theme: ThemeInfo | None,
) -> TextElement:
    """Извлекает параграфы и runs с индивидуальными стилями"""
    paragraphs: list[Paragraph] = []

    for para in text_frame.paragraphs:
        runs: list[Run] = []
        for run in para.runs:
            runs.append(
                Run(
                    text=run.text,
                    style=extract_style(run.font, para, placeholder_kind, theme),
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
) -> TextStyle:
    """Извлекает стиль текста с учётом темы и токенов"""
    font_name, _ = resolve_font(font, placeholder_kind, theme)
    color_hex, color_token = resolve_color(font, theme)

    size_pt = font.size.pt if font.size else None

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
        bold=bool(font.bold),
        italic=bool(font.italic),
        underline=bool(font.underline),
        color_hex=color_hex,
        color_token=color_token,
        alignment=alignment,
        line_spacing=line_spacing,
    )


def resolve_font(
    font,
    placeholder_kind: PlaceholderKind | None,
    theme: ThemeInfo | None,
) -> tuple[str | None, str | None]:
    """Разрешает шрифт: возвращает имя и токен (+mj-lt / +mn-lt)"""
    name = font.name

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