"""Общий лимит Studio и отмена до запуска worker — без моделей и конвертеров."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from exposlides.design_content import extractive_plan, source_excerpts
from exposlides.design_models import DesignRequest
from exposlides.design_pipeline import save_model
from exposlides.studio import FixInput, Studio


def ready_job(studio, identifier, operation):
    request = DesignRequest(script="Команда развивает платформу анализа данных.",
                            slide_count=1, mode="extractive")
    story = extractive_plan(request, source_excerpts(request.script))
    save_model(studio.directory(identifier) / "request.json", request)
    job = {
        "id": identifier, "status": "awaiting_review" if operation == "build" else "completed",
        "stage": "review", "active_seconds": 0, "error": "Предыдущее сообщение",
        "story": story.model_dump(mode="json"), "_owner_id": "f"*32,
        "variants": ([] if operation == "build" else [
            {"id": "story", "revision": 2, "preview_urls": [], "exports": {}},
        ]),
    }
    studio.jobs[identifier] = job
    studio._save(job)
    return story


def submit(studio, identifier, operation, story):
    if operation == "build":
        return studio.build(identifier, story)
    return studio.fix(identifier, "story", FixInput(revision=2, issue_ids=["issue"]))


def fill_queue(studio, count, status):
    for index in range(count):
        identifier = f"{index+1:032x}"
        studio.jobs[identifier] = {"id": identifier, "status": status}


@pytest.mark.parametrize("operation", ["build", "fix"])
@pytest.mark.parametrize("active_status", ["queued", "running", "cancelling"])
def test_full_queue_rejects_existing_job_transition_without_mutation(
    tmp_path, monkeypatch, operation, active_status,
):
    studio = Studio(tmp_path)
    try:
        identifier = "a"*32
        story = ready_job(studio, identifier, operation)
        original = deepcopy(studio.jobs[identifier])
        persisted = (studio.directory(identifier) / "job.json").read_bytes()
        fill_queue(studio, 8, active_status)
        dispatch = Mock()
        monkeypatch.setattr(studio, "_submit", dispatch)
        with pytest.raises(HTTPException) as rejected:
            submit(studio, identifier, operation, story)
        assert rejected.value.status_code == 429
        assert studio.jobs[identifier] == original
        assert (studio.directory(identifier) / "job.json").read_bytes() == persisted
        assert identifier not in studio.cancels
        dispatch.assert_not_called()
    finally:
        studio.close()


@pytest.mark.parametrize("operation", ["build", "fix"])
def test_closed_studio_rejects_existing_job_transition_without_mutation(
    tmp_path, monkeypatch, operation,
):
    studio = Studio(tmp_path)
    identifier = "a"*32
    story = ready_job(studio, identifier, operation)
    original = deepcopy(studio.jobs[identifier])
    studio.close()
    dispatch = Mock()
    monkeypatch.setattr(studio, "_submit", dispatch)
    with pytest.raises(HTTPException) as rejected:
        submit(studio, identifier, operation, story)
    assert rejected.value.status_code == 503
    assert studio.jobs[identifier] == original
    dispatch.assert_not_called()


def test_build_and_fix_compete_atomically_for_the_last_slot(tmp_path, monkeypatch):
    studio = Studio(tmp_path)
    try:
        fill_queue(studio, 7, "running")
        jobs = [("a"*32, "build"), ("b"*32, "fix")]
        stories = {identifier: ready_job(studio, identifier, operation)
                   for identifier, operation in jobs}
        previous = {identifier: deepcopy(studio.jobs[identifier]) for identifier, _ in jobs}
        dispatch = Mock()
        monkeypatch.setattr(studio, "_submit", dispatch)
        barrier = threading.Barrier(2)

        def attempt(item):
            identifier, operation = item
            barrier.wait(timeout=5)
            try:
                submit(studio, identifier, operation, stories[identifier])
                return identifier, 202
            except HTTPException as error:
                return identifier, error.status_code

        with ThreadPoolExecutor(max_workers=2) as callers:
            results = list(callers.map(attempt, jobs))
        assert sorted(status for _, status in results) == [202, 429]
        assert sum(job["status"] in {"queued", "running", "cancelling"}
                   for job in studio.jobs.values()) == 8
        rejected_id = next(identifier for identifier, status in results if status == 429)
        assert studio.jobs[rejected_id] == previous[rejected_id]
        assert json.loads((studio.directory(rejected_id) / "job.json").read_text(
            encoding="utf-8")) == previous[rejected_id]
        dispatch.assert_called_once()
    finally:
        studio.close()


@pytest.mark.parametrize("operation, terminal_status", [("build", "cancelled"), ("fix", "completed")])
def test_queued_cancel_keeps_capacity_reserved_until_worker_acknowledges(
    tmp_path, monkeypatch, operation, terminal_status,
):
    factory = Mock(side_effect=AssertionError("Отменённая работа не должна запускать pipeline"))
    studio = Studio(tmp_path, workers=1, pipeline_factory=factory)
    release = threading.Event()
    started = threading.Event()

    def hold_worker():
        started.set()
        assert release.wait(timeout=10)

    try:
        blocker = studio.pool.submit(hold_worker)
        assert started.wait(timeout=5)
        fill_queue(studio, 7, "running")
        identifier = "a"*32
        story = ready_job(studio, identifier, operation)
        previous_variants = deepcopy(studio.jobs[identifier]["variants"])
        assert submit(studio, identifier, operation, story)["status"] == "queued"
        assert studio.cancel(identifier)["status"] == "cancelling"
        other = "b"*32
        other_story = ready_job(studio, other, "build")
        with pytest.raises(HTTPException) as rejected:
            studio.build(other, other_story)
        assert rejected.value.status_code == 429
        assert studio.jobs[other]["status"] == "awaiting_review"
        release.set()
        blocker.result(timeout=5)
        studio.pool.submit(lambda: None).result(timeout=5)
        assert studio.jobs[identifier]["status"] == terminal_status
        assert studio.jobs[identifier]["variants"] == previous_variants
        assert identifier not in studio.cancels
        factory.assert_not_called()
        dispatch = Mock()
        monkeypatch.setattr(studio, "_submit", dispatch)
        assert studio.build(other, other_story)["status"] == "queued"
        dispatch.assert_called_once()
    finally:
        release.set()
        studio.close()
