from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import quote

import grpc
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
file_storage = importlib.import_module("exposlides.file_storage")
messages = importlib.import_module("exposlides._proto.file_service_pb2")
FileServiceStorage = file_storage.FileServiceStorage
StorageError = file_storage.StorageError
StoredFile = file_storage.StoredFile
FILE_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "file-service"


class FakeChannel:
    def __init__(self) -> None:
        self.requests = []
        self.timeouts = []
        self.close_count = 0
        self.error = None
        self.upload_response = messages.UploadFileResponse(file_id="stored-file", version=3)
        self.download_response = messages.DownloadFileResponse(content=b"result", version=3)

    def unary_unary(self, method, *, request_serializer, response_deserializer):
        def call(request, *, timeout):
            request_type = (
                messages.UploadFileRequest
                if method.endswith("/UploadFile")
                else messages.DownloadFileRequest
            )
            self.requests.append((method, request_type.FromString(request_serializer(request))))
            self.timeouts.append(timeout)
            if self.error is not None:
                raise self.error
            response = (
                self.upload_response if method.endswith("/UploadFile") else self.download_response
            )
            return response_deserializer(response.SerializeToString())

        return call

    def close(self):
        self.close_count += 1


@pytest.fixture
def fake_channel(monkeypatch):
    channel = FakeChannel()
    connection = Mock(return_value=channel)
    monkeypatch.setattr(grpc, "insecure_channel", connection)
    return channel, connection


def test_upload_binds_existing_protocol_and_preserves_cyrillic_name(fake_channel):
    channel, connection = fake_channel
    storage = FileServiceStorage("localhost:50051", timeout=12.5)

    stored = storage.upload("Шаблон.pptx", b"presentation", task_id="task-1")

    assert stored == StoredFile("stored-file", 3)
    connection.assert_called_once_with("localhost:50051", options=file_storage.GRPC_OPTIONS)
    assert dict(connection.call_args.kwargs["options"]) == {
        "grpc.max_send_message_length": 64 * 1024 * 1024,
        "grpc.max_receive_message_length": 64 * 1024 * 1024,
    }
    method, request = channel.requests[0]
    assert method == "/file_service.FileService/UploadFile"
    assert request.filename == "Шаблон.pptx"
    assert request.content == b"presentation"
    assert request.task_id == "task-1"
    assert request.file_id == ""
    assert request.content_type == file_storage.CONTENT_TYPES[".pptx"]
    assert channel.timeouts == [12.5]


def test_download_pins_saved_version_and_uses_deadline(fake_channel):
    channel, _ = fake_channel
    storage = FileServiceStorage("file-service:50051")

    assert storage.download(StoredFile("saved-id", 3)) == b"result"

    method, request = channel.requests[0]
    assert method == "/file_service.FileService/DownloadFile"
    assert request.file_id == "saved-id"
    assert request.version == 3
    assert channel.timeouts == [30]


def test_transfer_supports_web_limit_above_grpc_default(fake_channel):
    channel, _ = fake_channel
    content = b"x" * (25 * 1024 * 1024)
    channel.download_response = messages.DownloadFileResponse(content=content, version=3)
    storage = FileServiceStorage("localhost:50051")

    reference = storage.upload("big.txt", content)
    assert storage.download(reference) == content
    assert len(channel.requests[0][1].content) == len(content)


@pytest.mark.parametrize("content", [b"x" * 65, b"x" * 50])
def test_oversized_upload_including_envelope_is_rejected_before_rpc(
    fake_channel, monkeypatch, content
):
    channel, _ = fake_channel
    monkeypatch.setattr(file_storage, "MAX_GRPC_MESSAGE_BYTES", 64)
    storage = FileServiceStorage("localhost:50051")

    with pytest.raises(StorageError, match="лимит"):
        storage.upload("result.txt", content)

    assert channel.requests == []


def test_oversized_download_is_rejected(fake_channel, monkeypatch):
    channel, _ = fake_channel
    monkeypatch.setattr(file_storage, "MAX_GRPC_MESSAGE_BYTES", 64)
    channel.download_response = messages.DownloadFileResponse(content=b"x" * 64, version=3)

    with pytest.raises(StorageError, match="лимит"):
        FileServiceStorage("localhost:50051").download(StoredFile("saved-id", 3))


class PrivateRpcError(grpc.RpcError):
    def __init__(self, status):
        self.status = status

    def code(self):
        return self.status

    def details(self):
        raise AssertionError("Внутренние детали ошибки не должны читаться")

    def __str__(self):
        return "postgres://user:secret@private-db query; internal secret"


@pytest.mark.parametrize("operation", ["upload", "download"])
@pytest.mark.parametrize(
    ("status", "message"),
    [
        (grpc.StatusCode.NOT_FOUND, "не найден"),
        (grpc.StatusCode.UNAVAILABLE, "недоступно"),
        (grpc.StatusCode.DEADLINE_EXCEEDED, "не ответило вовремя"),
        (grpc.StatusCode.INVALID_ARGUMENT, "формат файла"),
        (grpc.StatusCode.RESOURCE_EXHAUSTED, "лимит"),
        (grpc.StatusCode.INTERNAL, "Ошибка файлового хранилища"),
    ],
)
def test_rpc_errors_are_sanitized_and_not_retried(fake_channel, operation, status, message):
    channel, _ = fake_channel
    channel.error = PrivateRpcError(status)
    storage = FileServiceStorage("localhost:50051")

    with pytest.raises(StorageError, match=message) as error:
        if operation == "upload":
            storage.upload("source.txt", b"source")
        else:
            storage.download(StoredFile("saved-id", 3))

    assert "secret" not in str(error.value)
    assert error.value.__suppress_context__
    assert len(channel.requests) == 1


@pytest.mark.parametrize("response", [messages.UploadFileResponse(), messages.UploadFileResponse(
    file_id="saved-id", version=0
)])
def test_invalid_upload_reference_is_rejected(fake_channel, response):
    channel, _ = fake_channel
    channel.upload_response = response

    with pytest.raises(StorageError, match="некорректн"):
        FileServiceStorage("localhost:50051").upload("source.txt", b"source")


def test_download_of_wrong_version_is_rejected(fake_channel):
    with pytest.raises(StorageError, match="другую версию"):
        FileServiceStorage("localhost:50051").download(StoredFile("saved-id", 2))


@pytest.mark.parametrize("version", [0, -1, True, 2**31, "1"])
def test_saved_reference_requires_an_explicit_valid_version(version):
    with pytest.raises(StorageError, match="версию"):
        StoredFile("saved-id", version)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeout_does_not_open_channel(fake_channel, timeout):
    _, connection = fake_channel

    with pytest.raises(ValueError, match="Таймаут"):
        FileServiceStorage("localhost:50051", timeout=timeout)

    connection.assert_not_called()


def test_close_is_idempotent_and_prevents_more_requests(fake_channel):
    channel, _ = fake_channel
    storage = FileServiceStorage("localhost:50051")
    storage.close()
    storage.close()

    with pytest.raises(StorageError, match="закрыто"):
        storage.upload("source.txt", b"source")
    with pytest.raises(StorageError, match="закрыто"):
        storage.download(StoredFile("saved-id", 3))

    assert channel.close_count == 1
    assert channel.requests == []


@pytest.fixture
def minio_module(service_importer):
    return service_importer(FILE_SERVICE_ROOT, "app.minio_storage")


@pytest.mark.parametrize("filename", ["Шаблон №1.pptx", "literal%20name.txt", "simple.txt"])
def test_minio_metadata_encodes_filename_as_ascii(minio_module, monkeypatch, filename):
    client = AsyncMock()
    monkeypatch.setattr(minio_module.MinioStorage, "_get_client", AsyncMock(return_value=client))
    metadata = {"original_name": filename, "other": "unchanged"}

    asyncio.run(minio_module.MinioStorage.save_file(b"source", "id/v1.txt", "text/plain", metadata))

    saved = client.put_object.await_args.kwargs["Metadata"]
    assert saved == {
        "original_name": quote(filename, safe=""),
        "original_name_encoding": "url",
        "other": "unchanged",
    }
    assert saved["original_name"].isascii()
    assert metadata == {"original_name": filename, "other": "unchanged"}
    client.__aexit__.assert_awaited_once_with(None, None, None)


@pytest.mark.parametrize(
    ("metadata", "expected_name"),
    [
        ({"original_name": quote("Презентация.pptx"), "original_name_encoding": "url"},
         "Презентация.pptx"),
        ({"original_name": "literal%20name.txt"}, "literal%20name.txt"),
        ({"original_name": "legacy.txt"}, "legacy.txt"),
        ({}, "id/v1.txt"),
    ],
)
def test_minio_reads_encoded_and_legacy_names(minio_module, monkeypatch, metadata, expected_name):
    stream = AsyncMock()
    stream.__aenter__.return_value = stream
    stream.read.return_value = b"source"
    client = AsyncMock()
    client.get_object.return_value = {
        "Body": stream,
        "Metadata": metadata,
        "ContentType": "text/plain",
    }
    monkeypatch.setattr(minio_module.MinioStorage, "_get_client", AsyncMock(return_value=client))

    result = asyncio.run(minio_module.MinioStorage.get_file("id/v1.txt"))

    assert result == (b"source", "text/plain", expected_name)
    client.__aexit__.assert_awaited_once_with(None, None, None)


def test_server_configures_message_limits_to_support_web_uploads(minio_module, monkeypatch):
    server = Mock()
    server.start = AsyncMock()
    server.wait_for_termination = AsyncMock()
    make_server = Mock(return_value=server)
    create_tables = AsyncMock()
    register = Mock()
    monkeypatch.setattr(grpc.aio, "server", make_server)
    monkeypatch.setattr(minio_module.MinioStorage, "ensure_bucket", AsyncMock())
    monkeypatch.setitem(sys.modules, "app.database", SimpleNamespace(create_tables=create_tables))
    monkeypatch.setitem(sys.modules, "app.service", SimpleNamespace(FileService=Mock()))
    monkeypatch.setitem(
        sys.modules, "file_service_pb2_grpc",
        SimpleNamespace(add_FileServiceServicer_to_server=register),
    )
    main = importlib.import_module("app.main")

    asyncio.run(main.serve())

    assert dict(make_server.call_args.kwargs["options"]) == dict(file_storage.GRPC_OPTIONS)
    create_tables.assert_awaited_once_with()
    register.assert_called_once()
    server.start.assert_awaited_once_with()
