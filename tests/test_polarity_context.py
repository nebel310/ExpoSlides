"""Полярность сопоставляется с исходными утверждениями, включая несколько разделов."""

from pathlib import Path

import pytest

from exposlides.design_content import extractive_plan, source_excerpts, validate_story
from exposlides.design_models import DesignRequest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
AGENT_SOURCE = (
    "Экосистема LangChain — это не один инструмент, а набор компонентов.\r\n\r\n"
    "Для простых задач подойдет один агент с инструментами."
)


@pytest.mark.parametrize("generated", [
    AGENT_SOURCE,
    "Для простых задач подойдет один агент с инструментами.\n"
    "Экосистема LangChain — это не один инструмент, а набор компонентов.",
    "Для простых задач подойдет один агент с инструментами.",
    "Для простых задач достаточно одного агента с инструментами.",
    "Один агент с инструментами подходит для простых задач.",
    "Экосистема LangChain — это не один инструмент, а набор компонентов.\n"
    "Для простых задач достаточно одного агента с инструментами.",
    "Экосистема LangChain — это не один инструмент, а набор компонентов.\n"
    "Один агент с инструментами подходит для простых задач.",
])
def test_supported_claims_do_not_contradict_unrelated_source_negation(
    service_importer, generated,
):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.utils.fact_grounding")
    assert module.semantic_content_issues(AGENT_SOURCE, generated) == []


def test_extractive_plan_preserves_context_across_source_sections():
    request = DesignRequest(script=AGENT_SOURCE, mode="extractive", slide_count=2)
    excerpts = source_excerpts(request.script)
    plan = extractive_plan(request, excerpts)
    assert len(excerpts) == len(plan.slides) == 2
    assert validate_story(plan, request, excerpts) == []


@pytest.mark.parametrize(("source", "generated"), [
    ("Компания не хранит персональные данные.", "Компания хранит персональные данные."),
    ("Компания хранит персональные данные.", "Компания не хранит персональные данные."),
    (
        "Компания не хранит персональные данные.\n\nМодуль хранит персональные данные.",
        "Компания хранит персональные данные.\n\nМодуль хранит персональные данные.",
    ),
    (
        "Компания хранит персональные данные.\n\nМодуль не хранит персональные данные.",
        "Компания не хранит персональные данные.\n\nМодуль не хранит персональные данные.",
    ),
    (
        "Компания не хранит персональные данные.",
        "Компания не хранит персональные данные. Компания хранит персональные данные.",
    ),
    (
        "Компания хранит персональные данные.",
        "Компания хранит персональные данные. Компания не хранит персональные данные.",
    ),
    (AGENT_SOURCE, AGENT_SOURCE.replace("не один инструмент", "один инструмент")),
    (AGENT_SOURCE, AGENT_SOURCE.replace("подойдет один агент", "подойдет не один агент")),
    (
        AGENT_SOURCE,
        "Экосистема LangChain — это один инструмент. "
        "Один агент с инструментами подходит для простых задач.",
    ),
    (
        AGENT_SOURCE,
        "Экосистема LangChain — это не один инструмент, а набор компонентов. "
        "Не один агент с инструментами подходит для простых задач.",
    ),
    ("The service does not store personal data.", "The service does store personal data."),
    ("The service stores personal data.", "The service never stores personal data."),
])
def test_new_polarity_changes_are_rejected_even_when_supported_claims_remain(
    service_importer, source, generated,
):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.utils.fact_grounding")
    assert any("отрицание" in issue for issue in module.semantic_content_issues(source, generated))
