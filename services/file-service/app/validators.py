import json
import os
import zipfile
from io import BytesIO

ZIP_MAGIC_BYTES = b"PK\x03\x04"
PDF_MAGIC_BYTES = b"%PDF"

PNG_MAGIC_BYTES = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC_BYTES = b"\xFF\xD8\xFF"
GIF87_MAGIC_BYTES = b"GIF87a"
GIF89_MAGIC_BYTES = b"GIF89a"
BMP_MAGIC_BYTES = b"BM"
TIFF_LE_MAGIC_BYTES = b"II*\x00"
TIFF_BE_MAGIC_BYTES = b"MM\x00*"
EMF_MAGIC_BYTES = b"\x01\x00\x00\x00"
EMF_SIGNATURE = b" EMF"
WMF_PLACEABLE_MAGIC_BYTES = b"\xD7\xCD\xC6\x9A"
WMF_STANDARD_MAGIC_BYTES = b"\x01\x00\x09\x00"
WEBP_RIFF_MAGIC_BYTES = b"RIFF"
WEBP_FORMAT_MAGIC_BYTES = b"WEBP"
SVG_XML_PREFIX = b"<?xml"
SVG_TAG_PREFIX = b"<svg"


FILE_TYPE_EXTENSIONS: dict[str, list[str]] = {
    "pptx": [".pptx"],
    "pdf": [".pdf"],
    "json": [".json"],
    "txt": [".txt"],
    "png": [".png"],
    "jpg": [".jpg", ".jpeg"],
    "gif": [".gif"],
    "bmp": [".bmp"],
    "tiff": [".tiff", ".tif"],
    "emf": [".emf"],
    "wmf": [".wmf"],
    "svg": [".svg"],
    "webp": [".webp"],
}


def _is_valid_pptx(content: bytes) -> bool:
    """Проверить что контент является валидным pptx"""
    if not content.startswith(ZIP_MAGIC_BYTES):
        return False
    try:
        with zipfile.ZipFile(BytesIO(content)) as zf:
            if "[Content_Types].xml" not in zf.namelist():
                return False
            if not any(name.startswith("ppt/") for name in zf.namelist()):
                return False
    except zipfile.BadZipFile:
        return False
    return True


def _is_valid_pdf(content: bytes) -> bool:
    """Проверить что контент является валидным pdf"""
    return content.startswith(PDF_MAGIC_BYTES)


def _is_valid_json(content: bytes) -> bool:
    """Проверить что контент является валидным json"""
    try:
        json.loads(content.decode("utf-8"))
        return True
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False


def _is_valid_txt(content: bytes) -> bool:
    """Проверить что контент является текстовым"""
    if b"\x00" in content:
        return False
    try:
        content.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _is_valid_png(content: bytes) -> bool:
    """Проверить что контент является png"""
    return content.startswith(PNG_MAGIC_BYTES)


def _is_valid_jpeg(content: bytes) -> bool:
    """Проверить что контент является jpeg"""
    return content.startswith(JPEG_MAGIC_BYTES)


def _is_valid_gif(content: bytes) -> bool:
    """Проверить что контент является gif"""
    return content.startswith(GIF87_MAGIC_BYTES) or content.startswith(GIF89_MAGIC_BYTES)


def _is_valid_bmp(content: bytes) -> bool:
    """Проверить что контент является bmp"""
    return content.startswith(BMP_MAGIC_BYTES)


def _is_valid_tiff(content: bytes) -> bool:
    """Проверить что контент является tiff"""
    return content.startswith(TIFF_LE_MAGIC_BYTES) or content.startswith(TIFF_BE_MAGIC_BYTES)


def _is_valid_emf(content: bytes) -> bool:
    """Проверить что контент является emf"""
    if not content.startswith(EMF_MAGIC_BYTES):
        return False
    if len(content) < 44:
        return False
    return content[40:44] == EMF_SIGNATURE


def _is_valid_wmf(content: bytes) -> bool:
    """Проверить что контент является wmf"""
    return (
        content.startswith(WMF_PLACEABLE_MAGIC_BYTES)
        or content.startswith(WMF_STANDARD_MAGIC_BYTES)
    )


def _is_valid_svg(content: bytes) -> bool:
    """Проверить что контент является svg"""
    head = content[:100].lstrip()
    return head.startswith(SVG_XML_PREFIX) or head.startswith(SVG_TAG_PREFIX)


def _is_valid_webp(content: bytes) -> bool:
    """Проверить что контент является webp"""
    if len(content) < 12:
        return False
    return content.startswith(WEBP_RIFF_MAGIC_BYTES) and content[8:12] == WEBP_FORMAT_MAGIC_BYTES


def detect_file_type(content: bytes) -> str | None:
    """Определить тип файла по содержимому"""
    if _is_valid_pptx(content):
        return "pptx"
    if _is_valid_pdf(content):
        return "pdf"
    if _is_valid_json(content):
        return "json"
    if _is_valid_png(content):
        return "png"
    if _is_valid_jpeg(content):
        return "jpg"
    if _is_valid_gif(content):
        return "gif"
    if _is_valid_bmp(content):
        return "bmp"
    if _is_valid_tiff(content):
        return "tiff"
    if _is_valid_emf(content):
        return "emf"
    if _is_valid_wmf(content):
        return "wmf"
    if _is_valid_webp(content):
        return "webp"
    if _is_valid_svg(content):
        return "svg"
    if _is_valid_txt(content):
        return "txt"
    return None


def get_extension_for_type(file_type: str) -> str:
    """Вернуть каноничное расширение для типа файла"""
    return FILE_TYPE_EXTENSIONS[file_type][0]


def validate_file(filename: str, content: bytes) -> str | None:
    """Проверить что файл соответствует одному из допустимых типов и вернуть тип"""
    detected_type = detect_file_type(content)
    if detected_type is None:
        return None

    if filename:
        ext = os.path.splitext(filename)[1].lower()
        if ext not in FILE_TYPE_EXTENSIONS[detected_type]:
            return None

    return detected_type