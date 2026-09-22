from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path

from pptx import Presentation as PPTXPresentation

from app.models.presentation import (
    AssetRef,
    BBox,
    BackgroundKind,
    DesignTokens,
    ElementType,
    Fill,
    FillType,
    LayoutInfo,
    PlaceholderInfo,
    Presentation,
    Slide,
    SlideBackground,
    SlideElement,
)
from app.parsers.base import BaseParser
from app.parsers.pptx import shapes as shapes_module
from app.parsers.pptx import tokens as tokens_module
from app.parsers.pptx.assets import AssetBlob
from app.parsers.pptx.helpers import (
    classify_layout,
    classify_layout_by_name,
    content_hash,
    map_placeholder_kind,
    normalize_placeholder_idx,
)

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    """Результат парсинга: модель + бинарные ассеты"""

    presentation: Presentation
    assets: dict[str, AssetBlob] = field(default_factory=dict)


class PPTXParser(BaseParser):
    """Парсер файлов PowerPoint (.pptx)"""

    @classmethod
    async def parse(cls, file_path: str | Path) -> ParseResult:
        """Асинхронно парсит pptx в Presentation + ассеты"""
        path = Path(file_path)
        return await asyncio.to_thread(cls._parse_sync, path)

    @classmethod
    def _parse_sync(cls, path: Path) -> ParseResult:
        """Синхронно извлекает структуру, токены и ассеты"""
        prs = PPTXPresentation(str(path))
        assets: dict[str, AssetBlob] = {}

        theme = tokens_module.extract_theme(prs)

        layouts: list[LayoutInfo] = []
        layout_indices_by_partname: dict[str, int] = {}
        layout_kind_signatures: dict[int, list] = {}
        for idx, layout in enumerate(prs.slide_layouts, start=1):
            layout_indices_by_partname[str(layout.part.partname)] = idx
            parsed = cls._parse_layout(layout, idx, theme, assets)
            layouts.append(parsed)
            layout_kind_signatures[idx] = [
                ph.kind for ph in parsed.placeholders if ph.kind
            ]

        layout_size_map = tokens_module.build_layout_size_map(
            prs, layout_indices_by_partname
        )

        masters = tokens_module.extract_masters(prs, layout_indices_by_partname)
        patterns = tokens_module.compute_patterns(layouts, layout_kind_signatures)
        pattern_by_layout = tokens_module.map_layouts_to_patterns(layouts, patterns)

        slides: list[Slide] = []
        for idx, slide in enumerate(prs.slides, start=1):
            parsed_slide = cls._parse_slide(
                slide,
                idx,
                theme,
                layout_indices_by_partname,
                pattern_by_layout,
                assets,
            )
            cls._apply_layout_sizes(parsed_slide, layout_size_map)
            cls._mark_hidden_and_background(
                parsed_slide, prs.slide_width, prs.slide_height
            )
            parsed_slide.content_hash = content_hash(parsed_slide)
            slides.append(parsed_slide)

        if theme is not None:
            theme.all_fonts = tokens_module.collect_all_fonts(slides)

        components = tokens_module.compute_components(slides)
        typography = tokens_module.compute_typography(slides)
        grid = tokens_module.compute_grid(layouts, prs.slide_width, prs.slide_height)

        asset_refs = [
            AssetRef(
                asset_id=blob.asset_id,
                content_type=blob.content_type,
                size_bytes=len(blob.data),
                original_name=blob.original_name,
            )
            for blob in assets.values()
        ]

        presentation = Presentation(
            source_path=str(path),
            file_type="pptx",
            slide_width=prs.slide_width,
            slide_height=prs.slide_height,
            tokens=DesignTokens(theme=theme, typography=typography, grid=grid),
            patterns=patterns,
            components=components,
            masters=masters,
            slides=slides,
            layouts=layouts,
            assets=asset_refs,
        )
        return ParseResult(presentation=presentation, assets=assets)

    @classmethod
    def _parse_slide(
        cls,
        slide,
        index: int,
        theme,
        layout_indices_by_partname: dict[str, int],
        pattern_by_layout: dict[int, str],
        assets: dict[str, AssetBlob],
    ) -> Slide:
        """Извлекает данные одного слайда (без content_hash — он ставится позже)"""
        elements = []
        for shape in slide.shapes:
            element_id = f"slide-{index}-shape-{shape.shape_id}"
            elem = shapes_module.parse_shape(shape, theme, element_id, assets)
            if elem:
                elements.append(elem)

        layout_index = None
        if slide.slide_layout:
            layout_partname = str(slide.slide_layout.part.partname)
            layout_index = layout_indices_by_partname.get(layout_partname)

        pattern_id = pattern_by_layout.get(layout_index) if layout_index else None
        background = shapes_module.parse_background(slide.background, theme, assets)

        notes = None
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            raw_notes = slide.notes_slide.notes_text_frame.text
            if raw_notes and raw_notes.strip():
                notes = raw_notes

        return Slide(
            index=index,
            layout_type=classify_layout(slide),
            layout_name=slide.slide_layout.name if slide.slide_layout else None,
            layout_index=layout_index,
            pattern_id=pattern_id,
            elements=elements,
            background=background,
            notes=notes,
        )

    @classmethod
    def _apply_layout_sizes(
        cls,
        slide: Slide,
        layout_size_map: dict[tuple[int, int], list[float]],
    ) -> None:
        """Подставляет размеры шрифта из макета, где у run он не задан"""
        if slide.layout_index is None:
            return

        def visit(element: SlideElement) -> None:
            if element.text and element.placeholder_idx is not None:
                candidates = layout_size_map.get(
                    (slide.layout_index, element.placeholder_idx)
                )
                if candidates:
                    fallback = candidates[0]
                    for p in element.text.paragraphs:
                        for r in p.runs:
                            if r.style.size_pt is None:
                                r.style.size_pt = fallback
            if element.group:
                for child in element.group.children:
                    visit(child)

        for elem in slide.elements:
            visit(elem)

    @classmethod
    def _mark_hidden_and_background(
        cls,
        slide: Slide,
        slide_width: int,
        slide_height: int,
    ) -> None:
        """Помечает элементы, скрытые за пределами слайда, и фоновые картинки"""
        slide_area = slide_width * slide_height

        for element in slide.elements:
            bb = element.bbox
            if (
                bb.left + bb.width < 0
                or bb.top + bb.height < 0
                or bb.left > slide_width
                or bb.top > slide_height
            ):
                element.hidden = True

            if element.type == ElementType.IMAGE and element.image is not None:
                area = bb.width * bb.height
                if slide_area > 0 and area >= 0.9 * slide_area:
                    element.is_background = True

        background_elements = [
            e for e in slide.elements if e.is_background and e.image is not None
        ]
        if not background_elements:
            return

        first_bg = min(
            background_elements,
            key=lambda e: e.z_order if e.z_order is not None else 10**9,
        )

        current_fill_type = None
        if slide.background is not None and slide.background.fill is not None:
            current_fill_type = slide.background.fill.type

        if current_fill_type is None or current_fill_type == FillType.NONE:
            slide.background = SlideBackground(
                kind=BackgroundKind.UNKNOWN,
                fill=Fill(
                    type=FillType.PICTURE,
                    picture_asset_id=first_bg.image.asset_id,
                ),
            )

    @classmethod
    def _parse_layout(
        cls,
        layout,
        index: int,
        theme,
        assets: dict[str, AssetBlob],
    ) -> LayoutInfo:
        """Извлекает макет: placeholder'ы и фон, без полного дерева элементов"""
        placeholders: list[PlaceholderInfo] = []

        for shape in layout.shapes:
            if not shape.is_placeholder:
                continue
            try:
                bbox = BBox(
                    left=shape.left,
                    top=shape.top,
                    width=shape.width,
                    height=shape.height,
                )
                placeholders.append(
                    PlaceholderInfo(
                        kind=map_placeholder_kind(shape.placeholder_format.type),
                        name=shape.name,
                        idx=normalize_placeholder_idx(shape.placeholder_format.idx),
                        bbox=bbox,
                    )
                )
            except Exception:
                logger.debug(
                    "Не удалось разобрать placeholder макета %s",
                    index,
                    exc_info=True,
                )

        background = shapes_module.parse_background(layout.background, theme, assets)

        return LayoutInfo(
            name=layout.name,
            index=index,
            layout_type=classify_layout_by_name((layout.name or "").lower()),
            placeholders=placeholders,
            background=background,
        )