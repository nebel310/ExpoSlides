from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import httpx
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


def test_template_cover_budget_retries_overloaded_cover_without_losing_facts(
    service_importer, tmp_path,
):
    from tests.test_template_design import _profile

    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    profile = _profile(tmp_path)
    profile.patterns[0].name = "Титульный слайд"
    profile.patterns[0].slots[1].box.height = 12700 * 50
    good = _plan()
    good["slides"].append({**good["slides"][0], "id": "slide-2"})
    bad = json.loads(json.dumps(good))
    bad["slides"][0]["paragraphs"] = [SOURCE * 20]
    client = Client([bad, good])
    result = asyncio.run(module.generate(
        module.DesignRequest(script=SOURCE, slide_count=2), client, profile=profile,
    ))
    assert len(result.slides) == 2
    assert len(client.prompts) == 2
    assert '"first_slide": "cover"' in client.prompts[0]
    assert '"subtitle_max_characters"' in client.prompts[0]
    assert "не помещается на обложке" in client.prompts[1]
    assert SOURCE in result.slides[1].paragraphs


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
    with pytest.raises(errors.ContentValidationError, match="не прошёл проверку") as raised:
        asyncio.run(module.generate(module.DesignRequest(script=SOURCE, slide_count=1), client))
    assert len(client.prompts) == 3
    assert errors.content_error_code(raised.value) == "invalid_response"


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
    monkeypatch.chdir(tmp_path)
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


def _story_cli(service_importer, monkeypatch, tmp_path):
    # Settings читает только этот новый каталог, в котором нет .env.
    monkeypatch.chdir(tmp_path)
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    request_file = tmp_path / "request.json"
    request_file.write_text(module.DesignRequest(script=SOURCE, slide_count=1).model_dump_json(),
                            encoding="utf-8")
    output = tmp_path / "story.json"
    monkeypatch.setattr(module.sys, "argv", [
        "design_main", "--request", str(request_file), "--output", str(output),
    ])
    monkeypatch.setattr(module, "setup_logging", lambda: None)
    monkeypatch.setattr(module.settings, "llm_api_key", "hf_offline-test-key")
    monkeypatch.setattr(module.settings, "llm_fast_model", "qwen3.8-27b")
    closed = []

    async def close():
        closed.append(True)

    monkeypatch.setattr(module.fast_llm_client, "aclose", close)
    return module, output, closed


@pytest.mark.parametrize("kind,code,category", [
    ("invalid", 20, "invalid_response"), ("validation", 21, "content_validation"),
    ("timeout", 22, "timeout"), ("auth", 23, "auth"), ("network", 24, "network"),
    ("value_error", 1, "unknown"),
])
def test_story_cli_propagates_safe_typed_errors(
    service_importer, monkeypatch, tmp_path, capsys, kind, code, category,
):
    module, output, closed = _story_cli(service_importer, monkeypatch, tmp_path)
    llm = importlib.import_module("app.chains.llm")
    private = "private-key-and-source https://private-endpoint.test/v1"
    if kind == "invalid":
        error = llm.InvalidLLMGenerationError(private)
    elif kind == "validation":
        error = module.ContentValidationError(private)
    elif kind == "timeout":
        error = module.LLMGenerationError(private)
        error.__cause__ = httpx.ReadTimeout(private)
    elif kind == "auth":
        request = httpx.Request("POST", "https://private-endpoint.test/v1",
                                headers={"Authorization": "Bearer private-key-and-source"})
        error = module.LLMGenerationError(private)
        error.__cause__ = httpx.HTTPStatusError(
            private, request=request, response=httpx.Response(401, request=request),
        )
    elif kind == "network":
        error = module.LLMGenerationError(private)
        error.__cause__ = httpx.ConnectError(private)
    else:
        error = ValueError(private)

    async def generate(request):
        raise error

    monkeypatch.setattr(module, "generate", generate)
    assert module.main() == code
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == module.PUBLIC_ERROR_MESSAGES[category]
    assert "private-" not in captured.err
    assert closed == [True]
    assert not output.exists()
    assert not output.with_name("story-provenance.json").exists()


@pytest.mark.parametrize("failure,code,category", [
    ("missing_key", 23, "auth"), ("model", 25, "configuration"),
    ("metadata", 25, "configuration"),
])
def test_story_cli_preflight_failure_closes_client_without_calling_model(
    service_importer, monkeypatch, tmp_path, capsys, failure, code, category,
):
    module, output, closed = _story_cli(service_importer, monkeypatch, tmp_path)
    if failure == "missing_key":
        monkeypatch.setattr(module.settings, "llm_api_key", " ")
    elif failure == "model":
        monkeypatch.setattr(module.settings, "llm_fast_model", "private-unregistered-model")
    else:
        def broken_metadata(*args):
            raise ValueError("private-key-and-endpoint")
        monkeypatch.setattr(module, "role_metadata", broken_metadata)

    async def generate(request):
        pytest.fail("Preflight failure must not call the model")

    monkeypatch.setattr(module, "generate", generate)
    assert module.main() == code
    assert capsys.readouterr().err.strip() == module.PUBLIC_ERROR_MESSAGES[category]
    assert closed == [True]
    assert not output.exists()


def test_story_cli_real_timeout_cancels_generation_and_returns_timeout_code(
    service_importer, monkeypatch, tmp_path, capsys,
):
    module, output, closed = _story_cli(service_importer, monkeypatch, tmp_path)
    configuration = module.role_config("story") | {"timeout_seconds": 0.02}
    monkeypatch.setattr(module, "role_config", lambda role: configuration)
    cancelled = []

    async def generate(request):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    monkeypatch.setattr(module, "generate", generate)
    assert module.main() == 22
    assert cancelled == closed == [True]
    assert capsys.readouterr().err.strip() == module.PUBLIC_ERROR_MESSAGES["timeout"]
    assert not output.exists()


def test_story_cli_cleanup_failure_does_not_hide_original_error(
    service_importer, monkeypatch, tmp_path, capsys,
):
    module, output, _ = _story_cli(service_importer, monkeypatch, tmp_path)

    async def generate(request):
        raise module.ContentValidationError("private source")

    async def close():
        raise TimeoutError("private endpoint")

    monkeypatch.setattr(module, "generate", generate)
    monkeypatch.setattr(module.fast_llm_client, "aclose", close)
    assert module.main() == 21
    assert capsys.readouterr().err.strip() == module.PUBLIC_ERROR_MESSAGES["content_validation"]
    assert not output.exists()


def test_story_cli_keeps_validation_diagnostics_private_and_does_not_publish_plan(
    service_importer, monkeypatch, tmp_path, capsys,
):
    module, output, closed = _story_cli(service_importer, monkeypatch, tmp_path)
    bad = _plan()
    bad["slides"][0]["source_ids"] = ["invented-source"]
    calls = []

    async def reply(prompt, model):
        calls.append(True)
        return model.model_validate(bad)

    monkeypatch.setattr(module.fast_llm_client, "generate_json", reply)
    assert module.main() == 21
    assert len(calls) == 3
    assert closed == [True]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == module.PUBLIC_ERROR_MESSAGES["content_validation"]
    assert "invented-source" not in captured.err
    assert not output.exists()
    diagnostic = output.with_suffix(".diagnostics.json").read_text(encoding="utf-8")
    data = json.loads(diagnostic)
    assert data["code"] == "content_validation"
    assert any("Неизвестные ссылки" in issue for issue in data["issues"])
    assert data["last_validated_plan"]["slides"][0]["source_ids"] == ["invented-source"]
    assert "hf_offline-test-key" not in diagnostic
    assert "LLM_API_KEY" not in diagnostic
