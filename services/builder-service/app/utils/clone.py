from typing import NoReturn

from app.errors import SlideReuseNotSupportedError


def clone_slide(
    source_prs: object,
    target_prs: object,
    source_slide: object,
) -> NoReturn:
    """Явно отклоняет небезопасное клонирование без переноса relationships."""
    del source_prs, target_prs, source_slide
    raise SlideReuseNotSupportedError(
        "Повторное использование слайда шаблона не поддерживается: "
        "для клонирования нужен полный перенос relationships"
    )
