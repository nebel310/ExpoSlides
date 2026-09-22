from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


def _terms(service_importer):
    return service_importer(CONTENT_SERVICE_ROOT, "app.utils.short_labels").grounded_short_terms


def test_speaker_sized_field_can_use_whole_terms_without_a_colon_or_dash(service_importer):
    terms = _terms(service_importer)

    assert terms(
        "Проектирование универсальных агентов с LangChain и LangGraph",
        "Сегодня рассмотрим фреймворки LangChain и LangGraph для создания агентов.",
        16,
    ) == ["LangChain", "LangGraph"]


def test_preserves_spelling_order_and_deduplicates_repeated_terms(service_importer):
    terms = _terms(service_importer)

    assert terms(
        "ReAct, API, ReAct и LangChain. Снова API и LANGCHAIN.",
        "LangChain использует API и ReAct.",
        12,
    ) == ["ReAct", "API", "LangChain"]


@pytest.mark.parametrize("limit", [0, -1, 4, 8])
def test_does_not_truncate_a_term_to_fit(service_importer, limit):
    terms = _terms(service_importer)

    assert terms("LangChain и LangGraph", "LangChain и LangGraph", limit) == []


@pytest.mark.parametrize("source", [
    "OpenAPI помогает создавать интерфейсы.",
    "APIClient помогает создавать интерфейсы.",
    "API-клиент помогает создавать интерфейсы.",
    "API‑клиент помогает создавать интерфейсы.",
    "API‐клиент помогает создавать интерфейсы.",
    "test_API помогает создавать интерфейсы.",
    "API2 помогает создавать интерфейсы.",
])
def test_source_attestation_requires_a_whole_token(service_importer, source):
    terms = _terms(service_importer)

    assert terms("API помогает создавать интерфейсы.", source, 16) == []


@pytest.mark.parametrize("original", [
    "OpenAPI", "APIClient", "API-клиент", "API‑клиент", "API‐клиент", "API2", "test_API",
])
def test_does_not_extract_a_fragment_of_an_original_compound(service_importer, original):
    terms = _terms(service_importer)

    assert terms(original, "Тема — API.", 16) == []


def test_does_not_pick_arbitrary_words_or_unknown_named_terms(service_importer):
    terms = _terms(service_importer)

    assert terms(
        "Архитектура агента, разработка, John Smith, production, Tools и UnknownGraph",
        "Архитектура агента, разработка, John Smith, production, Tools и LangGraph",
        16,
    ) == []


def test_keeps_a_complete_named_compound_when_it_fits(service_importer):
    terms = _terms(service_importer)

    assert terms("LangChain-Core", "Используем LangChain-Core.", 14) == ["LangChain-Core"]
    assert terms("LangChain-Core", "Используем LangChain-Core.", 9) == []


def test_can_use_exact_acronym_with_case_insensitive_source_spelling(service_importer):
    terms = _terms(service_importer)

    assert terms("LLM и RAG", "В системе используются llm и rag.", 3) == ["LLM", "RAG"]
