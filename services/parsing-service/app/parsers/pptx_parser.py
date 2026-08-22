import asyncio
import uuid
from pathlib import Path

from pptx import Presentation as PPTXPresentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app.models.presentation import (
    BBox,
    ElementType,
    ImageElement,
    LayoutType,
    Paragraph,
    Presentation,
    Run,
    Slide,
    SlideElement,
    TableElement,
    TextElement,
    TextStyle,
)
from app.parsers.base import BaseParser




class PPTXParser(BaseParser):
    """Парсер файлов PowerPoint (.pptx)"""

    @classmethod
    async def parse(cls, file_path: str | Path) -> Presentation:
        """Асинхронно парсит pptx файл в модель Presentation"""
        path = Path(file_path)
        return await asyncio.to_thread(cls._parse_sync, path)

    @classmethod
    def _parse_sync(cls, path: Path) -> Presentation:
        """Синхронно извлекает структуру презентации"""
        prs = PPTXPresentation(str(path))

        slides: list[Slide] = []
        for idx, slide in enumerate(prs.slides, start=1):
            elements: list[SlideElement] = []
            for shape in slide.shapes:
                elem = cls._parse_shape(shape)
                if elem:
                    elements.append(elem)

            slides.append(
                Slide(
                    index=idx,
                    layout_type=cls._classify_layout(slide),
                    layout_name=slide.slide_layout.name if slide.slide_layout else None,
                    elements=elements,
                )
            )

        return Presentation(
            source_path=str(path),
            file_type="pptx",
            slide_width=prs.slide_width,
            slide_height=prs.slide_height,
            slides=slides,
        )

    @classmethod
    def _parse_shape(cls, shape) -> SlideElement | None:
        """Извлекает данные из одной фигуры слайда"""
        bbox = BBox(
            left=shape.left,
            top=shape.top,
            width=shape.width,
            height=shape.height,
        )

        z_order = None
        try:
            z_order = shape._element.order
        except Exception:
            pass

        placeholder_type = None
        if shape.is_placeholder:
            placeholder_type = shape.placeholder_format.type.name

        if shape.has_table:
            table = cls._parse_table(shape.table)
            return SlideElement(
                id=str(uuid.uuid4()),
                type=ElementType.TABLE,
                bbox=bbox,
                z_order=z_order,
                placeholder_type=placeholder_type,
                table=table,
            )

        if shape.has_text_frame:
            text = cls._parse_text_frame(shape.text_frame)
            return SlideElement(
                id=str(uuid.uuid4()),
                type=ElementType.TEXT,
                bbox=bbox,
                z_order=z_order,
                placeholder_type=placeholder_type,
                text=text,
            )

        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            image = ImageElement(
                image_path=str(shape.image.partname) if hasattr(shape, "image") else None,
                content_type=shape.image.content_type if hasattr(shape, "image") else None,
                alt_text=getattr(shape, "alt_text", None),
            )
            return SlideElement(
                id=str(uuid.uuid4()),
                type=ElementType.IMAGE,
                bbox=bbox,
                z_order=z_order,
                placeholder_type=placeholder_type,
                image=image,
            )

        return SlideElement(
            id=str(uuid.uuid4()),
            type=ElementType.OTHER,
            bbox=bbox,
            z_order=z_order,
            placeholder_type=placeholder_type,
        )

    @classmethod
    def _parse_text_frame(cls, text_frame) -> TextElement:
        """Извлекает текст и стили из текстовой рамки"""
        paragraphs: list[Paragraph] = []
        full_text_parts: list[str] = []

        for para in text_frame.paragraphs:
            runs: list[Run] = []
            para_text = ""

            for run in para.runs:
                runs.append(
                    Run(
                        text=run.text,
                        style=cls._extract_style(run.font),
                    )
                )
                para_text += run.text

            paragraph = Paragraph(
                text=para_text,
                level=para.level if para.level is not None else 0,
                bullet=False,
                runs=runs,
            )

            paragraphs.append(paragraph)
            full_text_parts.append(para_text)

        return TextElement(
            paragraphs=paragraphs,
            full_text="\n".join(full_text_parts),
        )

    @classmethod
    def _parse_table(cls, table) -> TableElement:
        """Извлекает данные таблицы"""
        rows = len(table.rows)
        cols = len(table.columns)

        cells: list[list[str]] = []
        for row in table.rows:
            row_cells: list[str] = []
            for cell in row.cells:
                row_cells.append(cell.text)
            cells.append(row_cells)

        return TableElement(rows=rows, cols=cols, cells=cells)

    @classmethod
    def _extract_style(cls, font) -> TextStyle:
        """Извлекает стиль текста из объекта font"""
        color_hex = None
        try:
            if font.color and font.color.rgb:
                color_hex = str(font.color.rgb)
        except Exception:
            pass

        return TextStyle(
            font_name=font.name,
            size_pt=font.size.pt if font.size else None,
            bold=bool(font.bold),
            italic=bool(font.italic),
            underline=bool(font.underline),
            color_hex=color_hex,
        )

    @classmethod
    def _classify_layout(cls, slide) -> LayoutType:
        """Классифицирует макет слайда"""
        return LayoutType.UNKNOWN