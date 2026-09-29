"""Перезапуск сохраняет доступ к уже опубликованным файлам прерванной сборки."""

import json

import pytest
from fastapi.testclient import TestClient

from exposlides.design_pipeline import save_model
from exposlides.studio import create_app


@pytest.mark.parametrize("operation", ["generate", "build"])
def test_restart_exposes_published_variants_of_interrupted_build(tmp_path, operation):
    identifier, owner = "a" * 32, "b" * 32
    directory = tmp_path / "jobs" / identifier
    save_model(directory / "job.json", {
        "id": identifier, "_owner_id": owner, "status": "running", "operation": operation,
        "variants": [], "active_seconds": 1,
    })
    exported = directory / "variants/story/1/presentation.html"
    exported.parent.mkdir(parents=True)
    exported.write_text("<!doctype html><title>Saved result</title>", encoding="utf-8")
    variants = [{"id": "story", "revision": 1, "preview_urls": [],
                 "exports": {"html": "variants/story/files/1/presentation.html"}}]
    save_model(directory / "variants.json", variants)
    with TestClient(create_app(tmp_path)) as client:
        client.cookies.set("studio_owner", owner)
        response = client.get(f"/api/design/jobs/{identifier}")
        assert response.status_code == 200
        job = response.json()
        assert job["status"] == "failed"
        assert job["error"]
        assert len(job["variants"]) == 1
        download = client.get(job["variants"][0]["exports"]["html"])
        assert download.status_code == 200
        assert download.content == exported.read_bytes()
        persisted = json.loads((directory / "job.json").read_text(encoding="utf-8"))
        assert persisted["variants"] == variants


@pytest.mark.parametrize("corrupt", [
    "{",
    [{"id": "story", "revision": 1, "exports": {"pptx": 42}, "preview_urls": []}],
    [{"id": "story", "revision": 1, "exports": {}, "preview_urls": [42]}],
    [{"id": "story", "revision": 0, "exports": {}, "preview_urls": []}],
])
def test_restart_keeps_job_visible_if_published_index_is_corrupt(tmp_path, corrupt):
    identifier = "a" * 32
    directory = tmp_path / "jobs" / identifier
    save_model(directory / "job.json", {
        "id": identifier, "status": "running", "operation": "generate", "variants": [],
    })
    (directory / "variants.json").write_text(
        corrupt if isinstance(corrupt, str) else json.dumps(corrupt), encoding="utf-8",
    )
    app = create_app(tmp_path)
    with TestClient(app):
        job = app.state.studio.get(identifier)
        assert job["status"] == "failed"
        assert job["variants"] == []
