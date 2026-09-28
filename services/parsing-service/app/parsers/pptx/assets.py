from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

from app.models.presentation import ImageElement, OleElement

logger = logging.getLogger(__name__)

R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


@dataclass
class AssetBlob:
    """Байты ассета до загрузки в file-service"""

    asset_id: str
    content_type: str
    data: bytes
    original_name: Optional[str] = None


def register_asset(
    data: bytes,
    content_type: str | None,
    original_name: str | None,
    assets: dict[str, AssetBlob],
) -> str:
    """Регистрирует бинарный ассет по хешу содержимого (дедупликация)"""
    asset_id = hashlib.sha256(data).hexdigest()[:16]
    if asset_id not in assets:
        assets[asset_id] = AssetBlob(
            asset_id=asset_id,
            content_type=content_type or "application/octet-stream",
            data=data,
            original_name=original_name,
        )
    return asset_id


def parse_image(shape, assets: dict[str, AssetBlob]) -> ImageElement:
    """Извлекает метаданные картинки и сохраняет байты в assets"""
    try:
        image = shape.image
    except Exception:
        return ImageElement(alt_text=getattr(shape, "alt_text", None))

    asset_id = register_asset(
        data=image.blob,
        content_type=image.content_type,
        original_name=getattr(image, "filename", None),
        assets=assets,
    )

    original_width = None
    original_height = None
    try:
        original_width, original_height = image.size
    except Exception:
        pass

    return ImageElement(
        asset_id=asset_id,
        content_type=image.content_type,
        original_width=original_width,
        original_height=original_height,
        alt_text=getattr(shape, "alt_text", None),
    )


def parse_ole(shape, assets: dict[str, AssetBlob]) -> OleElement:
    """Извлекает OLE-объект: progId и встроенный файл"""
    prog_id = None
    name = None
    content_type = None
    asset_id = None

    try:
        el = shape._element
        prog_id = el.get("progId")
        name = el.get("name")
        for rel in shape.part.rels.values():
            if rel.reltype.endswith("/oleObject"):
                ole_part = rel.target_part
                data = ole_part.blob
                content_type = getattr(ole_part, "content_type", None)
                asset_id = register_asset(
                    data=data,
                    content_type=content_type,
                    original_name=name,
                    assets=assets,
                )
                break
    except Exception:
        logger.debug("Не удалось разобрать OLE", exc_info=True)

    return OleElement(
        prog_id=prog_id,
        content_type=content_type,
        asset_id=asset_id,
        name=name,
    )


def parse_picture_fill_asset(shape, assets: dict[str, AssetBlob]) -> str | None:
    """Достаёт байты картинки из picture-fill фигуры и регистрирует как ассет"""
    try:
        a_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
        blip = shape._element.find(f".//{{{a_ns}}}blip")
        if blip is None:
            return None
        rId = blip.get(f"{{{R_NS}}}embed")
        if not rId:
            return None
        part = shape.part.related_part(rId)
        return register_asset(
            data=part.blob,
            content_type=getattr(part, "content_type", None),
            original_name=getattr(part, "partname", None),
            assets=assets,
        )
    except Exception:
        return None