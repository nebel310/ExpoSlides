from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


SCHEMA_VERSION = "2.0.0"


class ElementType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    TABLE = "table"
    CHART = "chart"
    SMARTART = "smartart"
    GROUP = "group"
    CONNECTOR = "connector"
    OLE = "ole"
    SHAPE = "shape"
    OTHER = "other"


class LayoutType(str, Enum):
    TITLE = "title"
    SECTION_HEADER = "section_header"
    BULLETS = "bullets"
    TWO_CONTENT = "two_content"
    IMAGE_TEXT = "image_text"
    TABLE = "table"
    THANK_YOU = "thank_you"
    UNKNOWN = "unknown"


class Alignment(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


class FillType(str, Enum):
    NONE = "none"
    SOLID = "solid"
    GRADIENT = "gradient"
    PICTURE = "picture"
    PATTERN = "pattern"
    BACKGROUND = "background"
    GROUP = "group"


class ChartType(str, Enum):
    BAR = "bar"
    COLUMN = "column"
    LINE = "line"
    PIE = "pie"
    DOUGHNUT = "doughnut"
    AREA = "area"
    SCATTER = "scatter"
    RADAR = "radar"
    BUBBLE = "bubble"
    STOCK = "stock"
    SURFACE = "surface"
    UNKNOWN = "unknown"


class ConnectorType(str, Enum):
    STRAIGHT = "straight"
    ELBOW = "elbow"
    CURVE = "curve"
    UNKNOWN = "unknown"


class BackgroundKind(str, Enum):
    NEUTRAL = "neutral"
    CONTAINER = "container"
    THEMATIC = "thematic"
    UNKNOWN = "unknown"


class PlaceholderKind(str, Enum):
    TITLE = "title"
    SUBTITLE = "subtitle"
    BODY = "body"
    CONTENT = "content"
    PICTURE = "picture"
    TABLE = "table"
    CHART = "chart"
    DATE = "date"
    FOOTER = "footer"
    SLIDE_NUMBER = "slide_number"
    SECTION_HEADER = "section_header"
    OTHER = "other"


class BBox(BaseModel):
    left: int
    top: int
    width: int
    height: int


class TextStyle(BaseModel):
    font_name: Optional[str] = None
    size_pt: Optional[float] = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color_hex: Optional[str] = None
    color_token: Optional[str] = None
    alignment: Optional[Alignment] = None
    line_spacing: Optional[float] = None


class Run(BaseModel):
    text: str
    style: TextStyle
    hyperlink: Optional[str] = None


class Paragraph(BaseModel):
    level: int = 0
    bullet: bool = False
    bullet_char: Optional[str] = None
    runs: list[Run] = Field(default_factory=list)


class TextElement(BaseModel):
    paragraphs: list[Paragraph] = Field(default_factory=list)


class GradientStop(BaseModel):
    position: float = 0.0
    color_hex: Optional[str] = None
    color_token: Optional[str] = None


class Fill(BaseModel):
    type: FillType = FillType.NONE
    color_hex: Optional[str] = None
    color_token: Optional[str] = None
    gradient_stops: list[GradientStop] = Field(default_factory=list)
    gradient_angle: Optional[float] = None
    picture_asset_id: Optional[str] = None
    pattern_name: Optional[str] = None


class LineStyle(BaseModel):
    color_hex: Optional[str] = None
    color_token: Optional[str] = None
    width_pt: Optional[float] = None
    dash: Optional[str] = None


class TableCell(BaseModel):
    text: str = ""
    row_span: int = 1
    col_span: int = 1
    is_merged_origin: bool = False
    is_spanned: bool = False


class TableElement(BaseModel):
    rows: int
    cols: int
    column_widths: list[int] = Field(default_factory=list)
    row_heights: list[int] = Field(default_factory=list)
    first_row_header: bool = False
    banded_rows: bool = False
    cells: list[list[TableCell]] = Field(default_factory=list)


class ImageElement(BaseModel):
    asset_id: Optional[str] = None
    content_type: Optional[str] = None
    original_width: Optional[int] = None
    original_height: Optional[int] = None
    alt_text: Optional[str] = None


class ChartSeries(BaseModel):
    name: Optional[str] = None
    categories: list[str] = Field(default_factory=list)
    values: list[float] = Field(default_factory=list)
    color_hex: Optional[str] = None
    color_token: Optional[str] = None


class ChartAxis(BaseModel):
    kind: str
    title: Optional[str] = None
    units: Optional[str] = None
    has_major_gridlines: bool = False
    has_minor_gridlines: bool = False
    min_value: Optional[float] = None
    max_value: Optional[float] = None


class ChartLegend(BaseModel):
    has_legend: bool = False
    position: Optional[str] = None


class ChartDataLabels(BaseModel):
    has_labels: bool = False
    show_value: bool = False
    show_category: bool = False
    show_series_name: bool = False
    show_percent: bool = False


class ChartElement(BaseModel):
    chart_type: ChartType = ChartType.UNKNOWN
    title: Optional[str] = None
    series: list[ChartSeries] = Field(default_factory=list)
    axes: list[ChartAxis] = Field(default_factory=list)
    legend: ChartLegend = Field(default_factory=ChartLegend)
    data_labels: ChartDataLabels = Field(default_factory=ChartDataLabels)


class SmartArtNode(BaseModel):
    id: str
    text: str = ""
    parent_id: Optional[str] = None
    level: int = 0


class SmartArtElement(BaseModel):
    layout_name: Optional[str] = None
    style_name: Optional[str] = None
    color_name: Optional[str] = None
    nodes: list[SmartArtNode] = Field(default_factory=list)


class ShapeGeometry(BaseModel):
    shape_type: Optional[str] = None
    adjustments: list[float] = Field(default_factory=list)


class GroupElement(BaseModel):
    children: list["SlideElement"] = Field(default_factory=list)


class ConnectorElement(BaseModel):
    connector_type: ConnectorType = ConnectorType.UNKNOWN
    begin_x: int = 0
    begin_y: int = 0
    end_x: int = 0
    end_y: int = 0
    begin_arrow: Optional[str] = None
    end_arrow: Optional[str] = None


class OleElement(BaseModel):
    prog_id: Optional[str] = None
    content_type: Optional[str] = None
    asset_id: Optional[str] = None
    name: Optional[str] = None


class SlideElement(BaseModel):
    id: str
    type: ElementType
    bbox: BBox
    z_order: Optional[int] = None
    rotation: Optional[float] = None
    placeholder_kind: Optional[PlaceholderKind] = None
    placeholder_idx: Optional[int] = None
    placeholder_name: Optional[str] = None
    fill: Optional[Fill] = None
    line: Optional[LineStyle] = None
    geometry: Optional[ShapeGeometry] = None
    text: Optional[TextElement] = None
    image: Optional[ImageElement] = None
    table: Optional[TableElement] = None
    chart: Optional[ChartElement] = None
    smartart: Optional[SmartArtElement] = None
    group: Optional[GroupElement] = None
    connector: Optional[ConnectorElement] = None
    ole: Optional[OleElement] = None
    hidden: bool = False
    is_background: bool = False


GroupElement.model_rebuild()


class SlideBackground(BaseModel):
    kind: BackgroundKind = BackgroundKind.UNKNOWN
    fill: Optional[Fill] = None


class TypographyEntry(BaseModel):
    size_pt: float
    role: str
    occurrences: int = 0


class TypographyScale(BaseModel):
    entries: list[TypographyEntry] = Field(default_factory=list)
    min_pt: Optional[float] = None
    max_pt: Optional[float] = None


class Grid(BaseModel):
    margin_left: Optional[int] = None
    margin_right: Optional[int] = None
    margin_top: Optional[int] = None
    margin_bottom: Optional[int] = None
    column_positions: list[int] = Field(default_factory=list)
    row_positions: list[int] = Field(default_factory=list)


class ThemeInfo(BaseModel):
    colors: dict[str, str] = Field(default_factory=dict)
    fonts: dict[str, str] = Field(default_factory=dict)
    all_fonts: list[str] = Field(default_factory=list)


class DesignTokens(BaseModel):
    theme: Optional[ThemeInfo] = None
    typography: TypographyScale = Field(default_factory=TypographyScale)
    grid: Grid = Field(default_factory=Grid)


class SlotSignature(BaseModel):
    kind: PlaceholderKind = PlaceholderKind.OTHER
    bbox: BBox
    idx: Optional[int] = None


class LayoutPattern(BaseModel):
    id: str
    name: str
    layout_indices: list[int] = Field(default_factory=list)
    slots: list[SlotSignature] = Field(default_factory=list)


class ComponentOccurrence(BaseModel):
    slide_index: int
    element_id: str


class Component(BaseModel):
    id: str
    signature: str
    element_template: SlideElement
    occurrences: list[ComponentOccurrence] = Field(default_factory=list)


class MasterInfo(BaseModel):
    index: int
    name: Optional[str] = None
    layout_indices: list[int] = Field(default_factory=list)


class PlaceholderInfo(BaseModel):
    kind: Optional[PlaceholderKind] = None
    name: Optional[str] = None
    idx: Optional[int] = None
    bbox: BBox


class Slide(BaseModel):
    index: int
    layout_type: LayoutType = LayoutType.UNKNOWN
    layout_name: Optional[str] = None
    layout_index: Optional[int] = None
    pattern_id: Optional[str] = None
    elements: list[SlideElement] = Field(default_factory=list)
    background: Optional[SlideBackground] = None
    notes: Optional[str] = None
    content_hash: Optional[str] = None


class LayoutInfo(BaseModel):
    name: str
    index: int
    layout_type: LayoutType = LayoutType.UNKNOWN
    pattern_id: Optional[str] = None
    placeholders: list[PlaceholderInfo] = Field(default_factory=list)
    background: Optional[SlideBackground] = None


class AssetRef(BaseModel):
    asset_id: str
    file_id: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    original_name: Optional[str] = None
    source: Optional[str] = None


class Presentation(BaseModel):
    schema_version: str = SCHEMA_VERSION
    source_path: Optional[str] = None
    file_type: str = "pptx"
    slide_width: int
    slide_height: int
    tokens: DesignTokens = Field(default_factory=DesignTokens)
    patterns: list[LayoutPattern] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    masters: list[MasterInfo] = Field(default_factory=list)
    slides: list[Slide] = Field(default_factory=list)
    layouts: list[LayoutInfo] = Field(default_factory=list)
    assets: list[AssetRef] = Field(default_factory=list)