from unittest.mock import AsyncMock, MagicMock

import pytest
from app.file_client import FileServiceClient


def _settings():
    """Заглушка настроек для клиента"""
    settings = MagicMock()
    settings.file_service_grpc_host = "file-service"
    settings.file_service_grpc_port = 50051
    settings.file_service_timeout = 60.0
    return settings


def _client_with_stub(stub):
    """Создаёт клиент с подменённым стабом"""
    client = FileServiceClient(_settings())
    client.stub = stub
    return client


async def test_upload_file_returns_id(monkeypatch):
    """upload_file возвращает file_id из ответа"""
    response = MagicMock()
    response.file_id = "abc"
    stub = MagicMock()
    stub.UploadFile = AsyncMock(return_value=response)
    client = _client_with_stub(stub)

    result = await client.upload_file(
        filename="r.pptx",
        content=b"data",
        content_type="application/x",
        task_id="t1",
    )
    assert result == "abc"
    stub.UploadFile.assert_awaited_once()


async def test_download_file_returns_bytes(monkeypatch):
    """download_file возвращает content из ответа"""
    response = MagicMock()
    response.content = b"payload"
    stub = MagicMock()
    stub.DownloadFile = AsyncMock(return_value=response)
    client = _client_with_stub(stub)

    result = await client.download_file("f1")
    assert result == b"payload"


async def test_call_without_start_raises():
    """Обращение к клиенту без start() падает"""
    client = FileServiceClient(_settings())
    with pytest.raises(RuntimeError, match="не запущен"):
        await client.download_file("f1")


async def test_stop_closes_channel():
    """stop() закрывает канал и сбрасывает стаб"""
    channel = MagicMock()
    channel.close = AsyncMock()
    client = FileServiceClient(_settings())
    client.channel = channel
    client.stub = MagicMock()
    await client.stop()
    assert client.channel is None
    assert client.stub is None
    channel.close.assert_awaited_once()