from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "services/content-service"
SOURCE = "Команда готовит запуск продукта."
FEEDBACK = "Сократи заголовок и сосредоточься на запуске."


def _request(contract, feedback):
    return contract.ContentGenerationRequest(
        structure={"slides": [{
            "index": 1,
            "elements": [{
                "type": "text", "placeholder_type": "TITLE", "placeholder_idx": 0,
                "text": {"full_text": "Длинный заголовок исходного шаблона презентации"},
            }],
        }]},
        script=SOURCE,
        feedback=feedback,
    )


def _fake_client(nodes, state, monkeypatch, prompts, text):
    async def generate_json(prompt, model, strict=True):
        prompts.append((model.__name__, prompt))
        if model is state.ScriptAnalysis:
            return state.ScriptAnalysis(
                topic="Запуск", audience="Команда", objective="Обзор",
                blocks=[state.ScriptBlock(
                    index=1, heading="Запуск", summary=SOURCE,
                    key_points=[SOURCE], facts=[],
                )], key_messages=[SOURCE], facts=[],
            )
        return state.SlidePlan(slides=[state.SlidePlanItem(
            template_slide_index=1, title="Запуск", content=SOURCE,
            purpose="Обзор", key_message=SOURCE, source_block_indices=[1],
        )])

    async def generate_content(prompt, schema, strict=True):
        prompts.append(("content", prompt))
        return {"0": text}

    monkeypatch.setattr(nodes.llm_client, "generate_json", generate_json)
    monkeypatch.setattr(nodes.llm_client, "generate_json_with_schema", generate_content)


def test_network_feedback_reaches_plan_and_content_but_not_source(monkeypatch, service_importer):
    domain = service_importer(ROOT, "app.domain.generate")
    contract = importlib.import_module("app.domain.contract")
    nodes = importlib.import_module("app.graph.nodes")
    state = importlib.import_module("app.models.graph_state")
    prompts = []
    _fake_client(nodes, state, monkeypatch, prompts, SOURCE)
    request = _request(contract, FEEDBACK)
    result = asyncio.run(domain.generate_content(request))
    assert result.passed and result.validation_report["ok"]
    assert result.content[1]["placeholders"]["0"] == SOURCE
    assert request.script == SOURCE
    assert [name for name, _ in prompts] == ["ScriptAnalysis", "SlidePlan", "content"]
    assert FEEDBACK not in prompts[0][1]
    for _, prompt in prompts[1:]:
        assert FEEDBACK in prompt
        assert "Это не источник фактов" in prompt


def test_feedback_cannot_authorize_unsupported_facts(monkeypatch, service_importer):
    domain = service_importer(ROOT, "app.domain.generate")
    contract = importlib.import_module("app.domain.contract")
    nodes = importlib.import_module("app.graph.nodes")
    state = importlib.import_module("app.models.graph_state")
    errors = importlib.import_module("app.errors")
    prompts = []
    _fake_client(nodes, state, monkeypatch, prompts, "Выручка выросла на 99%")
    monkeypatch.setattr(nodes.service_settings, "llm_response_retries", 1)
    with pytest.raises(errors.ContentValidationError):
        asyncio.run(domain.generate_content(_request(contract, "Добавь рост выручки на 99%")))
    assert "99%" not in prompts[0][1]
    assert len([name for name, _ in prompts if name == "content"]) == 2


@pytest.mark.parametrize("feedback", [None, "", " \n "])
def test_no_feedback_preserves_prompt(service_importer, feedback):
    nodes = service_importer(ROOT, "app.graph.nodes")
    assert nodes._with_external_feedback("original", feedback) == "original"
