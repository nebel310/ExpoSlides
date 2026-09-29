"""Замена содержимого фотографии с сохранением маски, положения и порядка фигур."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement

from exposlides.design_models import PlacedBlock
from exposlides.design_native_text import native_shapes
from exposlides.design_pptx_parts import NativeBuildError, isolate_slide_layout


def image_size(path: Path) -> tuple[int, int]:
    if not path.is_file() or path.stat().st_size > 25 * 1024 * 1024:
        raise NativeBuildError("Нужен локальный PNG/JPEG размером не более 25 МБ")
    try:
        with Image.open(path) as image:
            size = image.size
            if image.format not in {"PNG", "JPEG"} or size[0] * size[1] > 25_000_000:
                raise NativeBuildError("Поддерживаются PNG/JPEG до 25 миллионов пикселей")
            image.verify()
            return size
    except NativeBuildError:
        raise
    except Exception as error:
        raise NativeBuildError("Не удалось прочитать изображение") from error


def fill_native_images(presentation, slide, blocks: list[PlacedBlock]) -> None:
    """Меняется только ссылка на фото и центральная обрезка под исходную область."""
    images = [block for block in blocks if block.kind == "image" and block.image_fit == "template"]
    if any(block.source_layer == "layout" for block in images):
        isolate_slide_layout(presentation, slide)
    used = set()
    for block in images:
        key = (block.source_layer, block.source_shape_id)
        if key in used:
            raise NativeBuildError("Одна фотография назначена нескольким блокам")
        used.add(key)
        layer = slide.slide_layout if block.source_layer == "layout" else slide
        shape = next((shape for shape in native_shapes(layer.shapes)
                      if shape.shape_id == block.source_shape_id), None)
        if shape is None or shape._element.tag != qn("p:pic"):
            raise NativeBuildError("Не найдена исходная фотография шаблона")
        path = Path(block.image_path)
        width, height = image_size(path)
        _, rid = layer.part.get_or_add_image_part(str(path))
        fill = shape._element.find(qn("p:blipFill"))
        blip = fill.find(qn("a:blip"))
        if blip is None or blip.get(qn("r:link")):
            raise NativeBuildError("Фотография должна быть встроена в шаблон")
        blip.set(qn("r:embed"), rid)
        # Новое фото может иметь другое соотношение сторон: заполняем всю маску
        # центральной обрезкой, без растяжения изображения и без изменения пути маски.
        ratio = block.box.width / block.box.height
        image_ratio = width / height
        horizontal = max(0, (1 - ratio / image_ratio) / 2)
        vertical = max(0, (1 - image_ratio / ratio) / 2)
        crop = fill.find(qn("a:srcRect"))
        if crop is None:
            crop = OxmlElement("a:srcRect")
            fill.insert(1, crop)
        for name, value in (("l", horizontal), ("r", horizontal),
                            ("t", vertical), ("b", vertical)):
            crop.set(name, str(round(value * 100000)))
