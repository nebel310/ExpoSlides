"""Недостаток диска не должен создавать задание или маскироваться ошибкой модели."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from exposlides.studio import create_app


def test_upload_and_generation_reject_full_disk_before_writing(tmp_path, monkeypatch):
    with TestClient(create_app(tmp_path)) as client:
        token = client.get("/api/session").json()["token"]
        template = client.get("/api/example").json()["template_id"]
        before = set(tmp_path.rglob("*"))
        monkeypatch.setattr("exposlides.studio.shutil.disk_usage", lambda _: SimpleNamespace(free=0))
        headers = {"X-Session-Token": token}
        uploaded = client.post("/api/templates", headers=headers,
                               json={"name": "test.pptx", "data": "YWJj"})
        assert uploaded.status_code == 507
        assert "недостаточно места" in uploaded.json()["detail"]
        result = client.post("/api/design/generate", headers=headers, json={
            "template_id": template, "request": {
                "script": "Проверочные материалы", "mode": "extractive", "slide_count": 1,
            },
        })
        assert result.status_code == 507
        assert client.get("/api/design/jobs").json() == {"jobs": []}
        assert set(tmp_path.rglob("*")) == before
