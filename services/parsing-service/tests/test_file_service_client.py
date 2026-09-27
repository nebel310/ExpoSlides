from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from app.grpc.file_service_client import FileServiceClient


@pytest.fixture
def client() -> FileServiceClient:
    return FileServiceClient("localhost", 50051)


@pytest.mark.asyncio
async def test_connect_creates_channel_and_stub(client: FileServiceClient) -> None:
    with patch("app.grpc.file_service_client.grpc.aio.insecure_channel") as ch_mock:
        ch_mock.return_value = MagicMock()
        with patch(
            "app.grpc.file_service_client.file_service_pb2_grpc.FileServiceStub"
        ) as stub_mock:
            await client.connect()
            ch_mock.assert_called_once_with("localhost:50051")
            stub_mock.assert_called_once()


@pytest.mark.asyncio
async def test_close_without_connect_ok(client: FileServiceClient) -> None:
    await client.close()


@pytest.mark.asyncio
async def test_close_after_connect(client: FileServiceClient) -> None:
    channel = MagicMock()
    channel.close = AsyncMock()

    with patch(
        "app.grpc.file_service_client.grpc.aio.insecure_channel",
        return_value=channel,
    ):
        with patch(
            "app.grpc.file_service_client.file_service_pb2_grpc.FileServiceStub"
        ):
            await client.connect()
            await client.close()
            channel.close.assert_awaited_once()
            assert client._channel is None


@pytest.mark.asyncio
async def test_download_without_connect_raises(client: FileServiceClient) -> None:
    with pytest.raises(RuntimeError):
        await client.download_file("f1")


@pytest.mark.asyncio
async def test_upload_without_connect_raises(client: FileServiceClient) -> None:
    with pytest.raises(RuntimeError):
        await client.upload_file(
            filename="a.pptx",
            content=b"",
            content_type="application/octet-stream",
            task_id="t1",
        )


@pytest.mark.asyncio
async def test_delete_without_connect_raises(client: FileServiceClient) -> None:
    with pytest.raises(RuntimeError):
        await client.delete_file("f1")


@pytest_asyncio.fixture
async def connected_client() -> FileServiceClient:
    c = FileServiceClient("localhost", 50051)
    c._channel = MagicMock()
    c._stub = MagicMock()
    return c


@pytest.mark.asyncio
async def test_download_returns_bytes(connected_client: FileServiceClient) -> None:
    stub = connected_client._stub
    response = MagicMock()
    response.content = b"hello"
    stub.DownloadFile = AsyncMock(return_value=response)

    result = await connected_client.download_file("f1", version=0)

    assert result == b"hello"
    stub.DownloadFile.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_returns_file_id(connected_client: FileServiceClient) -> None:
    stub = connected_client._stub
    response = MagicMock()
    response.file_id = "new-id"
    stub.UploadFile = AsyncMock(return_value=response)

    result = await connected_client.upload_file(
        filename="a.pptx",
        content=b"data",
        content_type="application/octet-stream",
        task_id="t1",
    )

    assert result == "new-id"
    stub.UploadFile.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_with_existing_file_id(connected_client: FileServiceClient) -> None:
    stub = connected_client._stub
    response = MagicMock()
    response.file_id = "existing"
    stub.UploadFile = AsyncMock(return_value=response)

    result = await connected_client.upload_file(
        filename="a.pptx",
        content=b"data",
        content_type="application/octet-stream",
        task_id="t1",
        file_id="existing",
    )

    assert result == "existing"
    request = stub.UploadFile.call_args.args[0]
    assert request.file_id == "existing"


@pytest.mark.asyncio
async def test_delete_calls_stub(connected_client: FileServiceClient) -> None:
    stub = connected_client._stub
    stub.DeleteFile = AsyncMock()

    await connected_client.delete_file("f1")

    stub.DeleteFile.assert_awaited_once()