from pathlib import Path


async def file_exists(path: str | Path) -> bool:
    """Проверяет существование файла"""
    return Path(path).is_file()


async def get_file_extension(path: str | Path) -> str:
    """Возвращает расширение файла без точки"""
    return Path(path).suffix.lower().lstrip(".")