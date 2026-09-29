"""Единое точное отображение данных в PPTX, расчёте места и проверке результата."""


def cell_text(value: str | int | float) -> str:
    """Сохранить все значащие цифры без округления стандартного формата g."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
