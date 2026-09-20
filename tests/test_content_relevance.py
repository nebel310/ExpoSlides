from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


def _report(service_importer, source, generated):
    validation = service_importer(CONTENT_SERVICE_ROOT, "app.utils.validation")
    models = importlib.import_module("app.models.graph_state")
    presentation = importlib.import_module("app.models.presentation")
    template = presentation.PresentationData(slides=[presentation.SlideData(
        index=1, placeholders=[presentation.PlaceholderData(idx=0)],
    )])
    content = {1: models.GeneratedSlideContent(placeholders={"0": generated})}
    return asyncio.run(validation.ContentValidator.validate(template, content, {1}, source))


def _distinct_context_words():
    return " ".join("материал" + chr(1072 + i // 10) + chr(1072 + i % 10) for i in range(100))


def test_long_source_does_not_require_copying_its_vocabulary(service_importer):
    summary = "Агенты используют инструменты сохраняют память"
    source = summary + " " + _distinct_context_words()
    assert _report(service_importer, source, summary).ok


@pytest.mark.parametrize("generated", ["Агенты", "", "Агенты Агенты Агенты"])
def test_repeating_one_shared_term_is_not_grounded(service_importer, generated):
    report = _report(service_importer, "Агенты используют инструменты сохраняют память", generated)
    assert not report.ok
    assert any("недостаточно связан" in issue for issue in report.issues)


def test_unrelated_padding_is_rejected_even_when_source_words_are_present(service_importer):
    source = "Агенты используют инструменты сохраняют память"
    report = _report(service_importer, source, source + " " + _distinct_context_words())
    assert not report.ok
    assert any("недостаточно связан" in issue for issue in report.issues)


@pytest.mark.parametrize("ending", ["Рост 20%", "Рост втрое", "Рост"])
def test_relevance_does_not_replace_fact_checks(service_importer, ending):
    source = "Агенты используют инструменты сохраняют память. Рост 18%"
    report = _report(service_importer, source, "Агенты используют инструменты сохраняют память. " + ending)
    assert not report.ok
    assert any("факт" in issue or "сравнения" in issue for issue in report.issues)
