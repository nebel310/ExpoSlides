from __future__ import annotations

import logging

from app.models.presentation import (
    ChartAxis,
    ChartDataLabels,
    ChartElement,
    ChartLegend,
    ChartSeries,
    ChartType,
    ThemeInfo,
)
from app.parsers.pptx.helpers import theme_color_to_token

from pptx.enum.chart import XL_LEGEND_POSITION
from pptx.enum.dml import MSO_COLOR_TYPE

logger = logging.getLogger(__name__)


def parse_chart(chart, theme: ThemeInfo | None) -> ChartElement:
    """Извлекает тип, серии, оси, легенду и подписи диаграммы"""
    chart_type = map_chart_type(chart.chart_type)

    title = None
    try:
        if chart.has_title and chart.chart_title.text_frame:
            title = chart.chart_title.text_frame.text
    except Exception:
        pass

    categories: list[str] = []
    try:
        categories = [str(c) for c in chart.plots[0].categories]
    except Exception:
        pass

    series: list[ChartSeries] = []
    for s in chart.series:
        name = None
        try:
            name = s.name
        except Exception:
            pass

        values: list[float] = []
        try:
            values = [float(v) for v in s.values if v is not None]
        except Exception:
            pass

        color_hex, color_token = series_color(s, theme)

        series.append(
            ChartSeries(
                name=name,
                categories=categories,
                values=values,
                color_hex=color_hex,
                color_token=color_token,
            )
        )

    legend = parse_legend(chart)
    axes = parse_axes(chart)
    data_labels = parse_data_labels(chart)

    return ChartElement(
        chart_type=chart_type,
        title=title,
        series=series,
        axes=axes,
        legend=legend,
        data_labels=data_labels,
    )


def series_color(series, theme: ThemeInfo | None) -> tuple[str | None, str | None]:
    """Пытается достать цвет серии диаграммы"""
    try:
        fore = series.format.fill.fore_color
        if fore.type == MSO_COLOR_TYPE.RGB:
            return str(fore.rgb), None
        if fore.type == MSO_COLOR_TYPE.SCHEME:
            token = theme_color_to_token(fore.theme_color)
            hex_val = theme.colors.get(token) if theme else None
            return hex_val, token
    except Exception:
        pass
    return None, None


def parse_axes(chart) -> list[ChartAxis]:
    """Извлекает параметры осей диаграммы"""
    axes: list[ChartAxis] = []
    for attr, kind in (("category_axis", "category"), ("value_axis", "value")):
        try:
            axis = getattr(chart, attr, None)
        except ValueError:
            # Круговые и кольцевые диаграммы не имеют осей. python-pptx
            # сообщает об этом исключением из свойства, а не значением None.
            continue
        if axis is None:
            continue
        axes.append(parse_axis(axis, kind))
    return axes


def parse_axis(axis, kind: str) -> ChartAxis:
    """Извлекает параметры одной оси"""
    title = None
    try:
        if axis.has_title and axis.axis_title.text_frame:
            title = axis.axis_title.text_frame.text
    except Exception:
        pass

    has_major = False
    has_minor = False
    try:
        has_major = bool(axis.has_major_gridlines)
        has_minor = bool(axis.has_minor_gridlines)
    except Exception:
        pass

    min_value = None
    max_value = None
    try:
        if axis.minimum_scale is not None:
            min_value = float(axis.minimum_scale)
        if axis.maximum_scale is not None:
            max_value = float(axis.maximum_scale)
    except Exception:
        pass

    return ChartAxis(
        kind=kind,
        title=title,
        has_major_gridlines=has_major,
        has_minor_gridlines=has_minor,
        min_value=min_value,
        max_value=max_value,
    )


def parse_legend(chart) -> ChartLegend:
    """Извлекает настройки легенды"""
    try:
        if chart.has_legend:
            return ChartLegend(
                has_legend=True,
                position=map_legend_position(chart.legend.position),
            )
    except Exception:
        pass
    return ChartLegend()


def parse_data_labels(chart) -> ChartDataLabels:
    """Извлекает настройки подписей данных"""
    try:
        plot = chart.plots[0]
        if not plot.has_data_labels:
            return ChartDataLabels()
        dl = plot.data_labels
        return ChartDataLabels(
            has_labels=True,
            show_value=bool(getattr(dl, "show_value", False)),
            show_category=bool(getattr(dl, "show_category_name", False)),
            show_series_name=bool(getattr(dl, "show_series_name", False)),
            show_percent=bool(getattr(dl, "show_percentage", False)),
        )
    except Exception:
        return ChartDataLabels()


def map_chart_type(xl_type) -> ChartType:
    """Приводит XL_CHART_TYPE к упрощённому ChartType"""
    try:
        name = str(xl_type).lower()
    except Exception:
        return ChartType.UNKNOWN

    if "column" in name:
        return ChartType.COLUMN
    if "bar" in name:
        return ChartType.BAR
    if "line" in name:
        return ChartType.LINE
    if "pie" in name:
        return ChartType.PIE
    if "doughnut" in name:
        return ChartType.DOUGHNUT
    if "area" in name:
        return ChartType.AREA
    if "scatter" in name or "xy" in name:
        return ChartType.SCATTER
    if "radar" in name:
        return ChartType.RADAR
    if "bubble" in name:
        return ChartType.BUBBLE
    if "stock" in name:
        return ChartType.STOCK
    if "surface" in name:
        return ChartType.SURFACE
    return ChartType.UNKNOWN


def map_legend_position(position) -> str | None:
    """Приводит XL_LEGEND_POSITION к строке"""
    mapping = {
        XL_LEGEND_POSITION.BOTTOM: "bottom",
        XL_LEGEND_POSITION.CORNER: "corner",
        XL_LEGEND_POSITION.LEFT: "left",
        XL_LEGEND_POSITION.RIGHT: "right",
        XL_LEGEND_POSITION.TOP: "top",
    }
    return mapping.get(position)