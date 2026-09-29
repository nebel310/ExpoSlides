"""Автоматический серверный workflow: fake model/build, настоящая очередь и persistence."""

import json
import threading
import time
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from exposlides.design_content import extractive_plan, source_excerpts
from exposlides.design_models import Box, DesignRequest, SlidePattern, TemplateProfile, TextStyle
from exposlides.design_pipeline import CancelledError, save_model
from exposlides.studio import PlanInput, Studio, create_app


@pytest.fixture
def pipeline_type():
    class FakePipeline:
        instances = []
        built = threading.Event()

        def __init__(self, directory, *, timeout, cancel, progress):
            self.directory = directory
            self.timeout = timeout
            self.deadline = time.monotonic() + timeout
            self.cancel = cancel
            self.progress = progress
            self.calls = []
            self.closed = False
            self.instances.append(self)

        def check(self):
            if self.cancel.is_set():
                raise CancelledError()
            if time.monotonic() >= self.deadline:
                raise TimeoutError("Общий лимит генерации исчерпан")

        def plan(self, template, request):
            self.calls.append("plan")
            self.progress("story")
            profile = TemplateProfile(
                template_sha256="a" * 64, width=1000, height=800,
                patterns=[SlidePattern(
                    source_slide_index=1, name="Template", slots=[], font="Arial",
                    content_box=Box(left=10, top=100, width=980, height=600),
                    palette=["202124"], title_style=TextStyle(), body_style=TextStyle(),
                )],
            )
            story = extractive_plan(request, source_excerpts(request.script))
            save_model(self.directory / "profile.json", profile)
            save_model(self.directory / "story.json", story)
            return profile, story

        def build(self, template, request, profile, story):
            self.check()
            self.calls.append("build")
            assert len(story.slides) == request.slide_count
            self.progress("building:story")
            variants = [
                {"id": variant, "revision": 1, "issues": [], "preview_urls": [], "exports": {}}
                for variant in ("story", "evidence", "cards")
            ]
            save_model(self.directory / "variants.json", variants)
            self.built.set()
            return variants

        def close(self):
            self.closed = True

    return FakePipeline


def prepared(tmp_path, pipeline_type):
    studio = Studio(tmp_path, workers=1, pipeline_factory=pipeline_type)
    identifier = "a" * 32
    template = tmp_path / "templates" / f"{identifier}.pptx"
    template.write_bytes(b"No parser is called by the offline pipeline")
    save_model(template.with_suffix(".json"), {"id": identifier})
    payload = PlanInput(template_id=identifier, request=DesignRequest(
        script="Команда развивает платформу. Поддержка помогает клиентам.",
        slide_count=1, mode="extractive",
    ))
    return studio, payload


def finish(studio, identifier):
    # Один worker: барьер выполняется только после генерации и её finally/save.
    studio.pool.submit(lambda: None).result(timeout=5)
    return studio.get(identifier)


def test_generate_endpoint_runs_to_completion_without_review_or_further_browser_request(
    tmp_path, pipeline_type, monkeypatch,
):
    app = create_app(tmp_path, pipeline_factory=pipeline_type)
    studio = app.state.studio
    states = []
    original_save = studio._save

    def record(job):
        states.append((job["status"], job["stage"]))
        original_save(job)

    monkeypatch.setattr(studio, "_save", record)
    with TestClient(app) as client:
        token = client.get("/api/session").json()["token"]
        template_id = client.get("/api/example").json()["template_id"]
        response = client.post("/api/design/generate", headers={"X-Session-Token": token}, json={
            "template_id": template_id, "request": {
                "script": "Команда развивает платформу.", "slide_count": 1, "mode": "extractive",
            },
        })
        assert response.status_code == 202
        identifier = response.json()["id"]
        # Никаких polling/build запросов: работу продолжает серверный executor.
        assert pipeline_type.built.wait(5)
        studio.pool.shutdown(wait=True)
        job = client.get(f"/api/design/jobs/{identifier}").json()
        assert job["status"] == "completed" and job["operation"] == "generate"
        assert len(job["variants"]) == 3
        assert len(pipeline_type.instances) == 1
        assert pipeline_type.instances[0].calls == ["plan", "build"]
        assert pipeline_type.instances[0].timeout == 300
        assert "awaiting_review" not in {status for status, _ in states}
        assert ("running", "building") in states
        assert json.loads((studio.directory(identifier) / "job.json").read_text())["story"] == job["story"]
        assert client.get("/api/design/jobs").json()["jobs"][0]["id"] == identifier
    restored = Studio(tmp_path, pipeline_factory=pipeline_type)
    try:
        assert restored.get(identifier)["status"] == "completed"
        assert len(restored.get(identifier)["variants"]) == 3
    finally:
        restored.close()


def test_legacy_plan_still_waits_for_review_before_build(tmp_path, pipeline_type):
    studio, payload = prepared(tmp_path, pipeline_type)
    try:
        identifier = studio.start(payload)["id"]
        job = finish(studio, identifier)
        assert job["status"] == "awaiting_review"
        assert pipeline_type.instances[0].calls == ["plan"]
        from exposlides.design_models import ContentPlan

        studio.build(identifier, ContentPlan.model_validate(job["story"]))
        assert finish(studio, identifier)["status"] == "completed"
    finally:
        studio.close()


def test_auto_generate_rejects_ungrounded_story_before_build(tmp_path, pipeline_type, monkeypatch):
    original = pipeline_type.plan

    def invalid(self, template, request):
        profile, story = original(self, template, request)
        story.slides[0].paragraphs.append("Выручка выросла на 999 процентов.")
        return profile, story

    monkeypatch.setattr(pipeline_type, "plan", invalid)
    studio, payload = prepared(tmp_path, pipeline_type)
    try:
        identifier = studio.start(payload, auto_build=True)["id"]
        job = finish(studio, identifier)
        assert job["status"] == "failed" and job["error"]
        assert job["request"]["script"] == payload.request.script
        assert pipeline_type.instances[0].calls == ["plan"]
        assert not (studio.directory(identifier) / "variants.json").exists()
    finally:
        studio.close()


def test_auto_generate_keeps_one_deadline_across_plan_and_build(tmp_path, pipeline_type, monkeypatch):
    original = pipeline_type.plan

    def exhausted(self, *args):
        result = original(self, *args)
        self.deadline = 0
        return result

    monkeypatch.setattr(pipeline_type, "plan", exhausted)
    studio, payload = prepared(tmp_path, pipeline_type)
    try:
        identifier = studio.start(payload, auto_build=True)["id"]
        job = finish(studio, identifier)
        assert job["status"] == "failed"
        assert job["error"] == "Общий лимит генерации исчерпан"
        assert len(pipeline_type.instances) == 1
        assert pipeline_type.instances[0].calls == ["plan"]
    finally:
        studio.close()


def test_auto_generate_cancels_while_waiting_for_serial_render_lock(
    tmp_path, pipeline_type, monkeypatch,
):
    studio, payload = prepared(tmp_path, pipeline_type)
    ready = threading.Event()
    original_save = studio._save

    def ready_to_build(job):
        original_save(job)
        if job["stage"] == "building":
            ready.set()

    monkeypatch.setattr(studio, "_save", ready_to_build)
    studio.render_lock.acquire()
    try:
        identifier = studio.start(payload, auto_build=True)["id"]
        assert ready.wait(5)
        assert pipeline_type.instances[0].calls == ["plan"]
        studio.cancel(identifier)
    finally:
        studio.render_lock.release()
    try:
        job = finish(studio, identifier)
        assert job["status"] == "cancelled"
        assert job["story"] and job["profile"]
        assert pipeline_type.instances[0].calls == ["plan"]
        assert pipeline_type.instances[0].closed
    finally:
        studio.close()


def test_auto_generate_build_failure_keeps_validated_story_and_published_variants(
    tmp_path, pipeline_type, monkeypatch,
):
    def partial(self, *args):
        save_model(self.directory / "variants.json", [
            {"id": "story", "revision": 1, "preview_urls": [], "exports": {}},
        ])
        raise TimeoutError("Не хватило времени на остальные варианты")

    monkeypatch.setattr(pipeline_type, "build", partial)
    studio, payload = prepared(tmp_path, pipeline_type)
    try:
        identifier = studio.start(payload, auto_build=True)["id"]
        job = finish(studio, identifier)
        assert job["status"] == "failed" and job["error"]
        assert job["story"] and job["profile"]
        assert [variant["id"] for variant in job["variants"]] == ["story"]
        assert json.loads((studio.directory(identifier) / "job.json").read_text())["story"] == job["story"]
    finally:
        studio.close()


@pytest.mark.parametrize("failure,status", [("model", 422), ("queue", 429), ("session", 403)])
def test_generate_endpoint_preserves_preflight_and_queue_guards(
    tmp_path, pipeline_type, monkeypatch, failure, status,
):
    app = create_app(tmp_path, pipeline_factory=pipeline_type)
    studio = app.state.studio
    monkeypatch.setattr(studio, "capabilities", Mock(return_value={"story": failure != "model"}))
    dispatch = Mock()
    monkeypatch.setattr(studio, "_submit", dispatch)
    with TestClient(app) as client:
        token = client.get("/api/session").json()["token"]
        template_id = client.get("/api/example").json()["template_id"]
        if failure == "queue":
            studio.jobs = {str(index): {"status": "running"} for index in range(studio.MAX_ACTIVE_JOBS)}
        count = len(studio.jobs)
        response = client.post("/api/design/generate", json={
            "template_id": template_id,
            "request": {"script": "Команда развивает платформу.", "slide_count": 1, "mode": "llm"},
        }, headers={"X-Session-Token": token if failure != "session" else "expired"})
        assert response.status_code == status
        if failure == "model":
            assert response.json()["detail"] == (
                "Сервис генерации временно недоступен. Попробуйте позже."
            )
        assert len(studio.jobs) == count
        assert list((tmp_path / "jobs").iterdir()) == []
        dispatch.assert_not_called()


@pytest.mark.parametrize("auto_build", [True, False])
def test_llm_story_with_factual_errors_reaches_build(
    tmp_path, pipeline_type, monkeypatch, auto_build,
):
    from exposlides.design_models import ContentPlan

    original = pipeline_type.plan

    def unverified(self, template, request):
        profile, story = original(self, template, request)
        story.slides[0].paragraphs.append("Выручка выросла на 999 процентов.")
        return profile, story

    monkeypatch.setattr(pipeline_type, "plan", unverified)
    studio, payload = prepared(tmp_path, pipeline_type)
    payload.request.mode = "llm"
    monkeypatch.setattr(studio, "capabilities", lambda **kwargs: {"story": True})
    try:
        identifier = studio.start(payload, auto_build=auto_build)["id"]
        job = finish(studio, identifier)
        if not auto_build:
            assert job["status"] == "awaiting_review"
            studio.build(identifier, ContentPlan.model_validate(job["story"]))
            job = finish(studio, identifier)
        assert job["status"] == "completed"
        assert any("build" in pipeline.calls for pipeline in pipeline_type.instances)
    finally:
        studio.close()
