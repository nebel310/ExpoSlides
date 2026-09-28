from unittest.mock import AsyncMock, MagicMock

import grpc
import pytest
from app.errors import FileServiceError
from app.services.file_client import FileServiceClient


def _client_with_stub(stub):
    """Создаёт клиент с подменённым стабом"""
    client = FileServiceClient()
    client._stub = stub
    return client


async def test_upload_file_ok():
    """Проверяет успешную загрузку файла"""
    stub = MagicMock()
    response = MagicMock()
    response.file_id = "f1"
    response.original_name = "a.pptx"
    response.size = 100
    response.version = 1
    stub.UploadFile = AsyncMock(return_value=response)
    client = _client_with_stub(stub)
    result = await client.upload_file(
        filename="a.pptx",
        content=b"data",
        content_type="application/x",
    )
    assert result == {
        "file_id": "f1",
        "filename": "a.pptx",
        "size": 100,
        "content_type": "application/x",
        "version": 1,
    }
    stub.UploadFile.assert_awaited_once()


async def test_upload_file_grpc_error():
    """Проверяет ошибку gRPC при загрузке"""
    stub = MagicMock()
    error = grpc.aio.AioRpcError.__new__(grpc.aio.AioRpcError)
    error.code = lambda: grpc.StatusCode.INVALID_ARGUMENT
    stub.UploadFile = AsyncMock(side_effect=error)
    client = _client_with_stub(stub)
    with pytest.raises(FileServiceError):
        await client.upload_file(
            filename="a.pptx",
            content=b"data",
            content_type="application/x",
        )


async def test_download_file_ok():
    """Проверяет успешное скачивание файла"""
    stub = MagicMock()
    response = MagicMock()
    response.content = b"payload"
    response.filename = "r.pptx"
    response.content_type = "application/x"
    response.version = 2
    stub.DownloadFile = AsyncMock(return_value=response)
    client = _client_with_stub(stub)
    content, filename, content_type, version = await client.download_file("f1")
    assert content == b"payload"
    assert filename == "r.pptx"
    assert content_type == "application/x"
    assert version == 2


async def test_download_file_grpc_error():
    """Проверяет ошибку gRPC при скачивании"""
    stub = MagicMock()
    error = grpc.aio.AioRpcError.__new__(grpc.aio.AioRpcError)
    error.code = lambda: grpc.StatusCode.NOT_FOUND
    stub.DownloadFile = AsyncMock(side_effect=error)
    client = _client_with_stub(stub)
    with pytest.raises(FileServiceError):
        await client.download_file("f1")


async def test_require_stub_without_start():
    """Проверяет ошибку при обращении без старта"""
    client = FileServiceClient()
    with pytest.raises(FileServiceError):
        client._require_stub()