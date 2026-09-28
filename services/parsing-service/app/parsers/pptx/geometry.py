"""Координаты элементов с учётом вложенных групп, отражений и поворотов."""

from math import cos, radians, sin

from app.models.presentation import BBox

from pptx.oxml.ns import qn

Affine = tuple[float, float, float, float, float, float]
IDENTITY: Affine = (1, 0, 0, 1, 0, 0)


def compose(left: Affine, right: Affine) -> Affine:
    """Композиция: сначала right, затем left."""
    a, b, c, d, e, f = left
    g, h, i, j, k, m = right
    return (
        a * g + c * h,
        b * g + d * h,
        a * i + c * j,
        b * i + d * j,
        a * k + c * m + e,
        b * k + d * m + f,
    )


def _xfrm(shape):
    for container_name in ("p:grpSpPr", "p:spPr"):
        container = shape._element.find(qn(container_name))
        if container is not None:
            element = container.find(qn("a:xfrm"))
            if element is not None:
                return element
    return shape._element.find(qn("p:xfrm"))


def _orientation(shape) -> Affine:
    """Поворот и отражения относительно центра в координатах родителя."""
    xfrm = _xfrm(shape)
    flip_h = xfrm is not None and xfrm.get("flipH") in ("1", "true")
    flip_v = xfrm is not None and xfrm.get("flipV") in ("1", "true")
    angle = radians(float(getattr(shape, "rotation", 0) or 0))
    sx, sy = (-1 if flip_h else 1), (-1 if flip_v else 1)
    a, b = cos(angle) * sx, sin(angle) * sx
    c, d = -sin(angle) * sy, cos(angle) * sy
    cx = shape.left + shape.width / 2
    cy = shape.top + shape.height / 2
    return (a, b, c, d, cx - a * cx - c * cy, cy - b * cx - d * cy)


def slide_bbox(shape, parent_transform: Affine = IDENTITY) -> BBox:
    """Ограничивающая рамка элемента в координатах слайда (EMU)."""
    a, b, c, d, e, f = compose(parent_transform, _orientation(shape))
    points = [
        (a * x + c * y + e, b * x + d * y + f)
        for x in (shape.left, shape.left + shape.width)
        for y in (shape.top, shape.top + shape.height)
    ]
    left = round(min(x for x, _ in points))
    top = round(min(y for _, y in points))
    return BBox(
        left=left,
        top=top,
        width=round(max(x for x, _ in points)) - left,
        height=round(max(y for _, y in points)) - top,
    )


def group_transform(shape, parent_transform: Affine = IDENTITY) -> Affine:
    """Преобразование локальной системы дочерних элементов группы в слайд."""
    xfrm = _xfrm(shape)
    if xfrm is None:
        return parent_transform
    offset = xfrm.find(qn("a:chOff"))
    extent = xfrm.find(qn("a:chExt"))
    if offset is None or extent is None:
        return parent_transform
    child_width = int(extent.get("cx", "0"))
    child_height = int(extent.get("cy", "0"))
    sx = shape.width / child_width if child_width else 1
    sy = shape.height / child_height if child_height else 1
    local = (
        sx,
        0,
        0,
        sy,
        shape.left - sx * int(offset.get("x", "0")),
        shape.top - sy * int(offset.get("y", "0")),
    )
    return compose(parent_transform, compose(_orientation(shape), local))
