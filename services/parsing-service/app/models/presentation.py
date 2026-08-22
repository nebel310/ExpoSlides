from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field




class ElementType(str, Enum):
    """Тип элемента слайда"""
    TEXT = "text"
    IMAGE = "image"
    TABLE = "table"
    OTHER = "other"


class LayoutType(str, Enum):
    """Тип макета слайда"""
    TITLE = "title"
    SECTION_HEADER = "section_header"
    BULLETS = "bullets"
    TWO_CONTENT = "two_content"
    IMAGE_TEXT = "image_text"
    TABLE = "table"
    THANK_YOU = "thank_you"
    UNKNOWN = "unknown"


class Alignment(str, Enum):
    """Выравнивание текста"""
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


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
    alignment: Optional[Alignment] = None
    line_spacing: Optional[float] = None


class Run(BaseModel):
    """Текстовый фрагмент с индивидуальным стилем"""
    text: str
    style: TextStyle


class Paragraph(BaseModel):
    """Абзац текста"""
    text: str
    level: int = 0
    bullet: bool = False
    runs: list[Run] = Field(default_factory=list)


class TextElement(BaseModel):
    """Текстовое содержимое элемента"""
    paragraphs: list[Paragraph] = Field(default_factory=list)
    full_text: str = ""


class ImageElement(BaseModel):
    """Информация об изображении"""
    image_path: Optional[str] = None
    content_type: Optional[str] = None
    alt_text: Optional[str] = None


class TableElement(BaseModel):
    """Данные таблицы"""
    rows: int
    cols: int
    cells: list[list[str]]


class PlaceholderInfo(BaseModel):
    """Информация о placeholder"""
    placeholder_type: Optional[str] = None
    name: Optional[str] = None
    idx: Optional[int] = None
    bbox: BBox
    element: "SlideElement"


class SlideElement(BaseModel):
    """Элемент слайда"""
    id: str
    type: ElementType
    bbox: BBox
    z_order: Optional[int] = None
    placeholder_type: Optional[str] = None
    placeholder_idx: Optional[int] = None
    placeholder_name: Optional[str] = None
    text: Optional[TextElement] = None
    image: Optional[ImageElement] = None
    table: Optional[TableElement] = None


class SlideBackground(BaseModel):
    """Фон слайда или макета"""
    fill_type: Optional[str] = None
    color_hex: Optional[str] = None
    image_path: Optional[str] = None


class Slide(BaseModel):
    """Слайд презентации"""
    index: int
    layout_type: LayoutType = LayoutType.UNKNOWN
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
    placeholders: list[PlaceholderInfo] = Field(default_factory=list)
    background: Optional[SlideBackground] = None


class ThemeInfo(BaseModel):
    """Тема презентации (цвета и шрифты)"""
    colors: dict[str, str] = Field(default_factory=dict)
    fonts: dict[str, str] = Field(default_factory=dict)


class Presentation(BaseModel):
    """Структура презентации"""
    source_path: str
    file_type: str = "pptx"
    slide_width: int
    slide_height: int
    slides: list[Slide] = Field(default_factory=list)
    layouts: list[LayoutInfo] = Field(default_factory=list)
    theme: Optional[ThemeInfo] = None