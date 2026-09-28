from __future__ import annotations

import asyncio
import importlib
from decimal import Decimal
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


def _validate(service_importer, source, generated, *, required_messages=None):
    validation = service_importer(CONTENT_SERVICE_ROOT, "app.utils.validation")
    graph = importlib.import_module("app.models.graph_state")
    models = importlib.import_module("app.models.presentation")
    presentation = models.PresentationData(slides=[models.SlideData(
        index=1, placeholders=[models.PlaceholderData(idx=0, placeholder_type="BODY")],
    )])
    return asyncio.run(validation.ContentValidator.validate(
        presentation, {1: graph.GeneratedSlideContent(placeholders={"0": generated})},
        {1}, source, required_messages,
    ))


@pytest.mark.parametrize(("source", "generated", "issue"), [
    (
        "Выручка компании составила 10 млн рублей, прибыль компании составила 2 млн рублей.",
        "Выручка компании составила 2 млн рублей, прибыль компании составила 10 млн рублей.",
        "связь показателя",
    ),
    (
        "Компания не хранит персональные данные пользователей. Платформа поддерживает интеграцию.",
        "Компания хранит персональные данные пользователей. Платформа поддерживает интеграцию.",
        "отрицание",
    ),
    (
        "Выручка компании составила 10 млн рублей. Платформа поддерживает интеграцию данных.",
        "Выручка компании составила 10 млрд рублей. Платформа поддерживает интеграцию данных.",
        "связь показателя",
    ),
    (
        "Платформа поддерживает интеграцию корпоративных данных. "
        "Следующий этап — обучение сотрудников и региональное расширение.",
        "Платформа поддерживает интеграцию корпоративных данных.",
        "обязательное сообщение",
    ),
    (
        "Температура воздуха составила −10 градусов. Измерения проведены утром.",
        "Температура воздуха составила 10 градусов. Измерения проведены утром.",
        "связь показателя",
    ),
    (
        "В 2025 году выручка составила 10 млн рублей. В 2026 году выручка составила 20 млн рублей.",
        "В 2025 году выручка составила 20 млн рублей. В 2026 году выручка составила 10 млн рублей.",
        "связь показателя",
    ),
    (
        "Выручка компании Альфа составила 10 млн рублей. "
        "Выручка компании Бета составила 20 млн рублей.",
        "Выручка компании Альфа составила 20 млн рублей. "
        "Выручка компании Бета составила 10 млн рублей.",
        "связь показателя",
    ),
    (
        "Бюджет проекта составляет 10 млн рублей. Расходы команды составляют 2 млн долларов.",
        "Бюджет проекта составляет 10 млн долларов. Расходы команды составляют 2 млн рублей.",
        "связь показателя",
    ),
])
def test_integrated_validator_rejects_semantic_corruption(
    service_importer, source, generated, issue,
):
    report = _validate(service_importer, source, generated)
    assert not report.ok
    assert any(issue in text for text in report.issues)


@pytest.mark.parametrize(("source", "generated"), [
    (
        "Выручка компании составила 10 млн рублей, прибыль компании составила 2 млн рублей.",
        "Прибыль компании — 2 млн рублей. Выручка компании — 10 млн рублей.",
    ),
    (
        "Компания не хранит персональные данные пользователей. Платформа поддерживает интеграцию.",
        "Платформа поддерживает интеграцию. Компания не хранит персональные данные пользователей.",
    ),
    (
        "Платформа поддерживает интеграцию корпоративных данных. "
        "Следующий этап — обучение сотрудников и региональное расширение.",
        "Платформа поддерживает интеграцию корпоративных данных. "
        "Далее: обучить сотрудников, расшириться в регионах.",
    ),
    (
        "Команда готовит запуск продукта и описывает стратегию развития. "
        "Дополнительное пояснение раскрывает подробности обсуждения и историю исследования.",
        "Команда готовит запуск продукта и описывает стратегию развития.",
    ),
])
def test_integrated_validator_accepts_condensed_reordered_content(
    service_importer, source, generated,
):
    report = _validate(service_importer, source, generated)
    assert report.ok, report.issues


def test_explicit_required_message_is_checked(service_importer):
    source = "Команда развивает платформу анализа данных. Поддержка локального развёртывания."
    report = _validate(
        service_importer, source, "Команда развивает платформу анализа данных.",
        required_messages=["Поддержка локального развёртывания"],
    )
    assert any("обязательное сообщение" in issue for issue in report.issues)


def test_record_preserves_decimal_scale_unit_period_and_provenance(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.utils.fact_grounding")
    source = "В 2026 году выручка компании Альфа составила 10,5 млн рублей."
    records = module.extract_fact_records(source)
    assert len(records) == 1
    fact = records[0]
    assert fact.metric == "revenue"
    assert fact.value == Decimal("10500000")
    assert fact.unit == "RUB"
    assert fact.period == "2026"
    assert fact.entity == "альфа"
    assert source[slice(*fact.source_span)] == "10,5 млн рублей"


def test_equivalent_scale_not_flagged_by_semantic_layer(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.utils.fact_grounding")
    assert not module.semantic_content_issues(
        "Выручка составила 1 млн рублей.", "Выручка — 1000 тыс. рублей.",
    )


def test_source_negation_does_not_apply_to_different_object(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.utils.fact_grounding")
    assert not module.semantic_content_issues(
        "Компания не хранит персональные данные. Компания хранит агрегаты.",
        "Компания не хранит персональные данные. Компания хранит агрегаты.",
    )


def test_source_negation_with_positive_exception_is_not_rejected(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.utils.fact_grounding")
    source = "Компания не хранит персональную информацию, но хранит агрегированную статистику."
    assert not module.semantic_content_issues(source, source)
