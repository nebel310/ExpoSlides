import os
import json
import zipfile
from io import BytesIO




ZIP_MAGIC_BYTES = b"PK\x03\x04"
PDF_MAGIC_BYTES = b"%PDF"



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


def detect_file_type(content: bytes) -> str | None:
    """Определить тип файла по содержимому"""
    if _is_valid_pptx(content):
        return "pptx"
    if _is_valid_pdf(content):
        return "pdf"
    if _is_valid_json(content):
        return "json"
    if _is_valid_txt(content):
        return "txt"
    return None


def get_extension_for_type(file_type: str) -> str:
    """Вернуть расширение для типа файла"""
    return {
        "pptx": ".pptx",
        "pdf": ".pdf",
        "json": ".json",
        "txt": ".txt",
    }[file_type]


def validate_file(filename: str, content: bytes) -> str | None:
    """Проверить что файл соответствует одному из допустимых типов и вернуть тип"""
    detected_type = detect_file_type(content)
    if detected_type is None:
        return None

    if filename:
        ext = os.path.splitext(filename)[1].lower()
        expected_ext = get_extension_for_type(detected_type)
        if ext != expected_ext:
            return None

    return detected_type