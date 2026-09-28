import logging

import grpc
from app.config import settings
from file_service_pb2 import DownloadFileRequest, UploadFileRequest
from file_service_pb2_grpc import FileServiceStub

logger = logging.getLogger(__name__)


class FileServiceClient:
    """Асинхронный gRPC-клиент file-service"""

    def __init__(self, host: str | None = None, port: int | None = None) -> None:
        """Создать клиент с адресом из аргументов или настроек"""
        self._host = host or settings.file_service_grpc_host
        self._port = port or settings.file_service_grpc_port
        self._channel: grpc.aio.Channel | None = None
        self._stub: FileServiceStub | None = None

    async def start(self) -> None:
        """Открыть gRPC-канал и создать стаб"""
        target = f"{self._host}:{self._port}"
        logger.info("Открытие gRPC-канала к file-service: %s", target)
        self._channel = grpc.aio.insecure_channel(target)
        self._stub = FileServiceStub(self._channel)

    async def stop(self) -> None:
        """Закрыть gRPC-канал"""
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
            self._stub = None

    async def download_file(self, file_id: str, version: int = 0) -> bytes:
        """Скачать содержимое файла по file_id"""
        stub = self._require_stub()
        request = DownloadFileRequest(file_id=file_id, version=version)
        response = await stub.DownloadFile(request)
        logger.debug(
            "Скачан файл %s (version=%d, size=%d)",
            file_id,
            response.version,
            len(response.content),
        )
        return response.content

    async def upload_file(
        self,
        filename: str,
        content: bytes,
        content_type: str,
        task_id: str | None = None,
        file_id: str | None = None,
    ) -> str:
        """Загрузить файл и вернуть его file_id"""
        stub = self._require_stub()
        request = UploadFileRequest(
            filename=filename,
            content=content,
            content_type=content_type,
            task_id=task_id or "",
            file_id=file_id or "",
        )
        response = await stub.UploadFile(request)
        logger.debug(
            "Загружен файл %s (file_id=%s, version=%d, size=%d)",
            filename,
            response.file_id,
            response.version,
            response.size,
        )
        return response.file_id

    def _require_stub(self) -> FileServiceStub:
        """Вернуть стаб или упасть, если клиент не запущен"""
        if self._stub is None:
            raise RuntimeError("FileServiceClient не запущен: вызовите start()")
        return self._stub