from __future__ import annotations

from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


@pytest.mark.parametrize("marker", ["-", "–", "—", "*", "•"])
def test_remove_only_bullet_before_text_preserving_words_and_line_breaks(
    service_importer, marker,
):
    module = service_importer(SERVICE_ROOT, "app.utils.list_formatting")
    value = f"{marker} Маршрутизатор — распределение запросов.\r\n  {marker} Не отключать API."
    assert module.normalize_list_formatting(value) == (
        "Маршрутизатор — распределение запросов.\r\n  Не отключать API."
    )


@pytest.mark.parametrize("value", [
    "- 18%", "– 18 млн рублей", "— ₽42", "+ EBITDA", "1. Доходы", "2) Расходы",
    "−18%", "-18%", "AI-агенты", "Текст — пояснение", "\n\n", "", "- ",
])
def test_ambiguous_signs_numbering_and_other_text_remain_unchanged(service_importer, value):
    module = service_importer(SERVICE_ROOT, "app.utils.list_formatting")
    assert module.normalize_list_formatting(value) == value


def test_bullet_removal_does_not_remove_numbers_or_negation(service_importer):
    module = service_importer(SERVICE_ROOT, "app.utils.list_formatting")
    text = "- Выручка не выросла: 18 млн рублей.\n• API недоступен."
    assert module.normalize_list_formatting(text) == (
        "Выручка не выросла: 18 млн рублей.\nAPI недоступен."
    )
