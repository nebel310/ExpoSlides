"""Узкие проверки служебных подписей и выдуманных имён в полях шаблона."""

import re
import unicodedata

_TECHNICAL_LABELS = {
    "title", "body", "footer", "subtitle", "header", "object", "text",
    "picture", "slide_number", "placeholder",
    "футер", "колонтитул", "нижний колонтитул", "верхний колонтитул",
    "плейсхолдер", "заполнитель", "текстовое поле",
}
_EMPTY_CONTENT_LABELS = {"основные моменты"}
_PERSON_CUE = re.compile(
    r"\b(?:фио|ф\.?\s*и\.?\s*о\.?|имя\s+(?:докладчика|автора|спикера|сотрудника|"
    r"участника|фамилия)|фамилия\s+имя|(?:speaker|presenter|author|employee|full|first)"
    r"\s+name|name\s+(?:surname|last\s+name))\b"
)
_FILLING_HINT = re.compile(
    r"(?:должность\s+(?:докладчика|автора|спикера|сотрудника|участника)|"
    r"название\s+(?:компании|организации|проекта|презентации)|"
    r"(?:заголовок|подзаголовок|текст)\s+(?:слайда|презентации)|"
    r"(?:speaker|presenter|author|employee)\s+(?:name|title|position)|"
    r"(?:company|organization|project|presentation)\s+name|"
    r"your\s+(?:name|title|company)|(?:insert|click\s+to\s+add)\s+(?:title|text))"
)
_NAME_WORD = r"(?:[А-ЯЁ][а-яё]{1,}|[A-Z][a-z]{1,})(?:[-'][A-ZА-ЯЁ]?[a-zа-яё]+)?"
_PERSON_NAME = re.compile(rf"{_NAME_WORD}(?:\s+{_NAME_WORD}){{1,2}}")
_WORDS = re.compile(r"[a-zа-я]+", re.IGNORECASE)


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().replace("ё", "е").split())


def placeholder_grounding_issues(
    source_text: str, generated_text: str, template_text: str,
) -> list[str]:
    """Не выполняет NER: проверяет имена при подсказке поля или имени в образце.

    Тематические подписи допустимы вместо отсутствующего автора. Поэтому наличие
    слов из исходника оставляет обычную подпись допустимой; произвольные заголовки
    и все написанные с заглавной буквы слова не считаются именами автоматически.
    """
    value = generated_text.strip()
    normalized = _normalize(value)
    source = _normalize(source_text)
    if not normalized or normalized in source:
        return []

    if normalized in _TECHNICAL_LABELS or re.fullmatch(r"field_\d{4,}", normalized):
        return ["вместо содержания использовано служебное имя поля"]

    if normalized in _EMPTY_CONTENT_LABELS:
        return ["вместо содержания использована общая заглушка; раскройте тему исходника"]

    if _PERSON_CUE.fullmatch(normalized) or _FILLING_HINT.fullmatch(normalized):
        return ["вместо содержания повторена подсказка заполнения шаблона"]

    person_field = (
        _PERSON_CUE.search(_normalize(template_text))
        or _PERSON_NAME.fullmatch(template_text.strip())
    )
    if not person_field:
        return []
    if not _PERSON_NAME.fullmatch(value):
        return []

    source_words = set(_WORDS.findall(source))
    name_words = set(_WORDS.findall(normalized))
    if not source_words.intersection(name_words):
        return [
            "имя человека не подтверждено исходником; используйте имя из исходника "
            "или краткую тематическую подпись"
        ]
    return []
