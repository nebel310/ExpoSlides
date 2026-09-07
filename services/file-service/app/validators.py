import zipfile
from io import BytesIO


ALLOWED_EXTENSIONS = {".pptx"}
ALLOWED_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/zip",
}
ZIP_MAGIC_BYTES = b"PK\x03\x04"


def validate_pptx(filename: str, content_type: str, file_content: bytes) -> bool:
    """Проверить что файл является pptx"""
    if not filename.lower().endswith(tuple(ALLOWED_EXTENSIONS)):
        return False

    if content_type not in ALLOWED_MIME_TYPES:
        return False

    if not file_content.startswith(ZIP_MAGIC_BYTES):
        return False

    try:
        with zipfile.ZipFile(BytesIO(file_content)) as zf:
            if "[Content_Types].xml" not in zf.namelist():
                return False
            if not any(name.startswith("ppt/") for name in zf.namelist()):
                return False
    except zipfile.BadZipFile:
        return False

    return True