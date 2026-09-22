from __future__ import annotations

import importlib
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
SOURCE = "Агенты используют инструменты для решения задач и анализа результатов."


def _load(service_importer, *, titles=None, content="Содержание"):
    utility = service_importer(CONTENT_SERVICE_ROOT, "app.utils.plan_formatting")
    models = importlib.import_module("app.models.graph_state")
    plan = models.SlidePlan.model_validate({"slides": [{
        "template_slide_index": index + 9,
        "layout_type": "Исходный макет",
        "title": title,
        "content": content,
        "purpose": "Цель слайда",
        "key_message": "Основная мысль",
        "source_block_indices": [99],
    } for index, title in enumerate(titles or ["Заголовок"], 1)]})
    return utility, plan


@pytest.mark.parametrize("field", ["content", "purpose", "key_message"])
@pytest.mark.parametrize("marker", [".", ")"])
def test_removes_only_sequential_line_prefixes(service_importer, field, marker):
    utility, plan = _load(service_importer)
    original = (
        f"Введение\n1{marker} Анализ задачи\n2{marker} Выбор инструментов\n"
        f"3{marker} Проверка результата\nЗаключение"
    )
    setattr(plan.slides[0], field, original)

    result = utility.normalize_plan_numbering(plan, SOURCE)

    assert getattr(result.slides[0], field) == (
        "Введение\nАнализ задачи\nВыбор инструментов\nПроверка результата\nЗаключение"
    )
    assert getattr(plan.slides[0], field) == original


def test_titles_use_slide_order_and_keep_indices_and_original_immutable(service_importer):
    utility, plan = _load(service_importer, titles=[
        "Введение", "1. Анализ", "2. Инструменты", "Заключение",
    ])
    snapshot = plan.model_dump()

    result = utility.normalize_plan_numbering(plan, SOURCE)

    assert [item.title for item in result.slides] == [
        "Введение", "Анализ", "Инструменты", "Заключение",
    ]
    assert plan.model_dump() == snapshot
    for before, after in zip(plan.slides, result.slides, strict=True):
        assert before.model_dump(exclude={"title"}) == after.model_dump(exclude={"title"})
        assert before is not after
    result.slides[0].source_block_indices.append(100)
    assert plan.model_dump() == snapshot


@pytest.mark.parametrize("text", [
    "1. Анализ",
    "1. Анализ\n3. Инструменты",
    "1. Анализ\n2. Инструменты\n5. Проверка",
    "2. Анализ\n3. Инструменты",
    "01. Анализ\n02. Инструменты",
    "1. Анализ\n2) Инструменты",
    "1. Анализ\n  2. Инструменты",
    "1. Анализ\n\n2. Инструменты",
    "1. Анализ\nПояснение\n2. Инструменты",
    "1.Анализ\n2.Инструменты",
    "1. \n2. Инструменты",
    "2026. Анализ\n2027. Инструменты",
    "1.5% рост\n2.5% рост",
    "1. Анализ\n2. Инструменты\n1. Проверка\n2. Завершение",
])
def test_ambiguous_or_broken_sequences_are_unchanged(service_importer, text):
    utility, plan = _load(service_importer, content=text)
    assert utility.normalize_plan_numbering(plan, SOURCE) is plan
    utility, plan = _load(service_importer, titles=[line or " " for line in text.splitlines()])
    assert utility.normalize_plan_numbering(plan, SOURCE) is plan


@pytest.mark.parametrize("first,second", [
    ("января начинается проект", "февраля заканчивается проект"),
    ("квартал — анализ", "квартал — разработка"),
    ("млн рублей затрат", "млн рублей дохода"),
    ("миллиона рублей затрат", "миллиона рублей дохода"),
    ("процент роста", "процента роста"),
    ("месяц работы", "месяца работы"),
    ("кг сырья", "кг сырья"),
    ("человек в команде", "человека в команде"),
    ("January", "February"),
    ("янв. начало", "фев. завершение"),
    ("кв. анализа", "кв. разработки"),
    ("сек. работы", "сек. работы"),
    ("million rubles", "million rubles"),
    ("2. 2026", "3. 2026"),
    ("25% рост", "35% рост"),
    ("-5 градусов", "-10 градусов"),
    ("₽ затрат", "₽ дохода"),
])
def test_date_unit_and_numeric_openings_are_never_removed(service_importer, first, second):
    text = f"1. {first}\n2. {second}"
    utility, plan = _load(service_importer, content=text)
    assert utility.normalize_plan_numbering(plan, SOURCE) is plan
    utility, plan = _load(service_importer, titles=text.splitlines())
    assert utility.normalize_plan_numbering(plan, SOURCE) is plan


@pytest.mark.parametrize("source", [
    SOURCE + " 1 инструмент.", SOURCE + " 2 инструмента.", SOURCE + " Изменение -1.",
])
def test_source_numbers_disable_entire_matching_run(service_importer, source):
    utility, plan = _load(
        service_importer, titles=["1. Анализ", "2. Инструменты"],
        content="1. Анализ\n2. Инструменты",
    )
    assert utility.normalize_plan_numbering(plan, source) is plan


def test_indentation_crlf_and_remaining_facts_are_preserved_exactly(service_importer):
    text = (
        "Описание\r\n\t1) Доход 42 млн рублей, изменение -5%, дата 22.09.2026.  \r\n"
        "\t2) Версия API v3.7 совместима с GPT4; лимит 7.5%.\r\nКонец"
    )
    utility, plan = _load(service_importer, content=text)
    source = SOURCE + " 42 млн рублей -5% 22.09.2026 v3.7 GPT4 7.5%"

    result = utility.normalize_plan_numbering(plan, source)

    assert result.slides[0].content == text.replace("\t1) ", "\t").replace("\t2) ", "\t")
    assert plan.slides[0].content == text


def test_independent_runs_are_normalized_without_touching_other_text(service_importer):
    text = "1. Анализ\n2. Инструменты\nРаздел\n1) Проверка\n2) Завершение"
    utility, plan = _load(service_importer, content=text)
    result = utility.normalize_plan_numbering(plan, SOURCE)
    assert result.slides[0].content == "Анализ\nИнструменты\nРаздел\nПроверка\nЗавершение"


def test_real_unfounded_numbers_remain_visible_to_grounding(service_importer):
    utility, plan = _load(
        service_importer, content="1. Доход 42 млн рублей\n2. Рост составил 25%",
    )
    result = utility.normalize_plan_numbering(plan, SOURCE)
    assert utility.extract_fact_tokens(result.slides[0].content) == {"42", "25%"}


def test_normalization_is_idempotent(service_importer):
    utility, plan = _load(
        service_importer, titles=["1. Анализ", "2. Инструменты"],
        content="1. Проверка\n2. Завершение",
    )
    result = utility.normalize_plan_numbering(plan, SOURCE)
    assert utility.normalize_plan_numbering(result, SOURCE) is result


@pytest.mark.parametrize("original,expected", [
    (
        "1. Входные данные → 2. Рассуждение (анализ задачи, формирование плана) → "
        "3. Действие (выбор инструмента, выполнение) → 4. Повтор цикла до завершения задачи.",
        "Входные данные → Рассуждение (анализ задачи, формирование плана) → "
        "Действие (выбор инструмента, выполнение) → Повтор цикла до завершения задачи.",
    ),
    (
        "1. Определение задачи и желаемого результата. "
        "2. Выбор подходящей архитектуры агента. 3. Подбор необходимых инструментов. "
        "4. Настройка модели и системного промта. "
        "5. Итеративная разработка и тестирование с LangSmith.",
        "Определение задачи и желаемого результата. "
        "Выбор подходящей архитектуры агента. Подбор необходимых инструментов. "
        "Настройка модели и системного промта. "
        "Итеративная разработка и тестирование с LangSmith.",
    ),
    (
        "1. Анализ запроса пользователя. 2. Поиск в векторном хранилище. "
        "3. Дополнительный поиск актуальных новостей при нехватке информации.",
        "Анализ запроса пользователя. Поиск в векторном хранилище. "
        "Дополнительный поиск актуальных новостей при нехватке информации.",
    ),
    ("\t1) Анализ.  2) Инструменты.\r\n", "\tАнализ.  Инструменты.\r\n"),
    ("1. Анализ →2. Инструменты", "Анализ →Инструменты"),
    ("1. Анализ -> 2. Инструменты", "Анализ -> Инструменты"),
])
def test_inline_numbering_from_real_failures_preserves_all_other_text(
    service_importer, original, expected,
):
    utility, plan = _load(service_importer, content=original)
    result = utility.normalize_plan_numbering(plan, SOURCE)
    assert result.slides[0].content == expected
    assert plan.slides[0].content == original


@pytest.mark.parametrize("text", [
    "1. Анализ. 3. Инструменты.",
    "1. Анализ. 2. Инструменты. 5. Проверка.",
    "1. Анализ → 2. Инструменты → 5. Проверка.",
    "1. Анализ 2. Инструменты",
    "1. Анализ. 2) Инструменты.",
    "1. января начинается проект. 2. февраля заканчивается проект.",
    "1. квартал анализа. 2. квартал разработки.",
    "1. млн рублей. 2. млн рублей.",
    "1. 5% рост. 2. 10% рост.",
    "1. Анализ → 2. → 3. Проверка.",
    "Описание. 1. Анализ. 2. Инструменты.",
])
def test_ambiguous_inline_sequences_are_not_rewritten(service_importer, text):
    utility, plan = _load(service_importer, content=text)
    assert utility.normalize_plan_numbering(plan, SOURCE) is plan


def test_inline_numbering_preserves_numeric_facts_and_source_counts(service_importer):
    text = "1. Доход 42 млн рублей. 2. Снижение на -5%, дата 22.09.2026, API v3.7."
    utility, plan = _load(service_importer, content=text)
    result = utility.normalize_plan_numbering(plan, SOURCE)
    assert result.slides[0].content == text.replace("1. ", "").replace("2. Снижение", "Снижение")
    assert utility.extract_fact_tokens(result.slides[0].content) == {"42", "5%", "22.09", "2026", "7"}
    assert utility.normalize_plan_numbering(plan, SOURCE + " 2 инструмента.") is plan


@pytest.mark.parametrize("unit,first,second", [
    ("USD", "затрат", "дохода"),
    ("EUR", "затрат", "дохода"),
    ("RUB", "затрат", "дохода"),
    ("gbp", "затрат", "дохода"),
    ("ГБ", "памяти", "памяти"),
    ("МБ", "памяти", "памяти"),
    ("GB", "памяти", "памяти"),
    ("MiB", "памяти", "памяти"),
    ("гигабайта", "памяти", "памяти"),
    ("место", "в регионе", "в стране"),
    ("ранг", "в регионе", "в стране"),
])
@pytest.mark.parametrize("separator", ["\n", ". ", " → "])
def test_currency_memory_units_and_ranks_remain_numeric_facts(
    service_importer, unit, first, second, separator,
):
    text = f"1. {unit} {first}{separator}2. {unit} {second}."
    utility, plan = _load(service_importer, content=text)

    result = utility.normalize_plan_numbering(plan, SOURCE)

    assert result is plan
    assert utility.extract_fact_tokens(result.slides[0].content) == {"1", "2"}
    if separator == "\n":
        utility, plan = _load(service_importer, titles=text.splitlines())
        assert utility.normalize_plan_numbering(plan, SOURCE) is plan
