class BuilderError(RuntimeError):
    """Базовая ошибка сборки презентации."""


class BuilderInputError(BuilderError):
    """Входные файлы или межсервисные данные не согласованы."""


class BuilderOutputError(BuilderError):
    """Итоговый PPTX не удалось безопасно сохранить или проверить."""


class SlideReuseNotSupportedError(BuilderError):
    """Повторное использование одного слайда шаблона пока не поддерживается."""
