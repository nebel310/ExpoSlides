"""Изолированные операции OPC для независимых копий слайдов внутри шаблона."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.packuri import PackURI
from pptx.oxml import parse_xml
from pptx.oxml.ns import qn


class NativeBuildError(ValueError):
    """Шаблон или план нельзя безопасно собрать в редактируемую презентацию."""


class _PartCloner:
    def __init__(self, presentation: Any, selected_parts: list[Any]) -> None:
        self.package = presentation.part.package
        self.used_names = {str(part.partname) for part in self.package.iter_parts()}
        self.primary: dict[Any, Any] = {}
        self.clones = []
        for source in selected_parts:
            clone = self._empty_clone(source)
            self.clones.append(clone)
            self.primary.setdefault(source, clone)

    def _empty_clone(self, source: Any) -> Any:
        path = PurePosixPath(str(source.partname))
        counter = 1
        while True:
            candidate = str(path.with_name(f"{path.stem}-exposlides-{counter}{path.suffix}"))
            if candidate not in self.used_names:
                break
            counter += 1
        self.used_names.add(candidate)
        return type(source).load(PackURI(candidate), source.content_type, self.package, source.blob)

    def _copy_relationships(self, source: Any, clone: Any, memo: dict[Any, Any]) -> None:
        targets = {}
        for relationship in source.rels.values():
            if relationship.is_external:
                continue
            target = relationship.target_part
            if relationship.reltype in {
                RT.SLIDE_LAYOUT,
                RT.SLIDE_MASTER,
                RT.NOTES_MASTER,
                RT.THEME,
                RT.IMAGE,
            }:
                copied = target
            elif target in memo:
                copied = memo[target]
            elif relationship.reltype == RT.SLIDE:
                copied = self.primary.get(target)
                if copied is None:
                    raise NativeBuildError(
                        "Шаблон содержит внутреннюю ссылку на слайд, отсутствующий в плане"
                    )
            else:
                # У каждого экземпляра собственные chart/workbook/SmartArt/notes parts.
                copied = self._empty_clone(target)
                memo[target] = copied
                self._copy_relationships(target, copied, memo)
            targets[target.partname] = copied
        clone.load_rels_from_xml(parse_xml(source.rels.xml), targets)
        if len(clone.rels) != len(source.rels):
            raise NativeBuildError("При клонировании потеряна связь между частями PPTX")

    def populate(self, sources: list[Any]) -> list[Any]:
        for source, clone in zip(sources, self.clones, strict=True):
            self._copy_relationships(source, clone, {source: clone})
        return self.clones


def clone_selected_slides(presentation: Any, source_indices: list[int]) -> list[Any]:
    """Заменяет список слайдов независимыми копиями в заданном порядке."""
    sources = list(presentation.slides)
    if any(index < 1 or index > len(sources) for index in source_indices):
        raise NativeBuildError("План ссылается на отсутствующий слайд шаблона")
    xml = presentation.part._element
    if xml.find(qn("p:custShowLst")) is not None or any(
        element.tag.endswith("}sectionLst") for element in xml.iter()
    ):
        raise NativeBuildError(
            "Шаблон содержит custom shows или sections: их перенос в новую колоду пока не поддерживается"
        )
    selected = [sources[index - 1].part for index in source_indices]
    clones = _PartCloner(presentation, selected).populate(selected)
    slide_ids = presentation.slides._sldIdLst
    old_ids = list(slide_ids)
    for element in old_ids:
        slide_ids.remove(element)
        presentation.part.drop_rel(element.rId)
        if element.rId in presentation.part.rels:
            raise NativeBuildError("PPTX содержит дополнительные ссылки на исходный слайд")
    for clone in clones:
        rid = presentation.part.relate_to(clone, RT.SLIDE)
        slide_ids.add_sldId(rid)
        # Тайминги могут ссылаться на удаляемые фигуры. Новая колода статическая.
        timing = clone._element.find(qn("p:timing"))
        if timing is not None:
            clone._element.remove(timing)
    return [part.slide for part in clones]


def remove_shapes(slide: Any, shape_ids: list[int]) -> None:
    """Удаляет только явно выбранные фигуры, сохраняя соседей во вложенных группах."""
    requested = set(shape_ids)
    found: set[int] = set()

    def visit(shapes) -> None:
        for shape in list(shapes):
            if shape.shape_id in requested:
                found.add(shape.shape_id)
                # Также учитываем явно перечисленных потомков удаляемой группы.
                if hasattr(shape, "shapes"):
                    collect(shape.shapes)
                shape._element.getparent().remove(shape._element)
            elif hasattr(shape, "shapes"):
                visit(shape.shapes)

    def collect(shapes) -> None:
        for shape in shapes:
            if shape.shape_id in requested:
                found.add(shape.shape_id)
            if hasattr(shape, "shapes"):
                collect(shape.shapes)

    visit(slide.shapes)
    missing = requested - found
    if missing:
        raise NativeBuildError(f"Не найдены заменяемые фигуры: {sorted(missing)}")
