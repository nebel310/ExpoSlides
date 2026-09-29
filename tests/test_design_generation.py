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
    client = Client([bad, {"cover_title": "Платформа", "cover_subtitle": "Анализ данных"}])
    result = asyncio.run(module.generate(
        module.DesignRequest(script=SOURCE, slide_count=2), client, profile=profile,
    ))
    assert len(result.slides) == 2
    assert len(client.prompts) == 2
    assert '"first_slide": "cover"' in client.prompts[0]
    assert '"subtitle_max_characters"' in client.prompts[0]
    assert "Все подробности обложки приложение сохранит" in client.prompts[1]
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


def test_story_repairs_only_returned_slides_and_validates_merged_plan(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    good = _plan()
    good['slides'].append({**good['slides'][0], 'id': 'slide-2'})
    bad = json.loads(json.dumps(good))
    bad['slides'][1]['source_ids'] = ['invented-source']
    repair = {'title': good['title'], 'slides': [good['slides'][1]]}
    client = Client([bad, repair])
    result = asyncio.run(module.generate(
        module.DesignRequest(script=SOURCE, slide_count=2), client,
    ))
    assert len(result.slides) == 2
    assert result.slides[0].model_dump() == module.ContentPlan.model_validate(bad).slides[0].model_dump()
    assert result.slides[1].source_ids == ['source-1']
    assert 'только исправленными слайдами' in client.prompts[1]
    assert 'previous_plan' in client.prompts[1]
    assert 'slide_count относится к объединённому плану' in client.prompts[1]
    assert 'Одного упоминания в notes недостаточно' in client.prompts[1]
    assert not module.validate_story(result, module.DesignRequest(script=SOURCE, slide_count=2),
                                     module.source_excerpts(SOURCE))


def test_story_repair_rejects_new_slide_ids_without_publishing_partial_plan(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    bad = _plan()
    bad['slides'][0]['source_ids'] = ['invented-source']
    unknown = _plan()
    unknown['slides'][0]['id'] = 'new-id'
    client = Client([bad, unknown, unknown])
    with pytest.raises(module.StoryValidationError):
        asyncio.run(module.generate(module.DesignRequest(script=SOURCE, slide_count=1), client))
    assert len(client.prompts) == 3


def test_wrong_slide_count_still_requires_a_complete_plan(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    wrong = _plan()
    good = _plan()
    good['slides'].append({**good['slides'][0], 'id': 'slide-2'})
    client = Client([wrong, good])
    result = asyncio.run(module.generate(module.DesignRequest(script=SOURCE, slide_count=2), client))
    assert len(result.slides) == 2
    assert 'полный исправленный ContentPlan' in client.prompts[1]


def test_compact_repairs_preserve_facts_and_validate_the_merged_plan(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    plan = module.ContentPlan.model_validate({"title": "Тема", "slides": [
        {"id": "slide-1", "title": "Платформа", "paragraphs": [SOURCE], "source_ids": ["source-1"]},
        {"id": "slide-2", "title": "Команда", "paragraphs": ["Команда"], "source_ids": ["source-1"]},
    ]})
    payload = {"sources": [{"id": "source-1", "text": SOURCE}], "template_layout": {
        "title_max_characters": 15, "subtitle_max_characters": 12,
    }}
    client = Client([{"cover_title": "Платформа", "cover_subtitle": "Анализ", "source_0": SOURCE}])
    result = asyncio.run(module._repair_fields(client, plan, payload, (True, payload["sources"])))
    assert len(result.slides) == 2
    assert result.slides[1].paragraphs[0] == "Команда"
    assert result.slides[1].paragraphs == ["Команда"]
    assert SOURCE in result.slides[1].notes
    assert SOURCE in result.slides[0].notes
    assert plan.slides[0].paragraphs == [SOURCE]
    assert not module.validate_story(result, module.DesignRequest(script=SOURCE, slide_count=2),
                                     module.source_excerpts(SOURCE))


def test_story_repairs_do_not_accept_unsupported_numbers(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    bad = _plan()
    bad["slides"][0]["paragraphs"] = ["Тема"]
    bad["slides"][0]["title"] = "Тема"
    invented = _plan()
    invented["slides"][0]["paragraphs"] = [SOURCE + " Рост 99%."]
    client = Client([bad, invented, bad])
    with pytest.raises(module.StoryValidationError):
        asyncio.run(module.generate(module.DesignRequest(script=SOURCE, slide_count=1), client))
    assert len(client.prompts) == 3


def test_story_prompt_receives_actual_layout_word_budgets(service_importer, tmp_path):
    from tests.test_template_design import _profile

    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    profile = _profile(tmp_path)
    client = Client([_plan()])
    asyncio.run(module.generate(
        module.DesignRequest(script=SOURCE, slide_count=1), client, profile=profile,
    ))
    payload = json.loads(client.prompts[0].split("<DATA>\n", 1)[1].rsplit("\n</DATA>", 1)[0])
    budgets = payload["template_layout"]["body_text_budgets"]
    assert budgets
    assert budgets[0]["source_slide_index"] == 1
    assert budgets[0]["max_words"] > 0
    assert budgets[0]["max_characters"] > budgets[0]["max_words"]


@pytest.mark.parametrize("invalid", ["length", "extra"])
def test_compact_repair_rejects_invalid_fields(service_importer, invalid):
    from pydantic import ValidationError

    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    plan = module.ContentPlan.model_validate(_plan())
    payload = {"sources": [{"id": "source-1", "text": SOURCE}]}
    reply = {"source_0": SOURCE}
    if invalid == "length":
        reply["source_0"] = "x" * 1201
    else:
        reply["extra"] = "must not be discarded"
    with pytest.raises(ValidationError):
        asyncio.run(module._repair_fields(Client([reply]), plan, payload,
                                          (False, payload["sources"])))


def test_cover_redistribution_retries_when_body_still_overflows(
    service_importer, tmp_path,
):
    from tests.test_template_design import _profile

    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    profile = _profile(tmp_path)
    profile.patterns[0].name = "Титульный слайд"
    profile.patterns[0].slots[1].box.height = 12700 * 50
    text = SOURCE * 3
    reply = {"title": "Платформа", "slides": [
        {"id": "s1", "title": "Платформа", "paragraphs": ["Анализ данных", text],
         "source_ids": ["source-1"]},
        {"id": "s2", "title": "Команда", "paragraphs": [text],
         "source_ids": ["source-1"]},
    ]}
    fixed = json.loads(json.dumps(reply))
    fixed["slides"][0]["paragraphs"] = ["Анализ данных"]
    fixed["slides"][1]["paragraphs"] = [SOURCE]
    fixed["slides"][1]["notes"] = text
    client = Client([reply, fixed])
    result = asyncio.run(module.generate(
        module.DesignRequest(script=SOURCE, slide_count=2), client, profile=profile,
    ))
    assert len(client.prompts) == 2
    assert result.slides[0].paragraphs == ["Анализ данных"]
    assert result.slides[1].paragraphs == [SOURCE]
    assert result.slides[1].notes == text
    assert reply["slides"][0]["paragraphs"] == ["Анализ данных", text]


def test_cover_redistribution_never_discards_new_facts(service_importer, tmp_path):
    from tests.test_template_design import _profile

    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    profile = _profile(tmp_path)
    profile.patterns[0].name = "Титульный слайд"
    profile.patterns[0].slots[1].box.height = 12700 * 50
    plan = module.ContentPlan.model_validate({"title": "Платформа", "slides": [
        {"id": "s1", "title": "Платформа", "paragraphs": ["Анализ", SOURCE * 3],
         "source_ids": ["source-1"]},
        {"id": "s2", "title": "Команда", "paragraphs": ["Данные"],
         "source_ids": ["source-2"]},
    ]})
    changed = module._redistribute_cover(profile, plan)
    assert changed.slides[1].paragraphs == ["Данные", SOURCE * 3]
    assert changed.slides[1].source_ids == ["source-2", "source-1"]
    assert plan.slides[1].paragraphs == ["Данные"]


def test_required_next_step_is_covered_across_slides_not_repeated_on_cover():
    from exposlides.design_content import source_excerpts, validate_story
    from exposlides.design_models import ContentPlan, DesignRequest

    source = "Библиотека помогает читателям выбирать книги. Следующий этап — собрать отзывы и улучшить каталог."
    request = DesignRequest(script=source, slide_count=2)
    plan = ContentPlan.model_validate({"title": "Библиотека", "slides": [
        {"id": "cover", "title": "Библиотека", "paragraphs": ["Выбор книг"],
         "source_ids": ["source-1"]},
        {"id": "body", "title": "Каталог", "paragraphs": [source],
         "source_ids": ["source-1"]},
    ]})
    excerpts = source_excerpts(source)
    assert validate_story(plan, request, excerpts) == []
    missing = plan.model_copy(deep=True)
    missing.slides[1].paragraphs = ["Библиотека помогает читателям выбирать книги."]
    assert validate_story(missing, request, excerpts)
    invented = plan.model_copy(deep=True)
    invented.slides[0].paragraphs = ["Выручка составила 999 млн рублей."]
    assert validate_story(invented, request, excerpts)


def _copy_story_prompts(module, monkeypatch, tmp_path):
    config = importlib.import_module("app.design_config")
    workflow, registry = config._configs()
    settings = config.role_config("story")
    root = config.ROOT
    for relative in [settings["prompt"], *settings["prompts"].values()]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / relative).read_bytes())
    monkeypatch.setattr(config, "_configs", lambda: (workflow, registry))
    monkeypatch.setattr(config, "ROOT", tmp_path)
    return {name: tmp_path / relative for name, relative in settings["prompts"].items()}


@pytest.mark.parametrize("patch", [False, True])
def test_retry_loads_external_templates_and_preserves_grounding_payload(
    service_importer, monkeypatch, tmp_path, patch,
):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    paths = _copy_story_prompts(module, monkeypatch, tmp_path)
    for name in ("correction", "correction_patch" if patch else "correction_full"):
        path = paths[name]
        path.write_text(f"external-{name} " + path.read_text(encoding="utf-8"), encoding="utf-8")
    bad, good = _plan(), _plan()
    if patch:
        bad["slides"][0]["source_ids"] = ["invented-source"]
    else:
        good["slides"].append({**good["slides"][0], "id": "slide-2"})
    client = Client([bad, good])
    request = module.DesignRequest(
        script=SOURCE, slide_count=len(good["slides"]), purpose="Объяснить продукт",
        required_messages=[SOURCE],
    )

    result = asyncio.run(module.generate(request, client))

    assert len(result.slides) == request.slide_count
    assert len(client.prompts) == 2
    retry = client.prompts[1]
    assert retry.startswith("external-correction ")
    assert f"external-correction_{'patch' if patch else 'full'} " in retry
    assert "Одного упоминания в notes недостаточно" in retry
    assert "Числа и обязательные сообщения оставьте видимыми" in retry
    payload = json.loads(retry.split("данные:\n", 1)[1])
    assert payload["input"]["required_messages"] == [SOURCE]
    assert payload["input"]["purpose"] == request.purpose
    assert payload["input"]["sources"][0]["text"] == SOURCE
    assert payload["previous_plan"] == module.ContentPlan.model_validate(bad).model_dump(mode="json")
    assert payload["issues"]
    expected = (module.role_prompt("story", "repair_requirements").rstrip("\n")
                if patch else client.prompts[0])
    assert payload["generation_requirements"] == expected


def test_editorial_repair_loads_external_template_with_original_source_and_limits(
    service_importer, monkeypatch, tmp_path,
):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    path = _copy_story_prompts(module, monkeypatch, tmp_path)["editorial_repair"]
    path.write_text("external-editorial " + path.read_text(encoding="utf-8"), encoding="utf-8")
    plan = module.ContentPlan.model_validate(_plan())
    payload = {"sources": [{"id": "source-1", "text": SOURCE}], "template_layout": {
        "title_max_characters": 15, "subtitle_max_characters": 12,
    }}
    client = Client([{"cover_title": "Платформа", "cover_subtitle": "Анализ", "source_0": SOURCE}])

    result = asyncio.run(module._repair_fields(client, plan, payload, (True, payload["sources"])))

    assert len(client.prompts) == 1
    prompt = client.prompts[0]
    assert prompt.startswith("external-editorial ")
    assert "Сохрани все его ключевые формулировки, факты, числа и отрицания" in prompt
    data = json.loads(prompt.split("инструкциями:\n", 1)[1])
    assert data == {
        "cover": plan.slides[0].model_dump(), "limits": payload["template_layout"],
        "source_fields": {"source_0": SOURCE},
    }
    assert result.slides[0].paragraphs == ["Анализ"]
    assert SOURCE in result.slides[0].notes


def test_missing_repair_prompt_fails_as_configuration_before_calling_llm(
    service_importer, monkeypatch, tmp_path,
):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_main")
    _copy_story_prompts(module, monkeypatch, tmp_path)["editorial_repair"].unlink()
    client = Client([_plan()])

    with pytest.raises(module.GenerationConfigurationError):
        asyncio.run(module.generate(module.DesignRequest(script=SOURCE, slide_count=1), client))
    assert not client.prompts


def test_story_cli_publishes_factual_errors_after_all_retries(
    service_importer, monkeypatch, tmp_path, capsys,
):
    module, output, closed = _story_cli(service_importer, monkeypatch, tmp_path)
    bad = _plan()
    bad["slides"][0]["paragraphs"].append("Выручка выросла на 99%.")
    calls = []

    async def reply(prompt, model):
        calls.append(prompt)
        return model.model_validate(bad)

    monkeypatch.setattr(module.fast_llm_client, "generate_json", reply)
    assert module.main() == 0
    assert len(calls) == 3
    assert closed == [True]
    assert capsys.readouterr().err == ""
    saved = module.ContentPlan.model_validate_json(output.read_text(encoding="utf-8"))
    request = module.DesignRequest(script=SOURCE, slide_count=1)
    assert any("99%" in issue for issue in module.validate_story(
        saved, request, module.source_excerpts(SOURCE),
    ))
    assert output.with_name("story-provenance.json").exists()
