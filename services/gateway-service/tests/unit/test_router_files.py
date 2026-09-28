from unittest.mock import AsyncMock

from app.errors import FileServiceError
from app.repositories.files import FileRepository
from app.services import file_client as fc_module


async def _bootstrap(client) -> str:
    """Создаёт сессию через bootstrap"""
    response = await client.post("/api/session/bootstrap")
    return response.json()["sid"]


async def test_upload_ok(client, monkeypatch):
    """Проверяет успешную загрузку"""
    upload = AsyncMock(return_value={
        "file_id": "f1",
        "filename": "a.pptx",
        "size": 4,
        "content_type": "application/x",
        "version": 1,
    })
    monkeypatch.setattr(fc_module.file_client, "upload_file", upload)
    sid = await _bootstrap(client)
    response = await client.post(
        "/api/files/upload",
        files={"file": ("a.pptx", b"data", "application/x")},
        cookies={"exposlides_sid": sid},
    )
    assert response.status_code == 200
    assert response.json()["file_id"] == "f1"
    upload.assert_awaited_once()


async def test_upload_without_session(client):
    """Проверяет загрузку без сессии"""
    response = await client.post(
        "/api/files/upload",
        files={"file": ("a.pptx", b"data", "application/x")},
    )
    assert response.status_code == 401


async def test_upload_too_large(client, monkeypatch):
    """Проверяет превышение размера"""
    from app.config import settings
    monkeypatch.setattr(settings, "max_upload_size", 2)
    sid = await _bootstrap(client)
    response = await client.post(
        "/api/files/upload",
        files={"file": ("a.pptx", b"data-big", "application/x")},
        cookies={"exposlides_sid": sid},
    )
    assert response.status_code == 413


async def test_upload_file_service_error(client, monkeypatch):
    """Проверяет ошибку file-service"""
    upload = AsyncMock(side_effect=FileServiceError("boom"))
    monkeypatch.setattr(fc_module.file_client, "upload_file", upload)
    sid = await _bootstrap(client)
    response = await client.post(
        "/api/files/upload",
        files={"file": ("a.pptx", b"data", "application/x")},
        cookies={"exposlides_sid": sid},
    )
    assert response.status_code == 502


async def test_download_ok(client, redis, monkeypatch):
    """Проверяет скачивание"""
    download = AsyncMock(return_value=(b"payload", "r.pptx", "application/x", 1))
    monkeypatch.setattr(fc_module.file_client, "download_file", download)
    sid = await _bootstrap(client)
    await FileRepository.grant(redis, sid, "f1")
    response = await client.get(
        "/api/files/f1",
        cookies={"exposlides_sid": sid},
    )
    assert response.status_code == 200
    assert response.content == b"payload"
    assert "r.pptx" in response.headers["content-disposition"]


async def test_download_not_found(client, redis, monkeypatch):
    """Проверяет ошибку скачивания"""
    download = AsyncMock(side_effect=FileServiceError("nope"))
    monkeypatch.setattr(fc_module.file_client, "download_file", download)
    sid = await _bootstrap(client)
    await FileRepository.grant(redis, sid, "missing")
    response = await client.get(
        "/api/files/missing",
        cookies={"exposlides_sid": sid},
    )
    assert response.status_code == 404


async def test_download_without_session(client):
    """Проверяет скачивание без сессии"""
    response = await client.get("/api/files/f1")
    assert response.status_code == 401
