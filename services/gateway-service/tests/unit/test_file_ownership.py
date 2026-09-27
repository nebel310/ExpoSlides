from unittest.mock import AsyncMock

from app.repositories.files import FileRepository
from app.services import file_client as files
from app.services import kafka_consumer as events
from app.services import task_service as tasks


async def bootstrap(client):
    client.cookies.clear()
    response = await client.post("/api/session/bootstrap")
    return response.json()["sid"]


async def test_uploaded_file_download_is_private_and_unicode_filename_is_safe(client, monkeypatch):
    upload = AsyncMock(return_value={
        "file_id": "private", "filename": "Отчёт.pptx", "size": 4,
        "content_type": "application/octet-stream", "version": 1,
    })
    download = AsyncMock(return_value=(b"pptx", "Отчёт.pptx", "application/octet-stream", 1))
    monkeypatch.setattr(files.file_client, "upload_file", upload)
    monkeypatch.setattr(files.file_client, "download_file", download)
    owner = await bootstrap(client)
    response = await client.post("/api/files/upload", files={"file": ("Отчёт.pptx", b"data")})
    assert response.status_code == 200
    response = await client.get("/api/files/private")
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment; filename*=UTF-8''")
    assert response.headers["x-content-type-options"] == "nosniff"
    other = await bootstrap(client)
    assert other != owner
    assert (await client.get("/api/files/private")).status_code == 404
    download.assert_awaited_once()


async def test_task_cannot_use_other_sessions_input(client, redis, monkeypatch):
    owner = await bootstrap(client)
    await FileRepository.grant(redis, owner, "template")
    await FileRepository.grant(redis, owner, "script")
    await bootstrap(client)
    publish = AsyncMock()
    monkeypatch.setattr(tasks.kafka_producer, "publish", publish)
    response = await client.post("/api/tasks", json={
        "template_file_id": "template", "script_file_id": "script",
    })
    assert response.status_code == 404
    publish.assert_not_awaited()


async def test_generated_file_is_granted_to_task_owner_only(client, redis, monkeypatch):
    import json

    from app.repositories.tasks import TaskRepository

    owner = await bootstrap(client)
    await TaskRepository.save(redis, {"task_id": "task", "sid": owner, "status": "building"})
    monkeypatch.setattr(events, "emit_to_session", AsyncMock())
    await events.GatewayKafkaConsumer()._handle(redis, "task.built", json.dumps({
        "task_id": "task", "attempt": 1, "payload": {"result_file_id": "result"},
    }).encode())
    download = AsyncMock(return_value=(b"pptx", "result.pptx", "application/octet-stream", 1))
    monkeypatch.setattr(files.file_client, "download_file", download)
    assert (await client.get("/api/files/result")).status_code == 200
    await bootstrap(client)
    assert (await client.get("/api/files/result")).status_code == 404
    download.assert_awaited_once()
