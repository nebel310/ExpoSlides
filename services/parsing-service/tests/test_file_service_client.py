from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import file_service_pb2
from app.file_service_client import FileServiceClient


@pytest.fixture
def fake_stub() -> MagicMock:
    """Мок FileServiceStub с async-методами"""
    stub = MagicMock()
    stub.DownloadFile = AsyncMock()
    stub.UploadFile = AsyncMock()
    return stub


@pytest.fixture
def client(fake_stub: MagicMock) -> FileServiceClient:
    """Клиент с подставленным мок-стабом без реального connect"""
    instance = FileServiceClient(host="localhost", port=50051)
    instance._stub = fake_stub
    return instance


@pytest.mark.asyncio
async def test_download_file_returns_content(client, fake_stub):
    """download_file возвращает байты и передаёт file_id/version=0"""
    fake_stub.DownloadFile.return_value = file_service_pb2.DownloadFileResponse(
        content=b"pptx-bytes",
        filename="a.pptx",
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        version=1,
    )
    result = await client.download_file("fid-1")
    assert result == b"pptx-bytes"
    request = fake_stub.DownloadFile.call_args[0][0]
    assert request.file_id == "fid-1"
    assert request.version == 0


@pytest.mark.asyncio
async def test_download_file_with_version(client, fake_stub):
    """download_file прокидывает явную версию"""
    fake_stub.DownloadFile.return_value = file_service_pb2.DownloadFileResponse(content=b"x")
    await client.download_file("fid-1", version=2)
    request = fake_stub.DownloadFile.call_args[0][0]
    assert request.version == 2


@pytest.mark.asyncio
async def test_upload_file_returns_file_id(client, fake_stub):
    """upload_file возвращает file_id и прокидывает все поля запроса"""
    fake_stub.UploadFile.return_value = file_service_pb2.UploadFileResponse(file_id="new-id")
    file_id = await client.upload_file(
        filename="structure.json",
        content=b'{"a": 1}',
        content_type="application/json",
        task_id="t-1",
    )
    assert file_id == "new-id"
    request = fake_stub.UploadFile.call_args[0][0]
    assert request.filename == "structure.json"
    assert request.content == b'{"a": 1}'
    assert request.content_type == "application/json"
    assert request.task_id == "t-1"
    assert request.file_id == ""


@pytest.mark.asyncio
async def test_upload_file_with_existing_file_id(client, fake_stub):
    """upload_file прокидывает file_id для создания новой версии"""
    fake_stub.UploadFile.return_value = file_service_pb2.UploadFileResponse(file_id="fid")
    await client.upload_file(
        filename="structure.json",
        content=b"{}",
        content_type="application/json",
        task_id="t-1",
        file_id="existing",
    )
    request = fake_stub.UploadFile.call_args[0][0]
    assert request.file_id == "existing"


@pytest.mark.asyncio
async def test_download_file_without_connect_raises():
    """Вызов download_file до connect поднимает RuntimeError"""
    instance = FileServiceClient(host="localhost", port=50051)
    with pytest.raises(RuntimeError):
        await instance.download_file("x")


@pytest.mark.asyncio
async def test_upload_file_without_connect_raises():
    """Вызов upload_file до connect поднимает RuntimeError"""
    instance = FileServiceClient(host="localhost", port=50051)
    with pytest.raises(RuntimeError):
        await instance.upload_file(
            filename="x.json",
            content=b"{}",
            content_type="application/json",
            task_id="t",
        )