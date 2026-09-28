"""Ошибки модели проходят в UI без утечки ответа и без потери материалов."""

import json
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from exposlides.cli import CONTENT_ERROR_CODES
from exposlides.design_pipeline import STORY_ERRORS, DesignContentError, DesignPipeline, save_model
from exposlides.studio import Studio, create_app


@pytest.mark.parametrize("code", [*CONTENT_ERROR_CODES, 1])
def test_subprocess_failure_keeps_safe_typed_reason(tmp_path, code):
    pipeline = DesignPipeline(tmp_path)
    try:
        with pytest.raises(DesignContentError) as failure:
            pipeline.command(
                [sys.executable, "-c", f"print('private provider reply'); raise SystemExit({code})"],
                tmp_path, content_stage=True,
            )
        assert failure.value.code == CONTENT_ERROR_CODES.get(code, "unknown")
        assert "private" not in str(failure.value)
        if code in CONTENT_ERROR_CODES:
            assert str(failure.value) == STORY_ERRORS[CONTENT_ERROR_CODES[code]]
    finally:
        pipeline.close()


@pytest.mark.parametrize("code", [*STORY_ERRORS, "unknown"])
def test_studio_returns_safe_model_failure_and_retains_request(tmp_path, code):
    class FailedModel:
        def __init__(self, *args, **kwargs):
            pass

        def plan(self, *args):
            raise DesignContentError(code)

        def close(self):
            pass

    studio = Studio(tmp_path, pipeline_factory=FailedModel)
    try:
        identifier = "a" * 32
        studio.jobs[identifier] = {
            "id": identifier, "status": "queued", "stage": "story", "active_seconds": 0,
            "request": {"script": "Материалы пользователя", "mode": "llm"}, "variants": [],
        }
        studio._save(studio.jobs[identifier])
        studio._run(identifier, "plan", None, threading.Event())
        result = studio.get(identifier)
        assert result["status"] == "failed"
        assert result["error"] == str(DesignContentError(code))
        assert result["request"]["script"] == "Материалы пользователя"
        assert result["request"]["mode"] == "llm"
        assert json.loads((studio.directory(identifier) / "job.json").read_text(
            encoding="utf-8",
        ))["error"] == result["error"]
    finally:
        studio.close()


def test_missing_model_rejects_request_before_creating_job_and_refreshes_readiness(
    tmp_path, monkeypatch,
):
    app = create_app(tmp_path)
    studio = app.state.studio
    # Ранее модель была настроена; новая проверка должна обнаружить её отсутствие.
    studio.capability_flags = {"story": True, "contextual_audit": True, "generated_image": False}
    probe = Mock(return_value=SimpleNamespace(stdout=json.dumps({
        "story": False, "contextual_audit": False, "generated_image": False,
    })))
    monkeypatch.setattr("exposlides.studio.subprocess.run", probe)
    dispatch = Mock()
    monkeypatch.setattr(studio, "_submit", dispatch)
    with TestClient(app) as client:
        token = client.get("/api/session").json()["token"]
        example = client.get("/api/example").json()
        payload = {"template_id": example["template_id"], "request": {
            "script": "Материалы пользователя.", "slide_count": 1, "mode": "llm",
        }}
        response = client.post("/api/design/plan", headers={"X-Session-Token": token}, json=payload)
        assert response.status_code == 422
        assert "Модель не подключена" in response.json()["detail"]
        assert payload["request"]["mode"] == "llm"
        assert studio.jobs == {}
        assert list((tmp_path / "jobs").iterdir()) == []
        dispatch.assert_not_called()
        probe.assert_called_once()

        # Новая конфигурация видна после обновления страницы, без перезапуска сервера.
        probe.return_value.stdout = json.dumps({"story": True})
        assert client.get("/api/capabilities").json()["story"] is True
        response = client.post("/api/design/plan", headers={"X-Session-Token": token}, json=payload)
        assert response.status_code == 202
        assert response.json()["request"] == studio.get(response.json()["id"])["request"]
        assert response.json()["request"]["mode"] == "llm"
        dispatch.assert_called_once()


def test_extractive_plan_does_not_require_model_probe(tmp_path, monkeypatch):
    studio = Studio(tmp_path)
    try:
        identifier = "b" * 32
        template = tmp_path / "templates" / f"{identifier}.pptx"
        template.write_bytes(b"fake template: worker is not run")
        save_model(template.with_suffix(".json"), {"id": identifier})
        probe = Mock(side_effect=AssertionError("Локальному режиму модель не нужна"))
        monkeypatch.setattr(studio, "capabilities", probe)
        monkeypatch.setattr(studio, "_submit", Mock())
        from exposlides.studio import PlanInput

        result = studio.start(PlanInput.model_validate({"template_id": identifier, "request": {
            "script": "Материалы пользователя.", "slide_count": 1, "mode": "extractive",
        }}))
        assert result["status"] == "queued"
        assert result["request"]["mode"] == "extractive"
        probe.assert_not_called()
    finally:
        studio.close()
