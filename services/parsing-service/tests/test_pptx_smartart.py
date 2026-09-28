from __future__ import annotations

from app.parsers.pptx import smartart as smartart_module
from lxml import etree

DGM_NS = "http://schemas.openxmlformats.org/drawingml/2006/diagram"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _build_data_xml(nodes: list[tuple[str, str, str | None]], links: list[tuple[str, str]]) -> bytes:
    """Собирает минимальный dataModel XML для теста

    nodes: список (modelId, type, text)
    links: список (srcId, dstId) типа parOf
    """
    parts = [f'<dgm:dataModel xmlns:dgm="{DGM_NS}" xmlns:a="{A_NS}">']
    parts.append("<dgm:ptLst>")
    for model_id, ptype, text in nodes:
        text_el = ""
        if text is not None:
            text_el = f"<a:t>{text}</a:t>"
        parts.append(
            f'<dgm:pt modelId="{model_id}" type="{ptype}">'
            f"<dgm:prSet/>"
            f"<dgm:t><a:bodyPr/><a:p><a:r>{text_el}</a:r></a:p></dgm:t>"
            f"</dgm:pt>"
        )
    parts.append("</dgm:ptLst>")
    parts.append("<dgm:cxnLst>")
    for src, dst in links:
        parts.append(
            f'<dgm:cxn type="parOf" srcId="{src}" destId="{dst}"/>'
        )
    parts.append("</dgm:cxnLst>")
    parts.append("</dgm:dataModel>")
    return "".join(parts).encode("utf-8")


# ---------- parse_smartart_nodes ----------


def test_parse_smartart_nodes_single_root() -> None:
    """Один узел без детей"""
    xml = _build_data_xml([("n1", "doc", "Hello")], [])
    nodes = smartart_module.parse_smartart_nodes(xml)

    assert len(nodes) == 1
    assert nodes[0].id == "n1"
    assert nodes[0].text == "Hello"
    assert nodes[0].level == 0
    assert nodes[0].parent_id is None


def test_parse_smartart_nodes_tree() -> None:
    """Дерево: root → два ребёнка"""
    xml = _build_data_xml(
        [
            ("root", "doc", "Root"),
            ("c1", "node", "Child1"),
            ("c2", "node", "Child2"),
        ],
        [("root", "c1"), ("root", "c2")],
    )
    nodes = smartart_module.parse_smartart_nodes(xml)
    by_id = {n.id: n for n in nodes}

    assert by_id["root"].level == 0
    assert by_id["c1"].level == 1
    assert by_id["c2"].level == 1
    assert by_id["c1"].parent_id == "root"
    assert by_id["c2"].parent_id == "root"


def test_parse_smartart_nodes_nested() -> None:
    """Вложенность на два уровня"""
    xml = _build_data_xml(
        [
            ("root", "doc", "R"),
            ("c1", "node", "C1"),
            ("g1", "node", "G1"),
        ],
        [("root", "c1"), ("c1", "g1")],
    )
    nodes = smartart_module.parse_smartart_nodes(xml)
    by_id = {n.id: n for n in nodes}

    assert by_id["g1"].level == 2
    assert by_id["g1"].parent_id == "c1"


def test_parse_smartart_nodes_skips_transitions() -> None:
    """Узлы типов parTrans / sibTrans / pres пропускаются"""
    xml = _build_data_xml(
        [
            ("root", "doc", "R"),
            ("t1", "parTrans", None),
            ("c1", "node", "C1"),
        ],
        [("root", "t1"), ("t1", "c1")],
    )
    nodes = smartart_module.parse_smartart_nodes(xml)
    ids = [n.id for n in nodes]

    assert "t1" not in ids
    assert "root" in ids
    assert "c1" in ids


def test_parse_smartart_nodes_broken_xml() -> None:
    """Битый XML возвращает пустой список"""
    assert smartart_module.parse_smartart_nodes(b"not xml at all") == []


def test_parse_smartart_nodes_empty_xml() -> None:
    """Пустой dataModel без ptLst возвращает []"""
    xml = f'<dgm:dataModel xmlns:dgm="{DGM_NS}"/>'.encode("utf-8")

    assert smartart_module.parse_smartart_nodes(xml) == []


# ---------- extract_smartart_text ----------


def test_extract_smartart_text_single() -> None:
    """Один a:t внутри узла"""
    xml = _build_data_xml([("n1", "doc", "Hello")], [])
    root = etree.fromstring(xml)
    pt = next(root.iter(f"{{{DGM_NS}}}pt"))

    text = smartart_module.extract_smartart_text(pt)

    assert text == "Hello"


def test_extract_smartart_text_multiple() -> None:
    """Несколько a:t конкатенируются"""
    xml = (
        f'<dgm:pt xmlns:dgm="{DGM_NS}" xmlns:a="{A_NS}" modelId="n1" type="node">'
        f"<dgm:t><a:p><a:r><a:t>One</a:t></a:r><a:r><a:t>Two</a:t></a:r></a:p></dgm:t>"
        f"</dgm:pt>"
    ).encode("utf-8")
    pt = etree.fromstring(xml)

    text = smartart_module.extract_smartart_text(pt)

    assert text == "OneTwo"


def test_extract_smartart_text_empty() -> None:
    """Пустой узел даёт пустую строку"""
    xml = f'<dgm:pt xmlns:dgm="{DGM_NS}" modelId="n1" type="node"/>'.encode("utf-8")
    pt = etree.fromstring(xml)

    assert smartart_module.extract_smartart_text(pt) == ""


# ---------- parse_diagram_name ----------


def test_parse_diagram_name_from_title() -> None:
    """Имя берётся из <dgm:title val='...'>"""
    xml = (
        f'<dgm:layoutDef xmlns:dgm="{DGM_NS}">'
        f'<dgm:title val="Pyramid"/>'
        f"</dgm:layoutDef>"
    ).encode("utf-8")

    assert smartart_module.parse_diagram_name(xml) == "Pyramid"


def test_parse_diagram_name_from_desc() -> None:
    """Если title нет — берётся desc"""
    xml = (
        f'<dgm:layoutDef xmlns:dgm="{DGM_NS}">'
        f'<dgm:desc val="Fallback"/>'
        f"</dgm:layoutDef>"
    ).encode("utf-8")

    assert smartart_module.parse_diagram_name(xml) == "Fallback"


def test_parse_diagram_name_nothing() -> None:
    """Без title/desc — None"""
    xml = f'<dgm:layoutDef xmlns:dgm="{DGM_NS}"/>'.encode("utf-8")

    assert smartart_module.parse_diagram_name(xml) is None


def test_parse_diagram_name_broken_xml() -> None:
    """Битый XML — None"""
    assert smartart_module.parse_diagram_name(b"not xml") is None


# ---------- parse_smartart на сломанной фигуре ----------


def test_parse_smartart_broken_shape_returns_none() -> None:
    """Фигура без relIds возвращает None"""

    class BrokenShape:
        class _element:
            @staticmethod
            def find(path):
                return None

    assert smartart_module.parse_smartart(BrokenShape()) is None


def test_get_diagram_part_unknown_kind() -> None:
    """Неизвестный kind → None"""
    assert smartart_module.get_diagram_part(None, {}, "unknown") is None


def test_get_diagram_part_no_rel_id() -> None:
    """Без rId → None"""

    class FakeRelIds:
        @staticmethod
        def get(key):
            return None

    assert smartart_module.get_diagram_part(None, FakeRelIds(), "data") is None