"""Удаление однозначной нумерации плана без изменения числовых фактов."""

import re

from app.models.graph_state import SlidePlan
from app.utils.grounding import extract_fact_tokens

_NUMBERED_LINE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<number>[1-9]\d*)(?P<marker>[.)])[ \t]+"
    r"(?P<text>\S[^\r\n]*)(?P<ending>\r\n|\r|\n)?$"
)
_INLINE_NUMBER = re.compile(
    r"(?P<boundary>^[ \t]*|[ \t]*(?:→|->|⇒)[ \t]*|(?<=\.)[ \t]+)"
    r"(?P<number>[1-9]\d*)(?P<marker>[.)])[ \t]+"
)
_FACT_OPENING = re.compile(
    r"^(?:[\d%€$₽£+−–-]|"
    r"(?:январ[ьяе]|феврал[ьяе]|март[ае]?|апрел[ьяе]|ма[йяе]|июн[ьяе]|"
    r"июл[ьяе]|август[ае]?|сентябр[ьяе]|октябр[ьяе]|ноябр[ьяе]|декабр[ьяе]|"
    r"january|february|march|april|may|june|july|august|september|october|"
    r"november|december|янв|фев|мар|апр|июн|июл|авг|сен|сент|окт|ноя|нояб|дек|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|"
    r"квартал\w*|кв|полугоди\w*|год\w*|лет|месяц\w*|"
    r"недел\w*|дн\w*|день|час\w*|минут\w*|секунд\w*|"
    r"тыс\w*|млн|млрд|трлн|миллион\w*|миллиард\w*|"
    r"руб\w*|доллар\w*|евро|процент\w*|копе\w*|usd|eur|rub|gbp|cny|jpy|chf|"
    r"кг|г|мг|т|км|м|см|мм|л|мл|шт\w*|сек|мин|ч|сут\w*|квт|вт|байт\w*|"
    r"кб|мб|гб|тб|[kmgt]i?b|(?:кило|мега|гига|тера)байт\w*|"
    r"мест(?:о|а|у|ом|е)|ранг\w*|rank|place|"
    r"человек\w*|сотрудник\w*|пользовател\w*|клиент\w*|"
    r"years?|months?|weeks?|days?|hours?|minutes?|seconds?|quarters?|"
    r"thousand|million|billion|dollars?|euros?|percent|kg|km)\b)",
    re.IGNORECASE,
)


def _without_numbered_runs(values: list[str], source_tokens: set[str]) -> list[str]:
    """Меняет только целые соседние последовательности 1..N одного оформления."""
    result = values.copy()
    matches = [_NUMBERED_LINE.fullmatch(value) for value in values]
    position = 0
    while position < len(values):
        if matches[position] is None:
            position += 1
            continue
        end = position
        while end < len(values) and matches[end] is not None:
            end += 1
        run = [match for match in matches[position:end] if match is not None]
        numbers = [match["number"] for match in run]
        same_style = len({(match["indent"], match["marker"]) for match in run}) == 1
        sequential = numbers == [str(number) for number in range(1, len(run) + 1)]
        if (
            len(run) >= 2 and same_style and sequential
            and not source_tokens.intersection(numbers)
            and not any(_FACT_OPENING.match(match["text"]) for match in run)
        ):
            for offset, match in enumerate(run, position):
                result[offset] = match["indent"] + match["text"] + (match["ending"] or "")
        position = end
    return result


def _without_inline_numbering(text: str, source_tokens: set[str]) -> str:
    """Принимает только полный список от начала строки, разделённый точками/стрелками."""
    matches = list(_INLINE_NUMBER.finditer(text))
    numbers = [match["number"] for match in matches]
    if (
        len(matches) < 2 or matches[0].start() != 0
        or numbers != [str(number) for number in range(1, len(matches) + 1)]
        or len({match["marker"] for match in matches}) != 1
        or source_tokens.intersection(numbers)
    ):
        return text
    for position, match in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        item_text = text[match.end():end]
        if not item_text.strip() or _FACT_OPENING.match(item_text):
            return text
    result = text
    for match in reversed(matches):
        result = result[:match.start("number")] + result[match.end():]
    return result


def normalize_plan_numbering(plan: SlidePlan, source_text: str) -> SlidePlan:
    """Снимает только доказуемые номера пунктов; исходная модель не изменяется.

    Числа, встречающиеся в источнике, неоднозначные одиночные префиксы, даты,
    количества и нарушенные последовательности остаются для обычной проверки.
    """
    source_tokens = extract_fact_tokens(source_text)
    titles = _without_numbered_runs([item.title for item in plan.slides], source_tokens)
    replacements = []
    changed = False
    for item, title in zip(plan.slides, titles, strict=True):
        updates = {"title": title} if title != item.title else {}
        for field in ("content", "purpose", "key_message"):
            original = getattr(item, field)
            normalized = "".join(_without_numbered_runs(
                [
                    _without_inline_numbering(line, source_tokens)
                    for line in original.splitlines(keepends=True)
                ],
                source_tokens,
            ))
            if normalized != original:
                updates[field] = normalized
        changed |= bool(updates)
        replacements.append(item.model_copy(update=updates, deep=True))
    return plan.model_copy(update={"slides": replacements}) if changed else plan
