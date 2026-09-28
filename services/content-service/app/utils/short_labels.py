"""Целые короткие технические термины, подтверждённые исходным текстом."""

import re

_TOKEN_LEFT = r"(?<![\w‐‑-])"
_TOKEN_RIGHT = r"(?![\w‐‑-])"
_TECHNICAL_TOKEN = re.compile(
    _TOKEN_LEFT + r"[A-Za-z]+(?:[‐‑-][A-Za-z]+)*" + _TOKEN_RIGHT
)
_CAMEL_CASE = re.compile(r"[a-z][A-Z]")
_ACRONYM = re.compile(r"[A-Z]{2,}")


def grounded_short_terms(original: str, source: str, limit: int) -> list[str]:
    """Возвращает подходящие термины в порядке появления, без обрезания слов.

    Форма CamelCase или аббревиатуры ограничивает выбор: обычные слова доклада
    и части составных слов не используются как случайные подписи.
    Проверка допустимости сокращения фактов и отрицаний остаётся у вызывающего
    кода; эта функция лишь находит целые общие токены внутри обоих текстов.
    """
    if limit <= 0:
        return []
    source_normalized = source.casefold()
    result = []
    seen = set()
    for match in _TECHNICAL_TOKEN.finditer(original):
        term = match.group()
        if len(term) > limit or not (_CAMEL_CASE.search(term) or _ACRONYM.fullmatch(term)):
            continue
        normalized = term.casefold()
        if normalized in seen or not re.search(
            _TOKEN_LEFT + re.escape(normalized) + _TOKEN_RIGHT, source_normalized,
        ):
            continue
        seen.add(normalized)
        result.append(term)
    return result
