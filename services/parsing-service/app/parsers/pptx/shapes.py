from __future__ import annotations

import logging

from app.models.presentation import (
    BackgroundKind,
    BBox,
    ConnectorElement,
    ConnectorType,
    ElementType,
    Fill,
    FillType,
    GradientStop,
    GroupElement,
    LineStyle,
    ShapeGeometry,
    SlideBackground,
    SlideElement,
    ThemeInfo,
)
from app.parsers.pptx import assets as assets_module
from app.parsers.pptx import charts as charts_module
from app.parsers.pptx import smartart as smartart_module
from app.parsers.pptx import tables as tables_module
from app.parsers.pptx import text as text_module
from app.parsers.pptx.geometry import IDENTITY, Affine, group_transform, slide_bbox
from app.parsers.pptx.helpers import (
    get_rotation,
    get_z_order,
    map_placeholder_kind,
    normalize_placeholder_idx,
    theme_color_to_token,
)

from pptx.enum.dml import MSO_COLOR_TYPE, MSO_FILL_TYPE
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.slide import Slide, SlideLayout

logger = logging.getLogger(__name__)

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def parse_shape(
    shape,
    theme: ThemeInfo | None,
    element_id: str,
    assets: dict,
    owner: Slide | SlideLayout | None = None,
    *,
    transform: Affine = IDENTITY,
    shape_path: tuple[int, ...] = (),
) -> SlideElement | None:
    """Определяет тип фигуры и делегирует парсинг нужному методу"""
    bbox = BBox(
        left=shape.left,
        top=shape.top,
        width=shape.width,
        height=shape.height,
    )
    z_order = get_z_order(shape, element_id)
    rotation = get_rotation(shape)

    placeholder_kind = None
    placeholder_idx = None
    placeholder_name = None
    if shape.is_placeholder:
        placeholder_kind = map_placeholder_kind(shape.placeholder_format.type)
        placeholder_idx = normalize_placeholder_idx(shape.placeholder_format.idx)
        placeholder_name = shape.name

    fill = parse_fill(shape, theme, assets)
    line = parse_line(shape, theme)
    geometry = parse_geometry(shape)

    current_path = (*shape_path, shape.shape_id)
    common = dict(
        id=element_id,
        shape_id=shape.shape_id,
        shape_name=shape.name,
        has_text_frame=shape.has_text_frame,
        default_text_style=(text_module.default_style(shape, theme, placeholder_kind, owner)
                            if shape.has_text_frame else None),
        shape_path=list(current_path),
        slide_bbox=slide_bbox(shape, transform),
        bbox=bbox,
        z_order=z_order,
        rotation=rotation,
        placeholder_kind=placeholder_kind,
        placeholder_idx=placeholder_idx,
        placeholder_name=placeholder_name,
        fill=fill,
        line=line,
        geometry=geometry,
    )

    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        group = parse_group(
            shape, theme, element_id, assets, owner=owner,
            transform=transform, shape_path=current_path,
        )
        return SlideElement(type=ElementType.GROUP, group=group, **common)

    if getattr(shape, "has_chart", False):
        chart = charts_module.parse_chart(shape.chart, theme)
        return SlideElement(type=ElementType.CHART, chart=chart, **common)

    smartart = smartart_module.parse_smartart(shape)
    if smartart is not None:
        return SlideElement(type=ElementType.SMARTART, smartart=smartart, **common)

    if getattr(shape, "has_table", False):
        table = tables_module.parse_table(shape.table)
        return SlideElement(type=ElementType.TABLE, table=table, **common)

    if shape.shape_type == MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT:
        ole = assets_module.parse_ole(shape, assets)
        return SlideElement(type=ElementType.OLE, ole=ole, **common)

    if shape.shape_type == MSO_SHAPE_TYPE.LINE:
        connector = parse_connector(shape)
        if connector is not None:
            return SlideElement(type=ElementType.CONNECTOR, connector=connector, **common)

    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
        image = assets_module.parse_image(shape, assets)
        return SlideElement(type=ElementType.IMAGE, image=image, **common)

    if getattr(shape, "has_text_frame", False):
        text = text_module.parse_text_frame(
            shape.text_frame, placeholder_kind, theme, shape=shape, owner=owner
        )

        if placeholder_kind is not None:
            return SlideElement(type=ElementType.TEXT, text=text, **common)

        if geometry is not None and geometry.shape_type is not None:
            return SlideElement(type=ElementType.SHAPE, text=text, **common)

        if text is not None:
            return SlideElement(type=ElementType.TEXT, text=text, **common)

    return SlideElement(type=ElementType.SHAPE, **common)


def parse_group(
    shape,
    theme: ThemeInfo | None,
    parent_id: str,
    assets: dict,
    owner: Slide | SlideLayout | None = None,
    *,
    transform: Affine = IDENTITY,
    shape_path: tuple[int, ...] = (),
) -> GroupElement:
    """Рекурсивно разбирает группу фигур"""
    children: list[SlideElement] = []
    child_transform = group_transform(shape, transform)
    parent_path = shape_path or (shape.shape_id,)
    for idx, child in enumerate(shape.shapes):
        child_id = f"{parent_id}-child-{idx}"
        parsed = parse_shape(
            child, theme, child_id, assets, owner=owner,
            transform=child_transform, shape_path=parent_path,
        )
        if parsed:
            children.append(parsed)
    return GroupElement(children=children)


def parse_connector(shape) -> ConnectorElement | None:
    """Извлекает координаты и тип коннектора"""
    try:
        begin_x = getattr(shape, "begin_x", None)
        begin_y = getattr(shape, "begin_y", None)
        end_x = getattr(shape, "end_x", None)
        end_y = getattr(shape, "end_y", None)
        if None in (begin_x, begin_y, end_x, end_y):
            return None
    except Exception:
        return None

    ctype = ConnectorType.UNKNOWN
    try:
        prst = shape._element.find(f".//{{{A_NS}}}prstGeom")
        if prst is not None:
            geom = prst.get("prst", "")
            if geom == "line":
                ctype = ConnectorType.STRAIGHT
            elif geom in (
                "bentConnector2",
                "bentConnector3",
                "bentConnector4",
                "bentConnector5",
            ):
                ctype = ConnectorType.ELBOW
            elif geom in (
                "curvedConnector2",
                "curvedConnector3",
                "curvedConnector4",
                "curvedConnector5",
            ):
                ctype = ConnectorType.CURVE
    except Exception:
        pass

    return ConnectorElement(
        connector_type=ctype,
        begin_x=begin_x,
        begin_y=begin_y,
        end_x=end_x,
        end_y=end_y,
    )


def parse_fill(
    shape,
    theme: ThemeInfo | None,
    assets: dict,
) -> Fill | None:
    """Извлекает заливку фигуры"""
    try:
        fill = shape.fill
    except Exception:
        return None

    try:
        fill_type = fill.type
    except Exception:
        return None

    if fill_type is None:
        return None

    if fill_type == MSO_FILL_TYPE.BACKGROUND:
        return Fill(type=FillType.BACKGROUND)
    if fill_type == MSO_FILL_TYPE.GROUP:
        return Fill(type=FillType.GROUP)
    if fill_type == MSO_FILL_TYPE.SOLID:
        hex_val, token = fore_color(fill, theme)
        return Fill(type=FillType.SOLID, color_hex=hex_val, color_token=token)
    if fill_type == MSO_FILL_TYPE.GRADIENT:
        return parse_gradient_fill(fill, theme)
    if fill_type == MSO_FILL_TYPE.PATTERN:
        pattern = None
        try:
            pattern = str(fill.pattern)
        except Exception:
            pass
        hex_val, token = fore_color(fill, theme)
        return Fill(
            type=FillType.PATTERN,
            pattern_name=pattern,
            color_hex=hex_val,
            color_token=token,
        )
    if fill_type == MSO_FILL_TYPE.PICTURE:
        asset_id = assets_module.parse_picture_fill_asset(shape, assets)
        return Fill(type=FillType.PICTURE, picture_asset_id=asset_id)

    return Fill(type=FillType.NONE)


def fore_color(fill, theme: ThemeInfo | None) -> tuple[str | None, str | None]:
    """Достаёт HEX и токен из fore_color заливки"""
    try:
        fore = fill.fore_color
        if fore.type == MSO_COLOR_TYPE.RGB:
            return str(fore.rgb), None
        if fore.type == MSO_COLOR_TYPE.SCHEME:
            token = theme_color_to_token(fore.theme_color)
            hex_val = theme.colors.get(token) if theme else None
            return hex_val, token
    except Exception:
        pass
    return None, None


def parse_gradient_fill(fill, theme: ThemeInfo | None) -> Fill:
    """Извлекает градиент: стопы и угол"""
    stops: list[GradientStop] = []
    try:
        for stop in fill.gradient_stops:
            hex_val = None
            token = None
            try:
                color = stop.color
                if color.type == MSO_COLOR_TYPE.RGB:
                    hex_val = str(color.rgb)
                elif color.type == MSO_COLOR_TYPE.SCHEME:
                    token = theme_color_to_token(color.theme_color)
                    hex_val = theme.colors.get(token) if theme else None
            except Exception:
                pass
            stops.append(
                GradientStop(
                    position=float(stop.position),
                    color_hex=hex_val,
                    color_token=token,
                )
            )
    except Exception:
        pass

    angle = None
    try:
        angle = float(fill.gradient_angle)
    except Exception:
        pass

    return Fill(type=FillType.GRADIENT, gradient_stops=stops, gradient_angle=angle)


def parse_line(shape, theme: ThemeInfo | None) -> LineStyle | None:
    """Извлекает обводку фигуры"""
    try:
        line = shape.line
        color_hex = None
        color_token = None
        try:
            if line.color and line.color.type == MSO_COLOR_TYPE.RGB:
                color_hex = str(line.color.rgb)
            elif line.color and line.color.type == MSO_COLOR_TYPE.SCHEME:
                color_token = theme_color_to_token(line.color.theme_color)
                color_hex = theme.colors.get(color_token) if theme else None
        except Exception:
            pass

        width_pt = None
        try:
            if line.width is not None and line.width > 0:
                width_pt = line.width.pt
        except Exception:
            pass

        dash = None
        try:
            if line.dash_style is not None:
                dash = str(line.dash_style)
        except Exception:
            pass

        if color_hex is None and width_pt is None and dash is None:
            return None
        return LineStyle(
            color_hex=color_hex,
            color_token=color_token,
            width_pt=width_pt,
            dash=dash,
        )
    except Exception:
        return None


def parse_geometry(shape) -> ShapeGeometry | None:
    """Извлекает тип автофигуры и настройки"""
    shape_type = None
    try:
        ast = getattr(shape, "auto_shape_type", None)
        if ast is not None:
            shape_type = ast.name
    except Exception:
        pass

    adjustments: list[float] = []
    try:
        for adj in getattr(shape, "adjustments", []):
            adjustments.append(float(adj))
    except Exception:
        pass

    if shape_type is None and not adjustments:
        return None
    return ShapeGeometry(shape_type=shape_type, adjustments=adjustments)


def parse_background(
    background,
    theme: ThemeInfo | None,
    assets: dict,
) -> SlideBackground | None:
    """Извлекает фон и грубо классифицирует его тип"""
    if background is None:
        return None

    try:
        fill = background.fill
    except Exception:
        return None

    try:
        ftype = fill.type
    except Exception:
        return None

    parsed_fill: Fill | None = None
    if ftype == MSO_FILL_TYPE.SOLID:
        hex_val, token = fore_color(fill, theme)
        parsed_fill = Fill(type=FillType.SOLID, color_hex=hex_val, color_token=token)
    elif ftype == MSO_FILL_TYPE.GRADIENT:
        parsed_fill = parse_gradient_fill(fill, theme)
    elif ftype == MSO_FILL_TYPE.PICTURE:
        parsed_fill = Fill(type=FillType.PICTURE)
    elif ftype is not None:
        parsed_fill = Fill(type=FillType.NONE)

    if parsed_fill is None:
        return None

    kind = classify_background(parsed_fill)
    return SlideBackground(kind=kind, fill=parsed_fill)


def classify_background(fill: Fill) -> BackgroundKind:
    """Эвристика: solid/gradient/pattern — нейтральный, picture — неизвестно"""
    if fill.type in (
        FillType.SOLID,
        FillType.GRADIENT,
        FillType.NONE,
        FillType.BACKGROUND,
        FillType.PATTERN,
    ):
        return BackgroundKind.NEUTRAL
    if fill.type == FillType.PICTURE:
        return BackgroundKind.UNKNOWN
    return BackgroundKind.UNKNOWN
