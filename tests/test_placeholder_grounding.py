import asyncio
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
SOURCE = (
    "Проектирование AI-агентов с использованием фреймворков LangChain и LangGraph. "
    "Архитектура агента включает модели, инструменты и память."
)


@pytest.mark.parametrize("label", [
    "FOOTER", "TITLE", "BODY", "field_0001", "Футер", "Колонтитул", "Нижний колонтитул",
    "Верхний колонтитул", "Плейсхолдер", "Заполнитель", "Текстовое поле",
])
def test_technical_field_labels_are_not_slide_content(service_importer, label: str) -> None:
    helper = service_importer(CONTENT_SERVICE_ROOT, "app.utils.placeholder_grounding")

    assert helper.placeholder_grounding_issues(SOURCE, label, "Заголовок презентации")
    assert not helper.placeholder_grounding_issues(f"Поле {label} хранит текст.", label, "")


def test_generic_empty_content_label_needs_source_support(service_importer) -> None:
    helper = service_importer(CONTENT_SERVICE_ROOT, "app.utils.placeholder_grounding")

    assert helper.placeholder_grounding_issues(SOURCE, "Основные моменты", "Обзор проекта")
    assert not helper.placeholder_grounding_issues(
        SOURCE + " Основные моменты: модели, инструменты, память.", "Основные моменты", "",
    )
    # Ограничение касается точной заглушки, не всех названий разделов.
    for caption in ("Обзор", "Итоги", "Выводы", "Основные моменты архитектуры агента"):
        assert not helper.placeholder_grounding_issues(SOURCE, caption, "Основной текст")


@pytest.mark.parametrize("hint", [
    "Имя докладчика", "Должность докладчика", "Название компании", "Название проекта",
    "Заголовок слайда", "Company name", "Speaker title", "Your name", "Click to add text",
])
def test_filling_hints_are_rejected_without_a_matching_template_cue(
    service_importer, hint: str,
) -> None:
    helper = service_importer(CONTENT_SERVICE_ROOT, "app.utils.placeholder_grounding")

    assert helper.placeholder_grounding_issues(SOURCE, hint, "Обзор архитектуры")
    assert not helper.placeholder_grounding_issues(f"Обязательное поле анкеты: {hint}.", hint, "")


@pytest.mark.parametrize("caption", [
    "Архитектура агента", "Задачи докладчика", "Роль инструментов", "Создание компании",
])
def test_fill_hint_check_does_not_reject_ordinary_topic_captions(
    service_importer, caption: str,
) -> None:
    helper = service_importer(CONTENT_SERVICE_ROOT, "app.utils.placeholder_grounding")

    assert not helper.placeholder_grounding_issues(SOURCE, caption, "Основной текст")


@pytest.mark.parametrize("cue", ["Имя докладчика", "ФИО", "Имя Фамилия", "Presenter name"])
def test_explicit_author_field_rejects_unanchored_name(service_importer, cue: str) -> None:
    helper = service_importer(CONTENT_SERVICE_ROOT, "app.utils.placeholder_grounding")

    issues = helper.placeholder_grounding_issues(SOURCE, "Александр Иванов", cue)

    assert len(issues) == 1
    assert "имя человека не подтверждено" in issues[0]


@pytest.mark.parametrize("value", ["Архитектура агента", "AI-агенты", "LangChain", "Разработка"])
def test_author_field_accepts_short_topical_caption(service_importer, value: str) -> None:
    helper = service_importer(CONTENT_SERVICE_ROOT, "app.utils.placeholder_grounding")

    assert not helper.placeholder_grounding_issues(SOURCE, value, "Имя докладчика")


def test_guard_is_scoped_to_person_cues_and_preserves_source_names(service_importer) -> None:
    helper = service_importer(CONTENT_SERVICE_ROOT, "app.utils.placeholder_grounding")

    assert not helper.placeholder_grounding_issues(
        SOURCE + " Докладчик — Александр Иванов.", "Александр Иванов", "Имя докладчика",
    )
    assert not helper.placeholder_grounding_issues(
        SOURCE, "Большие Модели", "Имя докладчика",
    )
    assert not helper.placeholder_grounding_issues(SOURCE, "Новая Архитектура", "Тема")
    assert helper.placeholder_grounding_issues(SOURCE, "John Smith", "Presenter name")
    assert helper.placeholder_grounding_issues(SOURCE, "Имя докладчика", "Имя докладчика")


@pytest.mark.parametrize("template_name", ["Такума Хаяши", "John Smith"])
def test_actual_template_person_name_does_not_authorize_copying_it(
    service_importer, template_name: str,
) -> None:
    helper = service_importer(CONTENT_SERVICE_ROOT, "app.utils.placeholder_grounding")

    assert helper.placeholder_grounding_issues(SOURCE, template_name, template_name)
    assert helper.placeholder_grounding_issues(SOURCE, "Александр Иванов", template_name)
    assert not helper.placeholder_grounding_issues(
        SOURCE + f" Докладчик — {template_name}.", template_name, template_name,
    )
    assert not helper.placeholder_grounding_issues(SOURCE, "Архитектура агента", template_name)


def test_validator_does_not_hide_author_hallucination_behind_grounded_title(service_importer) -> None:
    models = service_importer(CONTENT_SERVICE_ROOT, "app.models.presentation")
    graph = service_importer(CONTENT_SERVICE_ROOT, "app.models.graph_state")
    validator = service_importer(CONTENT_SERVICE_ROOT, "app.utils.validation").ContentValidator
    presentation = models.PresentationData(slides=[models.SlideData(index=1, placeholders=[
        models.PlaceholderData(idx=0, placeholder_type="TITLE", max_length=250),
        models.PlaceholderData(idx=28, placeholder_type="BODY", text="Имя докладчика", max_length=32),
    ])])
    content = {1: graph.GeneratedSlideContent(placeholders={
        "0": SOURCE, "28": "Александр Иванов",
    })}

    report = asyncio.run(validator.validate(presentation, content, {1}, SOURCE))

    assert not report.ok
    assert len(report.issues) == 1
    assert "placeholder 28" in report.issues[0]
    assert "имя человека не подтверждено" in report.issues[0]
