"""Консервативные проверки явных фактов; не заменяют контекстуальный аудит.

Привязки извлекаются только для распознанных показателей и локальных утверждений.
Отсутствие ошибки не доказывает смысловую эквивалентность произвольного пересказа.
Модуль не импортирует настройки сервиса и пригоден для независимого eval scorer.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from math import ceil
from typing import Sequence

_NUMBER = re.compile(
    r"(?<![\w.,])(?P<value>[+−-]?\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?)"
    r"[ \t]*(?P<scale>тыс\.?|млн\.?|млрд\.?|thousand|million|billion)?"
    r"[ \t]*(?P<unit>%|руб(?:лей|ля|ль)?\.?|₽|доллар(?:ов|а)?|\$|usd|rub|"
    r"евро|€|eur|минут(?:ы|а)?|мин\.?|час(?:ов|а)?|секунд(?:ы|а)?|"
    r"градус(?:ов|а)?|°c|пользовател(?:ей|я|ь)|респондент(?:ов|а)?|"
    r"участник(?:ов|а)?|сотрудник(?:ов|а)?|человек|users?|minutes?|hours?)?",
    re.IGNORECASE,
)
_METRICS = {
    "revenue": r"выруч\w*|оборот\w*|revenue|sales",
    "profit": r"прибыл\w*|profit",
    "margin": r"марж\w*|margin",
    "growth": r"рост\w*|вырос\w*|увелич\w*|growth|increase\w*",
    "decline": r"снижен\w*|сниз\w*|сократ\w*|decreas\w*|decline",
    "conversion": r"конверси\w*|conversion",
    "temperature": r"температур\w*|temperature",
    "cost": r"затрат\w*|расход\w*|стоимост\w*|costs?",
    "budget": r"бюджет\w*|budget",
    "users": r"пользовател\w*|users?",
    "respondents": r"респондент\w*|respondents?",
    "participants": r"участник\w*|participants?",
    "employees": r"сотрудник\w*|employees?",
    "duration": r"время|длительност\w*|duration",
    "retention": r"удержани\w*|retention",
    "share": r"доля|доли|долю|share",
}
_METRIC_PATTERN = re.compile(
    "|".join(rf"(?P<{key}>\b(?:{value})\b)" for key, value in _METRICS.items()),
    re.IGNORECASE,
)
_WORD = re.compile(r"[a-zа-яё]+", re.IGNORECASE)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_SENTENCE = re.compile(r"[^\n;.!?]+(?:[.!?](?!\s|$)[^\n;.!?]+)*")
_IMPORTANT = re.compile(
    r"^\s*(?:следующ(?:ий этап|ие шаги)|дальнейшие шаги|ограничени[ея]|риски|"
    r"обязательно|next steps?|limitations?|required)\s*(?:[:—–-]\s*)?(.+)$",
    re.IGNORECASE,
)
_STOP = {
    "компания", "компании", "платформа", "платформы", "продукт", "проекта", "проект",
    "составила", "составил", "составляет", "достигла", "году", "года", "рублей",
    "следующий", "этап", "следующие", "шаги", "также", "будет", "будут", "данных",
    "the", "and", "company", "platform", "will", "next", "steps",
}
_NEGATION = re.compile(r"\b(?:не|not|never)\s+([a-zа-яё]+)", re.IGNORECASE)
# Отрицание может относиться к именной части через связку: «не представлять
# собой одну растровую картинку». Допускаем только связки и определители,
# чтобы отрицание другого действия не переносилось на соседнее утверждение.
_NEGATION_PREFIX = re.compile(
    r"\b(?:не|not|never)\s+(?:(?:"
    r"представл\w*|явля\w*|собой|быть|есть|"
    r"один|одна|одно|одни|одного|одной|одному|одним|одну|одних|одними|одном|"
    r"be|being|is|are|was|were|represent(?:s|ed|ing)?|a|an|one|single"
    r")\s+)*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FactRecord:
    """Числовой факт с локальным контекстом и координатами в источнике."""

    metric: str
    value: Decimal
    unit: str
    entity: str | None
    period: str | None
    source_span: tuple[int, int]
    source_text: str


def _unit(raw: str) -> str:
    value = raw.casefold().rstrip(".")
    if value.startswith("руб") or value in {"₽", "rub"}:
        return "RUB"
    if value.startswith("доллар") or value in {"$", "usd"}:
        return "USD"
    if value in {"евро", "€", "eur"}:
        return "EUR"
    if value.startswith(("мин", "minute")):
        return "minute"
    if value.startswith(("час", "hour")):
        return "hour"
    if value.startswith("секунд"):
        return "second"
    if value.startswith("градус") or value == "°c":
        return "degree"
    if value.startswith(("пользовател", "респондент", "участник", "сотрудник", "user")):
        return "person"
    return "person" if value == "человек" else value


def _entity(text: str) -> str | None:
    quoted = re.search(r'[«"]([^»"]+)[»"]', text)
    if quoted:
        return quoted[1].casefold()
    named = re.search(
        r"\b(?:[Кк]омпани[яи]|[Пп]роект[а]?|[Пп]родукт[а]?)\s+([A-ZА-ЯЁ][\w-]+)", text,
    )
    if named:
        return named[1].casefold()
    return None


def extract_fact_records(text: str) -> list[FactRecord]:
    """Извлечь однозначные пары показатель—число, не угадывая неизвестные метрики."""
    records = []
    for sentence in _SENTENCE.finditer(text):
        sentence_text = sentence.group()
        years = list(_YEAR.finditer(sentence_text))
        # Запятая между утверждениями не должна связывать прибыль с чужой выручкой.
        for clause in re.finditer(r"(?:[^,]|(?<=\d),(?=\d))+", sentence_text):
            clause_text = clause.group()
            metrics = list(_METRIC_PATTERN.finditer(clause_text))
            if not metrics:
                continue
            entity = _entity(clause_text) or _entity(sentence_text)
            for number in _NUMBER.finditer(clause_text):
                raw_value = number["value"]
                if _YEAR.fullmatch(raw_value) and not number["unit"] and not number["scale"]:
                    continue
                before = [metric for metric in metrics if metric.end() <= number.start()]
                metric = before[-1] if before else min(
                    metrics, key=lambda item: abs(item.start() - number.end()),
                )
                # Далёкий термин в длинном абзаце не доказывает привязку числа.
                if min(abs(metric.end() - number.start()),
                       abs(metric.start() - number.end())) > 70:
                    continue
                position = clause.start() + number.start()
                preceding_years = [year for year in years if year.start() < position]
                year = preceding_years[-1] if preceding_years else (years[0] if years else None)
                scale = (number["scale"] or "").casefold().rstrip(".")
                multiplier = {
                    "тыс": 1000, "thousand": 1000,
                    "млн": 1_000_000, "million": 1_000_000,
                    "млрд": 1_000_000_000, "billion": 1_000_000_000,
                }.get(scale, 1)
                value = Decimal(raw_value.replace("−", "-").replace(",", ".")
                                .replace(" ", "").replace("\u00a0", "")) * multiplier
                start = sentence.start() + clause.start() + number.start()
                records.append(FactRecord(
                    metric=metric.lastgroup or "", value=value,
                    unit=_unit(number["unit"] or ""), entity=entity,
                    period=year.group() if year else None,
                    source_span=(start, start + len(number.group())),
                    source_text=clause_text.strip(),
                ))
    return records


def _terms(text: str) -> set[str]:
    """Локальные лексические опоры, включая частые формы для краткого пересказа."""
    result = set()
    for word in _WORD.findall(text.casefold().replace("ё", "е")):
        if len(word) < 4 or word in _STOP:
            continue
        if word.startswith(("обуч", "тренинг")):
            result.add("обуч")
        elif word.startswith(("расшир", "экспанс")):
            result.add("расшир")
        else:
            result.add(word[:5])
    return result


def required_source_messages(source_text: str) -> list[str]:
    """Только явно отмеченные шаги, риски и ограничения обязательны автоматически."""
    result = []
    for sentence in _SENTENCE.finditer(source_text):
        match = _IMPORTANT.match(sentence.group())
        if match and len(_terms(match[1])) >= 2:
            result.append(match[1].strip())
    return result


def source_topic_visible(source_text: str, generated_text: str) -> bool:
    """Минимальная видимая опора источника, когда пояснения вынесены в notes."""
    expected = _terms(source_text)
    return bool(expected) and len(expected & _terms(generated_text)) >= min(2, len(expected))


def missing_required_messages(
    generated_text: str, required_messages: Sequence[str],
) -> list[str]:
    """Вернуть сообщения без достаточных явных лексических опор в результате."""
    generated = _terms(generated_text)
    missing = []
    for message in required_messages:
        expected = _terms(message)
        needed = min(len(expected), max(2, ceil(len(expected) * 0.5)))
        if expected and len(expected & generated) < needed:
            missing.append(message)
    return missing


def _polarity_issues(source_text: str, generated_text: str) -> list[str]:
    issues = []

    def clauses(text: str) -> list[str]:
        return [
            clause for sentence in _SENTENCE.finditer(text)
            for clause in re.split(r",\s+|\s+(?:но|but)\s+", sentence.group(),
                                   flags=re.IGNORECASE)
        ]

    def claim_key(text: str) -> tuple[str, ...]:
        return tuple(re.findall(r"\w+", text.casefold().replace("ё", "е")))

    source_claims = {claim_key(clause) for clause in clauses(source_text)}

    # Проверяем оба направления: удалённое отрицание и добавленное отрицание.
    for negative_text, other_text in (
        (source_text, generated_text), (generated_text, source_text),
    ):
        for text in clauses(negative_text):
            for negative in _NEGATION.finditer(text):
                predicate = negative[1].casefold()[:4]
                objects = _terms(text[negative.end():])
                if not objects:
                    continue
                quantifier = negative[1].casefold() in {
                    "один", "одна", "одно", "одни", "одного", "одной", "одному",
                    "одним", "одну", "одних", "одними", "одном",
                }
                quantified_object = _WORD.search(text, negative.end()) if quantifier else None
                for other in clauses(other_text):
                    # Общие слова не связывают разные утверждения: например,
                    # «не один инструмент» и «один агент с инструментами».
                    # Сосуществовавшие в источнике фразы не являются новой подменой.
                    # Новое отрицание/утверждение проверяется, даже если результат
                    # одновременно сохранил исходную правильную фразу.
                    if claim_key(text) in source_claims and claim_key(other) in source_claims:
                        continue
                    matches = list(re.finditer(rf"\b{re.escape(predicate)}\w*", other,
                                               re.IGNORECASE))
                    if quantified_object:
                        # «Один агент с инструментами» не утверждает «один инструмент»:
                        # сравниваем ближайший объект количества, а не весь хвост фразы.
                        matches = [match for match in matches if (
                            (candidate := _WORD.search(other, match.end()))
                            and candidate.group().casefold()[:5]
                            == quantified_object.group().casefold()[:5]
                        )]
                    if not matches or not objects.intersection(_terms(other)):
                        continue
                    if any(not _NEGATION_PREFIX.search(other[:match.start()])
                           for match in matches):
                        issues.append("Изменено отрицание исходного утверждения: " + text.strip())
    return list(dict.fromkeys(issues))


def semantic_content_issues(
    source_text: str, generated_text: str, required_messages: Sequence[str] | None = None,
    *, check_required_messages: bool = True,
) -> list[str]:
    """Обнаружить явные подмены связей фактов и пропущенные обязательные сообщения."""
    source = extract_fact_records(source_text)
    generated = extract_fact_records(generated_text)
    issues = []
    for fact in generated:
        candidates = [item for item in source if item.metric == fact.metric]
        if not candidates:
            continue
        if fact.entity and any(item.entity for item in candidates):
            candidates = [item for item in candidates if item.entity == fact.entity]
        if fact.period and any(item.period for item in candidates):
            candidates = [item for item in candidates if item.period == fact.period]
        if not any(item.value == fact.value and (
            not item.unit or not fact.unit or item.unit == fact.unit
        ) for item in candidates):
            issues.append(
                "Изменена связь показателя, значения, единицы или периода: " + fact.source_text
            )
    issues.extend(_polarity_issues(source_text, generated_text))
    required = list(required_source_messages(source_text)) if check_required_messages else []
    required.extend(required_messages or [])
    issues.extend(
        "Не раскрыто обязательное сообщение источника: " + message
        for message in missing_required_messages(generated_text, list(dict.fromkeys(required)))
    )
    return list(dict.fromkeys(issues))
