"""Ограниченный по времени клиент существующего файлового gRPC-сервиса."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

MAX_GRPC_MESSAGE_BYTES = 64 * 1024 * 1024
GRPC_OPTIONS = (
    ("grpc.max_send_message_length", MAX_GRPC_MESSAGE_BYTES),
    ("grpc.max_receive_message_length", MAX_GRPC_MESSAGE_BYTES),
)
CONTENT_TYPES = {
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pdf": "application/pdf",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
}


class StorageError(RuntimeError):
    """Ошибка хранилища без внутренних адресов, ключей и ответа сервера."""


@dataclass(frozen=True)
class StoredFile:
    """Ссылка на неизменяемую версию файла в файловом сервисе."""

    file_id: str
    version: int

    def __post_init__(self) -> None:
        if not isinstance(self.file_id, str) or not self.file_id.strip():
            raise StorageError("Хранилище вернуло некорректный идентификатор файла.")
        if type(self.version) is not int or not 1 <= self.version <= 2**31 - 1:
            raise StorageError("Хранилище вернуло некорректную версию файла.")


class FileServiceStorage:
    """Синхронный клиент для web-потоков; импорты gRPC отложены до подключения."""

    def __init__(self, target: str, timeout: float = 30) -> None:
        if not isinstance(target, str) or not target.strip():
            raise ValueError("Укажите адрес файлового сервиса.")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Таймаут файлового сервиса должен быть положительным числом.")

        import grpc

        from ._proto import file_service_pb2

        self._grpc = grpc
        self._messages = file_service_pb2
        self._timeout = timeout
        self._closed = False
        self._channel = grpc.insecure_channel(target.strip(), options=GRPC_OPTIONS)
        self._upload = self._channel.unary_unary(
            "/file_service.FileService/UploadFile",
            request_serializer=file_service_pb2.UploadFileRequest.SerializeToString,
            response_deserializer=file_service_pb2.UploadFileResponse.FromString,
        )
        self._download = self._channel.unary_unary(
            "/file_service.FileService/DownloadFile",
            request_serializer=file_service_pb2.DownloadFileRequest.SerializeToString,
            response_deserializer=file_service_pb2.DownloadFileResponse.FromString,
        )

    def _check_open(self) -> None:
        if self._closed:
            raise StorageError("Соединение с файловым хранилищем закрыто.")

    def _rpc_error(self, error: Exception) -> StorageError:
        status = error.code()
        messages = {
            self._grpc.StatusCode.NOT_FOUND: "Файл не найден в хранилище.",
            self._grpc.StatusCode.INVALID_ARGUMENT: "Хранилище отклонило формат файла.",
            self._grpc.StatusCode.RESOURCE_EXHAUSTED: "Превышен лимит файлового хранилища.",
            self._grpc.StatusCode.DEADLINE_EXCEEDED: "Файловое хранилище не ответило вовремя.",
            self._grpc.StatusCode.UNAVAILABLE: "Файловое хранилище недоступно.",
        }
        return StorageError(messages.get(status, "Ошибка файлового хранилища."))

    def upload(self, name: str, data: bytes, *, task_id: str = "") -> StoredFile:
        """Сохранить новый файл; неоднозначно завершённые загрузки не повторяются."""
        self._check_open()
        if len(data) > MAX_GRPC_MESSAGE_BYTES:
            raise StorageError("Файл превышает лимит файлового хранилища.")
        request = self._messages.UploadFileRequest(
            filename=name,
            content=data,
            content_type=CONTENT_TYPES.get(Path(name).suffix.lower(), "application/octet-stream"),
            task_id=task_id,
        )
        if request.ByteSize() > MAX_GRPC_MESSAGE_BYTES:
            raise StorageError("Файл превышает лимит файлового хранилища.")
        try:
            response = self._upload(request, timeout=self._timeout)
        except self._grpc.RpcError as error:
            raise self._rpc_error(error) from None
        return StoredFile(file_id=response.file_id, version=response.version)

    def download(self, file: StoredFile) -> bytes:
        """Прочитать конкретную сохранённую версию, не подменяя её последней."""
        self._check_open()
        request = self._messages.DownloadFileRequest(file_id=file.file_id, version=file.version)
        try:
            response = self._download(request, timeout=self._timeout)
        except self._grpc.RpcError as error:
            raise self._rpc_error(error) from None
        if response.version != file.version:
            raise StorageError("Хранилище вернуло другую версию файла.")
        if response.ByteSize() > MAX_GRPC_MESSAGE_BYTES:
            raise StorageError("Файл превышает лимит файлового хранилища.")
        return response.content

    def close(self) -> None:
        """Закрыть канал; повторное закрытие безопасно."""
        if not self._closed:
            self._closed = True
            self._channel.close()
