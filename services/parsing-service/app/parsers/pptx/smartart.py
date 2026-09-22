from __future__ import annotations

import logging

from lxml import etree

from app.models.presentation import SmartArtElement, SmartArtNode

logger = logging.getLogger(__name__)

DGM_NS = "http://schemas.openxmlformats.org/drawingml/2006/diagram"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

_REL_KINDS = {
    "dm": "data",
    "lo": "layout",
    "qs": "quickStyle",
    "cs": "colors",
}


def parse_smartart(shape) -> SmartArtElement | None:
    """Извлекает SmartArt: имя раскладки, стиль, узлы и связи"""
    try:
        el = shape._element
        relIds = el.find(f".//{{{DGM_NS}}}relIds")
        if relIds is None:
            return None
    except Exception:
        return None

    layout_name = None
    style_name = None
    color_name = None
    nodes: list[SmartArtNode] = []

    try:
        data_part = get_diagram_part(shape, relIds, "data")
        if data_part is not None:
            nodes = parse_smartart_nodes(data_part.blob)

        layout_part = get_diagram_part(shape, relIds, "layout")
        if layout_part is not None:
            layout_name = parse_diagram_name(layout_part.blob)

        style_part = get_diagram_part(shape, relIds, "quickStyle")
        if style_part is not None:
            style_name = parse_diagram_name(style_part.blob)

        color_part = get_diagram_part(shape, relIds, "colors")
        if color_part is not None:
            color_name = parse_diagram_name(color_part.blob)
    except Exception:
        logger.debug("Не удалось разобрать SmartArt", exc_info=True)

    return SmartArtElement(
        layout_name=layout_name,
        style_name=style_name,
        color_name=color_name,
        nodes=nodes,
    )


def get_diagram_part(shape, relIds, kind: str):
    """Достаёт related part диаграммы по типу (data / layout / quickStyle / colors)"""
    rel_attr = {"data": "dm", "layout": "lo", "quickStyle": "qs", "colors": "cs"}.get(kind)
    if rel_attr is None:
        return None

    rId = relIds.get(f"{{{R_NS}}}{rel_attr}")
    if not rId:
        return None

    try:
        return shape.part.related_part(rId)
    except Exception:
        return None


def parse_smartart_nodes(blob: bytes) -> list[SmartArtNode]:
    """Разбирает XML dataModel SmartArt и строит дерево узлов"""
    try:
        root = etree.fromstring(blob)
    except Exception:
        return []

    nodes_by_id: dict[str, SmartArtNode] = {}
    children_map: dict[str, list[str]] = {}

    for pt in root.iter(f"{{{DGM_NS}}}pt"):
        model_id = pt.get("modelId")
        if not model_id:
            continue
        ptype = pt.get("type")
        if ptype in ("parTrans", "sibTrans", "pres"):
            continue
        text = extract_smartart_text(pt)
        nodes_by_id[model_id] = SmartArtNode(id=model_id, text=text)
        children_map[model_id] = []

    for cxn in root.iter(f"{{{DGM_NS}}}cxn"):
        src = cxn.get("srcId")
        dst = cxn.get("destId")
        ctype = cxn.get("type")
        if ctype == "parOf" and src in children_map and dst in nodes_by_id:
            children_map[src].append(dst)

    # множество всех id, которые у кого-то являются ребёнком
    child_ids: set[str] = set()
    for children in children_map.values():
        child_ids.update(children)

    def walk(node_id: str, level: int, parent: str | None) -> None:
        node = nodes_by_id[node_id]
        node.parent_id = parent
        node.level = level
        for child_id in children_map.get(node_id, []):
            walk(child_id, level + 1, node_id)

    roots = set(nodes_by_id) - child_ids
    for root_id in roots:
        walk(root_id, 0, None)

    return list(nodes_by_id.values())


def extract_smartart_text(pt) -> str:
    """Собирает текст из всех a:t внутри узла"""
    parts: list[str] = []
    for t in pt.iter(f"{{{A_NS}}}t"):
        if t.text:
            parts.append(t.text)
    return "".join(parts)


def parse_diagram_name(blob: bytes) -> str | None:
    """Достаёт имя из title/desc части диаграммы"""
    try:
        root = etree.fromstring(blob)
    except Exception:
        return None
    for tag in ("title", "desc"):
        el = root.find(f".//{{{DGM_NS}}}{tag}")
        if el is not None and el.get("val"):
            return el.get("val")
    return None