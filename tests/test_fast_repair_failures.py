from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest
from gigachat.exceptions import AuthenticationError

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
SOURCE = "Команда готовит запуск продукта и описывает стратегию развития."
FITTING = "Команда готовит запуск продукта"
PRESERVED = "Стратегия развития продукта"


def _load(service_importer):
    fast = service_importer(CONTENT_SERVICE_ROOT, "app.graph.fast")
    graph = importlib.import_module("app.models.graph_state")
    presentation = importlib.import_module("app.models.presentation")
    llm = importlib.import_module("app.chains.llm")
    state = graph.ContentGraphState(
        script=SOURCE,
        presentation=presentation.PresentationData(slides=[presentation.SlideData(
            index=1, placeholders=[presentation.PlaceholderData(
                idx=index, placeholder_type="BODY", max_length=40,
            ) for index in range(3)],
        )]),
    )
    draft = {
        "analysis": {
            "topic": "Запуск продукта", "audience": "", "objective": "",
            "blocks": [{
                "index": 1, "heading": "Стратегия запуска", "summary": SOURCE,
                "key_points": [SOURCE], "facts": [],
            }],
            "key_messages": [SOURCE], "facts": [],
        },
        "plan": {"slides": [{
            "template_slide_index": 1, "title": "Стратегия запуска", "content": SOURCE,
            "purpose": "Раскрыть стратегию", "key_message": SOURCE,
            "source_block_indices": [1],
        }]},
    }
    return fast, llm, state, draft


class RepairFailureClient:
    def __init__(self, draft, repair, *, fail_candidates=False):
        self.draft = draft
        self.repair = repair
        self.fail_candidates = fail_candidates
        self.calls = []

    async def generate_json(self, prompt, model, strict=True):
        return model.model_validate(self.draft)

    async def generate_json_object(self, prompt, schema, strict=True, *, model=None):
        self.calls.append((prompt, schema))
        if len(self.calls) == 1:
            return {"field_0000": SOURCE, "field_0001": SOURCE, "field_0002": PRESERVED}
        if len(self.calls) == 2:
            if isinstance(self.repair, Exception):
                raise self.repair
            return self.repair
        assert len(self.calls) <= 4
        candidate = SOURCE if self.fail_candidates else FITTING
        if len(self.calls) == 4:
            return {alias: candidate for alias in schema["required"]}
        return {alias: [candidate] * 3 for alias in schema["required"]}


@pytest.mark.parametrize("failure_kind", ["extra", "missing", "type", "malformed"])
def test_content_repair_failure_can_use_single_final_stage(
    monkeypatch, service_importer, failure_kind,
):
    fast, llm, state, draft = _load(service_importer)
    responses = {
        "extra": {
            "field_0000": FITTING, "field_0001": FITTING, "field_0002": "Перезапись",
        },
        "missing": {"field_0000": FITTING},
        "type": {"field_0000": FITTING, "field_0001": {"text": "Неверный тип"}},
        "malformed": llm.InvalidLLMGenerationError("malformed JSON"),
    }
    client = RepairFailureClient(draft, responses[failure_kind])
    monkeypatch.setattr(fast, "fast_llm_client", client)

    result = asyncio.run(fast.generate_fast(state))

    assert result["validation"].ok
    assert result["content"][1].placeholders == {"0": FITTING, "1": FITTING, "2": PRESERVED}
    assert len(client.calls) == 3
    expected_final = ["field_0001"] if failure_kind in {"missing", "type"} else [
        "field_0000", "field_0001",
    ]
    assert client.calls[-1][1]["required"] == expected_final
    assert "Перезапись" not in client.calls[-1][0]
    assert "Неверный тип" not in client.calls[-1][0]


def test_repair_failure_then_failed_candidates_stops_with_typed_error(monkeypatch, service_importer):
    fast, _, state, draft = _load(service_importer)
    client = RepairFailureClient(draft, {"unknown": "Неверное поле"}, fail_candidates=True)
    monkeypatch.setattr(fast, "fast_llm_client", client)

    with pytest.raises(fast.ContentValidationError, match="нет короткого текста"):
        asyncio.run(fast.generate_fast(state))

    assert len(client.calls) == 4


@pytest.mark.parametrize("cause", [
    ConnectionError("connection failed"),
    AuthenticationError("https://example.test", 401, b"unauthorized", None),
    TimeoutError("timeout"),
])
def test_transport_auth_and_timeout_do_not_trigger_content_recovery(
    monkeypatch, service_importer, cause,
):
    fast, _, state, draft = _load(service_importer)
    error = fast.LLMGenerationError("request failed")
    error.__cause__ = cause
    client = RepairFailureClient(draft, error)
    monkeypatch.setattr(fast, "fast_llm_client", client)

    with pytest.raises(fast.LLMGenerationError) as raised:
        asyncio.run(fast.generate_fast(state))

    assert raised.value is error
    assert len(client.calls) == 2
