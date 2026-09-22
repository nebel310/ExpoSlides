from __future__ import annotations

import asyncio
import copy
import importlib
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
SOURCE = "Команда готовит запуск продукта и описывает стратегию развития."


def _load(service_importer, specifications):
    fast = service_importer(CONTENT_SERVICE_ROOT, "app.graph.fast")
    graph = importlib.import_module("app.models.graph_state")
    presentation = importlib.import_module("app.models.presentation")
    state = graph.ContentGraphState(
        script=SOURCE,
        presentation=presentation.PresentationData(slides=[
            presentation.SlideData(index=index, placeholders=[
                presentation.PlaceholderData(idx=position, placeholder_type=kind, max_length=limit)
                for position, (kind, limit) in enumerate(fields)
            ]) for index, fields in specifications
        ]),
    )
    return fast, state


def _draft(fast, indices):
    return fast.CombinedDraft.model_validate({
        "analysis": {
            "topic": "Запуск продукта", "audience": "", "objective": "",
            "blocks": [{
                "index": 1, "heading": "Стратегия запуска", "summary": SOURCE,
                "key_points": [SOURCE], "facts": [],
            }],
            "key_messages": [SOURCE], "facts": [],
        },
        "plan": {"slides": [{
            "template_slide_index": index, "title": "Стратегия запуска",
            "content": SOURCE, "purpose": "Раскрыть стратегию", "key_message": SOURCE,
            "source_block_indices": [1],
        } for index in indices]},
    })


def _indices(plan):
    return [item.template_slide_index for item in plan.slides]


def test_duplicate_replaced_without_changing_content_or_retrying(monkeypatch, service_importer):
    fast, state = _load(service_importer, [
        (15, [("TITLE", 80), ("BODY", 200)]),
        (6, [("TITLE", 80), ("BODY", 210), ("FOOTER", 40)]),
    ])
    original = _draft(fast, [15, 15])
    original.plan.slides[1].purpose = "Раскрыть развитие"
    snapshot = original.model_dump()
    calls = []

    class Client:
        async def generate_json(self, prompt, model, strict=True):
            calls.append(prompt)
            return model.model_validate(copy.deepcopy(snapshot))

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    repaired = fast._repair_duplicate_template_indices(state, original.plan)
    budget = fast._RepairBudget()
    result = asyncio.run(fast._generate_outline(state, budget))

    assert _indices(repaired) == _indices(result.plan) == [15, 6]
    assert original.model_dump() == snapshot
    for before, after in zip(original.plan.slides, repaired.slides, strict=True):
        assert before.model_dump(exclude={"template_slide_index"}) == after.model_dump(
            exclude={"template_slide_index"},
        )
    assert fast.nodes._plan_validation_issues(
        repaired, state.presentation, original.analysis,
        state.settings.max_slides, state.script, state.user_mapping,
        state.settings.strict_user_mapping,
    ) == []
    assert len(calls) == 1
    assert budget.remaining == 1


def test_reserves_later_original_indices_and_allocates_distinct_replacements(service_importer):
    fields = [("TITLE", 80), ("BODY", 200)]
    fast, state = _load(service_importer, [(index, fields) for index in (15, 6, 7, 8)])
    plan = _draft(fast, [15, 15, 6, 15]).plan

    repaired = fast._repair_duplicate_template_indices(state, plan)

    assert _indices(repaired) == [15, 7, 6, 8]
    assert len(repaired.slides) == len(plan.slides)
    assert set(_indices(repaired)) <= {slide.index for slide in state.presentation.slides}


def test_capacity_distance_and_stable_index_tie_ignore_metadata(service_importer):
    fast, state = _load(service_importer, [
        (15, [("TITLE", 50), ("BODY", 150), ("FOOTER", 500)]),
        (9, [("TITLE", 50), ("BODY", 160)]),
        (6, [("TITLE", 50), ("BODY", 140), ("HEADER", 800), ("DATE", 80)]),
        (2, [("TITLE", 50), ("BODY", 110), ("SLIDE_NUMBER", 400)]),
    ])

    repaired = fast._repair_duplicate_template_indices(state, _draft(fast, [15, 15]).plan)

    assert _indices(repaired) == [15, 6]


@pytest.mark.parametrize("fields", [
    [("TITLE", 80), ("BODY", 100), ("BODY", 100)],
    [("TITLE", 80), ("SUBTITLE", 200)],
])
def test_incompatible_shape_uses_bounded_plan_repair_then_fails(
    monkeypatch, service_importer, fields,
):
    fast, state = _load(service_importer, [
        (15, [("TITLE", 80), ("BODY", 200)]), (6, fields),
    ])
    original = _draft(fast, [15, 15])
    calls = []

    class Client:
        async def generate_json(self, prompt, model, strict=True):
            calls.append(prompt)
            data = original.plan if "slides" in model.model_fields else original
            return model.model_validate(data.model_dump())

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    assert fast._repair_duplicate_template_indices(state, original.plan) is original.plan
    with pytest.raises(fast.PlanValidationError, match="уникальным"):
        asyncio.run(fast._generate_outline(state, fast._RepairBudget()))
    assert len(calls) == 2
    assert "<REJECTED_PLAN>" in calls[1]


@pytest.mark.parametrize("strict", [False, True])
def test_any_user_mapping_disables_automatic_replacement(service_importer, strict):
    fields = [("TITLE", 80), ("BODY", 200)]
    fast, state = _load(service_importer, [(15, fields), (6, fields)])
    state.user_mapping = {"6": {}}
    state.settings.strict_user_mapping = strict
    plan = _draft(fast, [15, 15]).plan

    assert fast._repair_duplicate_template_indices(state, plan) is plan
    assert _indices(plan) == [15, 15]


def test_duplicate_unknown_index_is_never_replaced(monkeypatch, service_importer):
    fields = [("TITLE", 80), ("BODY", 200)]
    fast, state = _load(service_importer, [(15, fields), (6, fields)])
    original = _draft(fast, [99, 99])
    calls = []

    class Client:
        async def generate_json(self, prompt, model, strict=True):
            calls.append(prompt)
            data = original.plan if "slides" in model.model_fields else original
            return model.model_validate(data.model_dump())

    monkeypatch.setattr(fast, "fast_llm_client", Client())
    assert fast._repair_duplicate_template_indices(state, original.plan) is original.plan
    with pytest.raises(fast.PlanValidationError, match="99"):
        asyncio.run(fast._generate_outline(state, fast._RepairBudget()))
    assert len(calls) == 2
