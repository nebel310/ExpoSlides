from __future__ import annotations

from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


@pytest.mark.parametrize(("source", "generated"), [
    (
        "В формате PPTX слайды должны состоять из нативных объектов, "
        "а не представлять собой одну растровую картинку.",
        "PPTX: нативные объекты, а не растровая картинка",
    ),
    (
        "Результат не является одной растровой картинкой.",
        "Результат — не растровая картинка.",
    ),
    (
        "Результат — не растровая картинка.",
        "Результат не является одной растровой картинкой.",
    ),
    (
        "The presentation is not a single raster image.",
        "The presentation is not raster imagery.",
    ),
])
def test_nominal_negation_survives_removed_linking_words(
    service_importer, source: str, generated: str,
) -> None:
    module = service_importer(CONTENT_SERVICE_ROOT, "app.utils.fact_grounding")
    assert not module.semantic_content_issues(source, generated)


@pytest.mark.parametrize(("source", "generated"), [
    (
        "PPTX: нативные объекты, а не растровая картинка.",
        "PPTX: нативные объекты, а растровая картинка.",
    ),
    (
        "Результат — растровая картинка.",
        "Результат — не растровая картинка.",
    ),
    (
        "Компания не хранит данные и передаёт данные партнёрам.",
        "Компания не хранит данные и не передаёт данные партнёрам.",
    ),
    (
        "Компания хранит персональные данные пользователей.",
        "Компания не хранит персональные данные пользователей.",
    ),
    (
        "Компания не хранит персональные данные пользователей.",
        "Компания хранит персональные данные пользователей.",
    ),
])
def test_nominal_scope_fix_preserves_genuine_negation_errors(
    service_importer, source: str, generated: str,
) -> None:
    module = service_importer(CONTENT_SERVICE_ROOT, "app.utils.fact_grounding")
    issues = module.semantic_content_issues(source, generated)
    assert any("Изменено отрицание" in issue for issue in issues), issues
