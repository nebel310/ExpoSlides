from __future__ import annotations

import copy
import importlib
from pathlib import Path

import pytest
from pydantic import ValidationError

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


def _load(service_importer, combined):
    utility = service_importer(CONTENT_SERVICE_ROOT, "app.utils.unique_plan_schema")
    graph = importlib.import_module("app.models.graph_state")
    base = importlib.import_module("app.graph.fast").CombinedDraft if combined else graph.SlidePlan
    return utility, base


def _item(title="Тема"):
    return {
        "title": title, "content": "Содержание темы", "purpose": "Описать тему",
        "key_message": "Основная мысль", "source_block_indices": [3], "layout_type": None,
    }


def _payload(slides, combined):
    plan = {"slides": slides}
    if not combined:
        return plan
    return {"analysis": {
        "topic": "Тема", "audience": "", "objective": "", "blocks": [{
            "index": 3, "heading": "Тема", "summary": "Содержание темы",
            "key_points": ["Основная мысль"], "facts": [],
        }], "key_messages": ["Основная мысль"], "facts": [],
    }, "plan": plan}


@pytest.mark.parametrize("combined", [False, True])
def test_wire_schema_has_unique_index_keys_and_preserves_canonical_model_fields(
    service_importer, combined,
):
    utility, base = _load(service_importer, combined)
    original = base.model_json_schema()
    model = utility.unique_plan_model(base, [1, 2, 3, 4], [2, 4], 3, combined)

    schema = model.model_json_schema()
    slides = utility._slides_schema(schema, combined)
    assert base.model_json_schema() == original
    assert model.model_fields.keys() == base.model_fields.keys()
    assert slides["type"] == "object"
    assert list(slides["properties"]) == ["1", "2", "3", "4"]
    assert slides["required"] == ["2", "4"]
    assert slides["additionalProperties"] is False
    assert slides["minProperties"] == 2
    assert slides["maxProperties"] == 3
    entry = utility._resolve(schema, slides["properties"]["2"])
    assert "template_slide_index" not in entry["properties"]
    assert "template_slide_index" not in entry["required"]
    assert entry["additionalProperties"] is False
    assert entry["properties"]["source_block_indices"]["minItems"] == 1
    assert "pattern" not in str(schema)


@pytest.mark.parametrize("combined", [False, True])
def test_keyed_response_preserves_order_data_and_input_without_changing_saved_contract(
    service_importer, combined,
):
    utility, base = _load(service_importer, combined)
    model = utility.unique_plan_model(base, [1, 2, 3], [1, 3], 3, combined)
    payload = _payload({"3": _item("Первая тема"), "1": _item("Вторая тема")}, combined)
    snapshot = copy.deepcopy(payload)

    result = model.model_validate(payload)

    plan = result.plan if combined else result
    assert [item.template_slide_index for item in plan.slides] == [3, 1]
    assert [item.title for item in plan.slides] == ["Первая тема", "Вторая тема"]
    assert all(item.source_block_indices == [3] for item in plan.slides)
    assert payload == snapshot
    saved = result.model_dump()
    assert isinstance((saved["plan"] if combined else saved)["slides"], list)
    assert base.model_validate(saved).model_dump() == saved


@pytest.mark.parametrize("combined", [False, True])
@pytest.mark.parametrize("slides", [
    {}, {"0": _item()}, {"01": _item()}, {"9": _item()}, {1: _item()},
    {"1": []}, {"1": "Тема"}, {"1": None},
    {"1": {**_item(), "template_slide_index": 1}},
    {"1": {**_item(), "template_slide_index": 2}},
    {"1": {**_item(), "source_block_indices": []}},
    {"1": {**_item(), "title": ""}},
])
def test_invalid_keyed_responses_are_rejected_locally(service_importer, combined, slides):
    utility, base = _load(service_importer, combined)
    model = utility.unique_plan_model(base, [1, 2], [], 2, combined)

    with pytest.raises(ValidationError):
        model.model_validate(_payload(slides, combined))


@pytest.mark.parametrize("combined", [False, True])
def test_required_keys_and_maximum_are_checked_even_if_provider_ignores_schema(
    service_importer, combined,
):
    utility, base = _load(service_importer, combined)
    model = utility.unique_plan_model(base, [1, 2, 3], [2], 2, combined)

    with pytest.raises(ValidationError, match="обязательные"):
        model.model_validate(_payload({"1": _item()}, combined))
    with pytest.raises(ValidationError, match="Количество"):
        model.model_validate(_payload({str(i): _item() for i in (1, 2, 3)}, combined))


@pytest.mark.parametrize("combined", [False, True])
def test_keyed_entry_unknown_fields_are_rejected_instead_of_silently_dropped(
    service_importer, combined,
):
    utility, base = _load(service_importer, combined)
    model = utility.unique_plan_model(base, [1, 2], [], 2, combined)
    item = {**_item(), "invented_property": "Содержимое неизвестного поля"}

    with pytest.raises(ValidationError, match="неизвестные поля"):
        model.model_validate(_payload({"1": item}, combined))


@pytest.mark.parametrize("combined", [False, True])
def test_legacy_list_keeps_existing_extra_property_handling(service_importer, combined):
    utility, base = _load(service_importer, combined)
    model = utility.unique_plan_model(base, [1, 2], [], 2, combined)
    original = _payload([{
        **_item(), "template_slide_index": 1, "legacy_extra": "Прежнее дополнительное поле",
    }], combined)

    assert model.model_validate(original).model_dump() == base.model_validate(original).model_dump()


@pytest.mark.parametrize("combined", [False, True])
def test_legacy_list_is_accepted_without_silently_deduplicating_it(service_importer, combined):
    utility, base = _load(service_importer, combined)
    model = utility.unique_plan_model(base, [1, 2], [], 2, combined)
    original = _payload([{**_item(), "template_slide_index": 1}] * 2, combined)

    result = model.model_validate(original)

    assert result.model_dump() == base.model_validate(original).model_dump()
    plan = result.plan if combined else result
    assert [item.template_slide_index for item in plan.slides] == [1, 1]


def test_custom_base_schema_source_block_constraints_survive_wire_transformation(service_importer):
    utility, base = _load(service_importer, False)

    class CorrectedPlan(base):
        @classmethod
        def model_json_schema(cls, *args, **kwargs):
            schema = super().model_json_schema(*args, **kwargs)
            item = utility._resolve(schema, schema["properties"]["slides"]["items"])
            item["properties"]["source_block_indices"]["items"]["enum"] = [3, 7]
            schema["properties"]["slides"]["minItems"] = 2
            schema["properties"]["slides"]["maxItems"] = 3
            return schema

    model = utility.unique_plan_model(CorrectedPlan, [1, 2, 3, 4], [], 4, False)
    schema = model.model_json_schema()
    slides = schema["properties"]["slides"]
    item = utility._resolve(schema, slides["properties"]["1"])

    assert item["properties"]["source_block_indices"]["items"]["enum"] == [3, 7]
    assert slides["minProperties"] == 2
    assert slides["maxProperties"] == 3
    with pytest.raises(ValidationError, match="Количество"):
        model.model_validate({"slides": {"1": _item()}})


@pytest.mark.parametrize("allowed,required,limit", [
    ([], [], 1), ([0, 1], [], 2), ([1, 1], [], 2), ([1], [2], 1),
    ([1], [1, 1], 1), ([True], [], 1), ([1, 2], [1, 2], 1), ([1], [], 0),
])
def test_invalid_internal_configuration_fails_before_requests(
    service_importer, allowed, required, limit,
):
    utility, base = _load(service_importer, False)

    with pytest.raises(ValueError):
        utility.unique_plan_model(base, allowed, required, limit, False)
