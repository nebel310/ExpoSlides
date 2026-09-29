"""Узкая совместимость с неэкранированными кавычками в названиях макетов PPTX."""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any

from lxml import etree

from exposlides.web import APIError, inspect_template

_LAYOUT = re.compile(r"ppt/slideLayouts/slideLayout[0-9]+\.xml\Z")
_NAME = re.compile(rb'<p:cSld\b[^>]*\bname="([^"<>]*)"')


def prepare_template(data: bytes, name: str) -> tuple[bytes, dict[str, Any]]:
    """Проверить оригинал и при известном дефекте вернуть отдельную рабочую версию.

    Проверки размера, ZIP и CRC выполняются inspect_template до разбора XML.
    Не используем recovery-парсер: любые остальные повреждения остаются ошибкой.
    """
    try:
        return data, inspect_template(data, name, require_placeholders=False)
    except APIError as error:
        if not isinstance(error.__cause__, etree.XMLSyntaxError):
            raise
        original_error = error

    changes: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            if not _LAYOUT.fullmatch(member.filename):
                continue
            xml = archive.read(member)
            try:
                etree.fromstring(xml)
                continue
            except etree.XMLSyntaxError:
                pass
            # Каноническое имя cSld уже экранировано самим автором шаблона.
            match = _NAME.search(xml)
            if match is None or b"&quot;" not in match[1]:
                raise original_error
            escaped = match[1]
            broken = b'matchingName="' + escaped.replace(b"&quot;", b'"') + b'"'
            root_end = xml.find(b">", xml.find(b"<p:sldLayout"))
            if root_end < 0 or xml[:root_end].count(broken) != 1:
                raise original_error
            fixed = xml[:root_end].replace(
                broken, b'matchingName="' + escaped + b'"', 1,
            ) + xml[root_end:]
            try:
                root = etree.fromstring(fixed)
            except etree.XMLSyntaxError:
                raise original_error from None
            if root.tag != "{http://schemas.openxmlformats.org/presentationml/2006/main}sldLayout":
                raise original_error
            changes[member.filename] = fixed
        if not changes:
            raise original_error
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as compatible:
            compatible.comment = archive.comment
            for member in archive.infolist():
                compatible.writestr(member, changes.get(member.filename, archive.read(member)))
    working = output.getvalue()
    return working, inspect_template(working, name, require_placeholders=False)
