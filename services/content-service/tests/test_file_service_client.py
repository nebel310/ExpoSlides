from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.grpc.file_service_client import FileServiceClient


def _patch_transport():
    """Собрать контекстный менеджер для мока gRPC-транспорта"""
    return patch("app.grpc.file_service_client.grpc.aio.insecure_channel"), patch(
        "app.grpc.file_service_client.FileServiceStub"
    )


@pytest.mark.asyncio
async def test_start_opens_channel_and_stub():
    """Проверить, что start открывает канал и создаёт стаб"""
    channel_patch, stub_patch = _patch_transport()
    with channel_patch as mock_channel, stub_patch as mock_stub_cls:
        client = FileServiceClient(host="file-service", port=50051)
        await client.start()
        mock_channel.assert_called_once_with("file-service:50051")
        mock_stub_cls.assert_called_once()


@pytest.mark.asyncio
async def test_stop_closes_channel():
    """Проверить, что stop закрывает канал"""
    channel_patch, stub_patch = _patch_transport()
    with channel_patch as mock_channel_factory, stub_patch:
        mock_channel = MagicMock()
        mock_channel.close = AsyncMock()
        mock_channel_factory.return_value = mock_channel
        client = FileServiceClient(host="h", port=1)
        await client.start()
        await client.stop()
        mock_channel.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_without_start_is_safe():
    """Проверить, что stop без start не падает"""
    client = FileServiceClient(host="h", port=1)
    await client.stop()


@pytest.mark.asyncio
async def test_download_file_valid():
    """Проверить успешное скачивание файла"""
    channel_patch, stub_patch = _patch_transport()
    with channel_patch, stub_patch as mock_stub_cls:
        mock_stub = MagicMock()
        mock_stub.DownloadFile = AsyncMock(
            return_value=MagicMock(content=b"hello", version=0)
        )
        mock_stub_cls.return_value = mock_stub
        client = FileServiceClient(host="h", port=1)
        await client.start()
        data = await client.download_file("fid-1")
        assert data == b"hello"
        mock_stub.DownloadFile.assert_awaited_once()
        request = mock_stub.DownloadFile.await_args.args[0]
        assert request.file_id == "fid-1"
        assert request.version == 0


@pytest.mark.asyncio
async def test_download_file_specific_version():
    """Проверить скачивание конкретной версии"""
    channel_patch, stub_patch = _patch_transport()
    with channel_patch, stub_patch as mock_stub_cls:
        mock_stub = MagicMock()
        mock_stub.DownloadFile = AsyncMock(
            return_value=MagicMock(content=b"x", version=3)
        )
        mock_stub_cls.return_value = mock_stub
        client = FileServiceClient(host="h", port=1)
        await client.start()
        await client.download_file("fid", version=3)
        request = mock_stub.DownloadFile.await_args.args[0]
        assert request.version == 3


@pytest.mark.asyncio
async def test_download_file_before_start_raises():
    """Проверить ошибку при download без start"""
    client = FileServiceClient(host="h", port=1)
    with pytest.raises(RuntimeError):
        await client.download_file("fid")


@pytest.mark.asyncio
async def test_upload_file_valid_without_file_id():
    """Проверить успешную загрузку нового файла"""
    channel_patch, stub_patch = _patch_transport()
    with channel_patch, stub_patch as mock_stub_cls:
        mock_stub = MagicMock()
        mock_stub.UploadFile = AsyncMock(return_value=MagicMock(file_id="new-fid"))
        mock_stub_cls.return_value = mock_stub
        client = FileServiceClient(host="h", port=1)
        await client.start()
        file_id = await client.upload_file(
            filename="content.json",
            content=b"{}",
            content_type="application/json",
            task_id="task-1",
        )
        assert file_id == "new-fid"
        request = mock_stub.UploadFile.await_args.args[0]
        assert request.filename == "content.json"
        assert request.content == b"{}"
        assert request.content_type == "application/json"
        assert request.task_id == "task-1"
        assert request.file_id == ""


@pytest.mark.asyncio
async def test_upload_file_valid_with_file_id():
    """Проверить загрузку новой версии существующего файла"""
    channel_patch, stub_patch = _patch_transport()
    with channel_patch, stub_patch as mock_stub_cls:
        mock_stub = MagicMock()
        mock_stub.UploadFile = AsyncMock(return_value=MagicMock(file_id="existing"))
        mock_stub_cls.return_value = mock_stub
        client = FileServiceClient(host="h", port=1)
        await client.start()
        file_id = await client.upload_file(
            filename="content.json",
            content=b"{}",
            content_type="application/json",
            task_id="task-1",
            file_id="existing",
        )
        assert file_id == "existing"
        request = mock_stub.UploadFile.await_args.args[0]
        assert request.file_id == "existing"


@pytest.mark.asyncio
async def test_upload_file_before_start_raises():
    """Проверить ошибку при upload без start"""
    client = FileServiceClient(host="h", port=1)
    with pytest.raises(RuntimeError):
        await client.upload_file(
            filename="content.json",
            content=b"{}",
            content_type="application/json",
        )


@pytest.mark.asyncio
async def test_download_file_propagates_grpc_error():
    """Проверить проброс ошибки gRPC наверх"""
    import grpc

    channel_patch, stub_patch = _patch_transport()
    with channel_patch, stub_patch as mock_stub_cls:
        mock_stub = MagicMock()
        error = grpc.aio.AioRpcError(
            grpc.StatusCode.NOT_FOUND, None, None, "not found"
        )
        mock_stub.DownloadFile = AsyncMock(side_effect=error)
        mock_stub_cls.return_value = mock_stub
        client = FileServiceClient(host="h", port=1)
        await client.start()
        with pytest.raises(grpc.aio.AioRpcError):
            await client.download_file("missing")