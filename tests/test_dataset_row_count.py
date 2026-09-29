"""Наборы данных больше прежнего лимита проходят общий контракт без обрезки."""

import pytest
from pydantic import ValidationError

from exposlides.design_models import Dataset, DesignRequest


def test_large_dataset_survives_request_roundtrip():
    rows = [[f"{index:04d}", index / 10] for index in range(1001)]
    dataset = Dataset(id="data-1", name="sales", source="sales.csv",
                      columns=["Код", "Выручка, млн руб."], rows=rows)
    request = DesignRequest(script="Показать продажи", datasets=[dataset])
    restored = DesignRequest.model_validate_json(request.model_dump_json())
    assert restored.datasets[0].rows == rows
    assert restored.datasets[0].unit == ""
    assert "maxItems" not in Dataset.model_json_schema()["properties"]["rows"]


@pytest.mark.parametrize("rows", [[], [["001"]], [["001", float("inf")]]])
def test_row_count_change_keeps_structure_and_value_validation(rows):
    with pytest.raises(ValidationError):
        Dataset(id="data", name="sales", source="sales.csv",
                columns=["Код", "Выручка"], rows=rows)
