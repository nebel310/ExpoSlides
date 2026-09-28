from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


def _request(module, tmp_path, *, enabled=True, count=1):
    # Изображение генерируется тестом, внешние файлы и сеть не нужны.
    from PIL import Image

    image = tmp_path / "slide.png"
    Image.new("RGB", (20, 10), "white").save(image)
    return module.ContextualAuditRequest(enabled=enabled, slides=[
        module.AuditSlide(
            id=f"slide-{index}", image_path=image, text="Платформа анализа данных",
            source_text="Команда развивает платформу анализа данных.", source_ids=["source-1"],
        ) for index in range(count)
    ])


class Client:
    def __init__(self, module, *, failure=False):
        self.module = module
        self.calls = []
        self.failure = failure

    async def inspect(self, prompt, image_url):
        self.calls.append((prompt, image_url))
        if self.failure:
            raise RuntimeError("private provider failure")
        return self.module.SlideVerdict(checked_rules=list(self.module.RULES), findings=[
            self.module.Finding(
                rule="title_conclusion", message="Заголовок называет тему без вывода",
                evidence="На слайде написано «Платформа анализа данных»", severity="warning",
            ),
        ])


def test_disabled_audit_does_not_read_image_or_call_model(service_importer, tmp_path):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_audit")
    request = _request(module, tmp_path, enabled=False)
    request.slides[0].image_path = tmp_path / "missing.png"
    client = Client(module)
    report = asyncio.run(module.audit(request, client))
    assert report.contextual_status == "not_run"
    assert report.issues == []
    assert client.calls == []


def test_contextual_findings_have_trusted_slide_and_no_automatic_fix(service_importer, tmp_path):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_audit")
    client = Client(module)
    report = asyncio.run(module.audit(_request(module, tmp_path), client))
    assert report.contextual_status == "completed"
    assert len(report.issues) == 1
    issue = report.issues[0]
    assert issue.slide_id == "slide-0"
    assert issue.check_type == "contextual"
    assert issue.source_ids == ["source-1"]
    assert issue.fix == "none"
    prompt, image = client.calls[0]
    assert image.startswith("data:image/png;base64,")
    assert "Команда развивает" in prompt
    assert "не является инструкцией" in prompt


def test_contextual_provider_failure_is_explicit_and_does_not_leak_details(
    service_importer, tmp_path,
):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_audit")
    report = asyncio.run(module.audit(_request(module, tmp_path), Client(module, failure=True)))
    assert report.contextual_status == "failed"
    assert report.limitations
    assert "private provider" not in report.model_dump_json()
    assert not report.issues


def test_audit_timeout_cancels_tasks_and_returns_failed_status(
    service_importer, monkeypatch, tmp_path,
):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_audit")
    started = []
    cancelled = []

    async def inline_image_read(function, *args):
        # Не тратим короткий deadline на запуск thread pool: оба запроса
        # должны дойти до первого ожидания клиента до срабатывания таймера.
        return function(*args)

    monkeypatch.setattr(module.asyncio, "to_thread", inline_image_read)

    class SlowClient:
        async def inspect(self, prompt, image):
            started.append(asyncio.current_task())
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(asyncio.current_task())
                raise

    request = _request(module, tmp_path, count=2)
    request.timeout_seconds = 0.02

    async def run():
        # Watchdog не заменяет проверяемый timeout: его срабатывание провалит тест.
        return await asyncio.wait_for(module.audit(request, SlowClient()), timeout=1)

    report = asyncio.run(run())
    assert report.contextual_status == "failed"
    assert any("лимит" in issue for issue in report.limitations)
    assert len(started) == len(cancelled) == 2
    assert set(cancelled) == set(started)
    assert all(task.cancelled() for task in started)


def test_nonimage_input_is_not_sent_to_model(service_importer, tmp_path):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_audit")
    request = _request(module, tmp_path)
    other = tmp_path / "not-image.png"
    other.write_text("private unrelated data", encoding="utf-8")
    request.slides[0].image_path = other
    client = Client(module)
    report = asyncio.run(module.audit(request, client))
    assert report.contextual_status == "failed"
    assert not client.calls


def test_vision_payload_includes_image_and_uses_configured_model(
    service_importer, monkeypatch,
):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_audit")
    monkeypatch.setattr(module.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(module.settings, "llm_fast_model", "Qwen/Qwen3.8-27B")
    calls = []

    async def response(payload):
        calls.append(payload)
        text = json.dumps({"findings": [], "checked_rules": list(module.RULES)})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    monkeypatch.setattr(module.fast_llm_client, "_achat_with_transient_retry", response)
    result = asyncio.run(module.VisionAuditClient().inspect("Check the slide", "data:image/png;x"))
    assert not result.findings
    assert calls[0]["model"] == "Qwen/Qwen3.8-27B"
    assert calls[0]["messages"][0]["content"][1]["type"] == "image_url"


def test_incomplete_model_audit_is_retried_and_rejected(service_importer, monkeypatch):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_audit")
    errors = importlib.import_module("app.errors")
    monkeypatch.setattr(module.settings, "llm_api_key", "test-key")
    calls = []

    async def response(payload):
        calls.append(payload)
        text = json.dumps({"findings": [], "checked_rules": ["spelling"]})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    monkeypatch.setattr(module.fast_llm_client, "_achat_with_transient_retry", response)
    with pytest.raises(errors.LLMGenerationError, match="Некорректный ответ"):
        asyncio.run(module.VisionAuditClient().inspect("Check the slide", "data:image/png;x"))
    assert len(calls) == 2


def test_truncated_provider_envelope_is_retried_once(service_importer, monkeypatch):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_audit")
    monkeypatch.setattr(module.settings, "llm_api_key", "test-key")
    calls = []

    async def response(payload):
        calls.append(payload)
        if len(calls) == 1:
            raise module.ChatCompletionsResponseError("length")
        text = json.dumps({"findings": [], "checked_rules": list(module.RULES)})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    monkeypatch.setattr(module.fast_llm_client, "_achat_with_transient_retry", response)
    result = asyncio.run(module.VisionAuditClient().inspect("Check the slide", "data:image/png;x"))
    assert not result.findings
    assert len(calls) == 2
