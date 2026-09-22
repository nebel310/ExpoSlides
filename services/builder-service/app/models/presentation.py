from typing import Literal, Optional, Self

from pydantic import BaseModel, Field, field_validator, model_validator

PLACEHOLDER_TYPES = {
    "title": "TITLE",
    "subtitle": "SUBTITLE",
    "body": "BODY",
    "content": "OBJECT",
    "picture": "PICTURE",
    "table": "TABLE",
    "chart": "CHART",
    "date": "DATE",
    "footer": "FOOTER",
    "slide_number": "SLIDE_NUMBER",
    "section_header": "TITLE",
    "other": "OTHER",
}


class BBox(BaseModel):
    """Координаты и размеры элемента"""
    left: int
    top: int
    width: int
    height: int


class TextStyle(BaseModel):
    """Стиль текстового фрагмента"""
    font_name: Optional[str] = None
    size_pt: Optional[float] = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color_hex: Optional[str] = None
    alignment: Optional[str] = None
    line_spacing: Optional[float] = None


class Run(BaseModel):
    """Текстовый фрагмент с индивидуальным стилем"""
    text: str
    style: TextStyle


class Paragraph(BaseModel):
    """Абзац текста"""
    text: str = ""
    level: int = 0
    bullet: bool = False
    runs: list[Run] = Field(default_factory=list)

    @model_validator(mode="after")
    def restore_text(self) -> Self:
        """В контракте v2 текст абзаца хранится только в runs."""
        if "text" not in self.model_fields_set:
            self.text = "".join(run.text for run in self.runs)
        return self


class TextElement(BaseModel):
    """Текстовое содержимое элемента"""
    paragraphs: list[Paragraph] = Field(default_factory=list)
    full_text: str = ""

    @model_validator(mode="after")
    def restore_full_text(self) -> Self:
        if "full_text" not in self.model_fields_set:
            self.full_text = "\n".join(paragraph.text for paragraph in self.paragraphs)
        return self


class ImageElement(BaseModel):
    """Информация об изображении"""
    image_path: Optional[str] = None
    content_type: Optional[str] = None
    alt_text: Optional[str] = None
    asset_id: Optional[str] = None


class TableCell(BaseModel):
    """Ячейка контракта v2; оформление остаётся в исходном PPTX."""
    text: str = ""
    row_span: int = 1
    col_span: int = 1
    is_merged_origin: bool = False
    is_spanned: bool = False


class TableElement(BaseModel):
    """Данные таблицы"""
    rows: int
    cols: int
    cells: list[list[str]]

    @field_validator("cells", mode="before")
    @classmethod
    def read_v2_cells(cls, value: object) -> object:
        """Принимает строки v1 и структурированные ячейки v2."""
        if not isinstance(value, list):
            return value
        return [
            [TableCell.model_validate(cell).text if isinstance(cell, dict) else cell for cell in row]
            if isinstance(row, list) else row
            for row in value
        ]


class SlideElement(BaseModel):
    """Элемент слайда"""
    id: str
    type: str
    bbox: BBox
    z_order: Optional[int] = None
    placeholder_type: Optional[str] = None
    placeholder_kind: Optional[str] = None
    placeholder_idx: Optional[int] = None
    placeholder_name: Optional[str] = None
    text: Optional[TextElement] = None
    image: Optional[ImageElement] = None
    table: Optional[TableElement] = None

    @field_validator("placeholder_kind")
    @classmethod
    def check_placeholder_kind(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in PLACEHOLDER_TYPES:
            raise ValueError(f"Неизвестный тип placeholder v2: {value}")
        return value

    @model_validator(mode="after")
    def restore_placeholder_type(self) -> Self:
        if self.placeholder_type is None and self.placeholder_kind is not None:
            self.placeholder_type = PLACEHOLDER_TYPES[self.placeholder_kind]
        return self


class SlideBackground(BaseModel):
    """Фон слайда или макета"""
    fill_type: Optional[str] = None
    color_hex: Optional[str] = None
    image_path: Optional[str] = None


class Slide(BaseModel):
    """Слайд презентации"""
    index: int
    layout_type: str = "unknown"
    layout_name: Optional[str] = None
    layout_index: Optional[int] = None
    placeholder_type: Optional[str] = None
    elements: list[SlideElement] = Field(default_factory=list)
    background: Optional[SlideBackground] = None
    notes: Optional[str] = None


class LayoutInfo(BaseModel):
    """Информация о макете слайда"""
    name: str
    index: int
    elements: list[SlideElement] = Field(default_factory=list)
    placeholders: list[dict] = Field(default_factory=list)
    background: Optional[SlideBackground] = None


class ThemeInfo(BaseModel):
    """Тема презентации (цвета и шрифты)"""
    colors: dict[str, str] = Field(default_factory=dict)
    fonts: dict[str, str] = Field(default_factory=dict)


class DesignTokens(BaseModel):
    """Часть дизайн-токенов v2, используемая моделью сборщика."""
    theme: Optional[ThemeInfo] = None


class Presentation(BaseModel):
    """Структура презентации"""
    schema_version: Optional[Literal["1.0.0", "2.0.0"]] = None
    source_path: Optional[str] = None
    file_type: str = "pptx"
    slide_width: int
    slide_height: int
    slides: list[Slide] = Field(default_factory=list)
    layouts: list[LayoutInfo] = Field(default_factory=list)
    theme: Optional[ThemeInfo] = None
    tokens: Optional[DesignTokens] = None

    @model_validator(mode="after")
    def restore_theme(self) -> Self:
        if self.theme is None and self.tokens is not None:
            self.theme = self.tokens.theme
        return self
