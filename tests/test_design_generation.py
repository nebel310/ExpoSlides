from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"
SOURCE = "Команда развивает платформу анализа данных."


def _plan():
    return {
        "title": "Платформа анализа данных", "slides": [{
            "id": "slide-1", "title": "Платформа анализа данных", "paragraphs": [SOURCE],
            "source_ids": ["source-1"],
        }],
    }


class Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.prompts = []

    async def generate_json(self, prompt, model):
        self.prompts.append(prompt)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return model.model_validate(response)


def test_story_retries_malformed_structured_response(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    llm = importlib.import_module("app.chains.llm")
    client = Client([llm.InvalidLLMGenerationError("invalid"), _plan()])
    request = module.DesignRequest(script=SOURCE, slide_count=1)
    plan = asyncio.run(module.generate(request, client))
    assert plan.slides[0].source_ids == ["source-1"]
    assert len(client.prompts) == 2
    assert "JSON Schema" in client.prompts[1]


def test_story_retries_semantic_errors_and_keeps_original_request(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    bad = _plan()
    bad["slides"][0]["source_ids"] = ["invented-source"]
    client = Client([bad, _plan()])
    request = module.DesignRequest(script=SOURCE, slide_count=1, purpose="Объяснить продукт")
    result = asyncio.run(module.generate(request, client))
    assert result.slides[0].id == "slide-1"
    assert "Объяснить продукт" in client.prompts[1]
    assert "Неизвестные ссылки" in client.prompts[1]


def test_story_fails_after_bounded_invalid_replies(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    llm = importlib.import_module("app.chains.llm")
    errors = importlib.import_module("app.errors")
    client = Client([llm.InvalidLLMGenerationError("invalid")] * 3)
    with pytest.raises(errors.ContentValidationError, match="не прошёл проверку"):
        asyncio.run(module.generate(module.DesignRequest(script=SOURCE, slide_count=1), client))
    assert len(client.prompts) == 3


def test_story_does_not_retry_auth_or_network_failure_as_content(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    errors = importlib.import_module("app.errors")
    client = Client([errors.LLMGenerationError("provider failed")])
    with pytest.raises(errors.LLMGenerationError, match="provider failed"):
        asyncio.run(module.generate(module.DesignRequest(script=SOURCE, slide_count=1), client))
    assert len(client.prompts) == 1


@pytest.mark.parametrize("fails", [False, True])
def test_story_cli_saves_configured_alias_without_private_settings_only_on_success(
    service_importer, monkeypatch, tmp_path, capsys, fails,
):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    request_file = tmp_path / "request.json"
    request_file.write_text(module.DesignRequest(script=SOURCE, slide_count=1).model_dump_json(),
                            encoding="utf-8")
    output = tmp_path / "custom-name.json"
    monkeypatch.setattr(module.sys, "argv", [
        "design_main", "--request", str(request_file), "--output", str(output),
    ])
    monkeypatch.setattr(module, "setup_logging", lambda: None)
    monkeypatch.setattr(module.settings, "llm_fast_model", "qwen3.8-27b")
    monkeypatch.setattr(module.settings, "llm_api_key", "private-key-do-not-export")
    monkeypatch.setattr(module.settings, "llm_base_url", "https://private-endpoint.test/v1")
    closed = []

    async def generate(request):
        if fails:
            raise ValueError("invalid generated content")
        return module.ContentPlan.model_validate(_plan())

    async def close():
        closed.append(True)

    monkeypatch.setattr(module, "generate", generate)
    monkeypatch.setattr(module.fast_llm_client, "aclose", close)
    assert module.main() == int(fails)
    assert closed == [True]
    provenance_file = tmp_path / "story-provenance.json"
    if fails:
        assert not output.exists()
        assert not provenance_file.exists()
        assert "private-" not in capsys.readouterr().err
        return
    assert module.ContentPlan.model_validate_json(output.read_text(encoding="utf-8"))
    provenance = json.loads(provenance_file.read_text(encoding="utf-8"))
    assert provenance == module.role_metadata("story", "qwen3.8-27b")
    assert provenance["endpoint_model"] == "qwen3.8-27b"
    assert provenance["model"] == "Qwen/Qwen3.8-27B"
    assert set(provenance) == {
        "workflow_id", "workflow_version", "role", "model", "endpoint_model", "license",
        "parameters_billions", "registry_version", "prompt_sha256",
    }
    assert "private-" not in provenance_file.read_text(encoding="utf-8")
