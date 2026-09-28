import logging
from typing import Any

import file_service_pb2
import file_service_pb2_grpc
import grpc
from app.config import settings
from app.errors import FileServiceError

logger = logging.getLogger(__name__)


class FileServiceClient:
    """Асинхронный gRPC-клиент file-service"""

    def __init__(self) -> None:
        """Инициализирует клиент без подключения"""
        self._channel: grpc.aio.Channel | None = None
        self._stub: file_service_pb2_grpc.FileServiceStub | None = None

    async def start(self) -> None:
        """Открывает gRPC-канал"""
        target = f"{settings.file_service_grpc_host}:{settings.file_service_grpc_port}"
        max_message = settings.max_upload_size + 1024 * 1024
        self._channel = grpc.aio.insecure_channel(
            target,
            options=(
                ("grpc.max_send_message_length", max_message),
                ("grpc.max_receive_message_length", max_message),
            ),
        )
        self._stub = file_service_pb2_grpc.FileServiceStub(self._channel)
        logger.info("FileServiceClient подключён к %s", target)

    async def stop(self) -> None:
        """Закрывает gRPC-канал"""
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
            self._stub = None

    def _require_stub(self) -> file_service_pb2_grpc.FileServiceStub:
        """Возвращает стаб или падает"""
        if self._stub is None:
            raise FileServiceError("FileServiceClient не запущен")
        return self._stub

    async def upload_file(
        self,
        filename: str,
        content: bytes,
        content_type: str,
        task_id: str = "",
    ) -> dict[str, Any]:
        """Загружает файл в file-service"""
        stub = self._require_stub()
        request = file_service_pb2.UploadFileRequest(
            filename=filename,
            content=content,
            content_type=content_type,
            task_id=task_id,
        )
        try:
            response = await stub.UploadFile(request, timeout=settings.file_service_timeout)
        except grpc.aio.AioRpcError as error:
            raise FileServiceError(f"UploadFile failed: {error.code().name}") from error
        return {
            "file_id": response.file_id,
            "filename": response.original_name,
            "size": response.size,
            "content_type": content_type,
            "version": response.version,
        }

    async def download_file(
        self,
        file_id: str,
        version: int = 0,
    ) -> tuple[bytes, str, str, int]:
        """Скачивает файл из file-service"""
        stub = self._require_stub()
        request = file_service_pb2.DownloadFileRequest(file_id=file_id, version=version)
        try:
            response = await stub.DownloadFile(request, timeout=settings.file_service_timeout)
        except grpc.aio.AioRpcError as error:
            raise FileServiceError(f"DownloadFile failed: {error.code().name}") from error
        return response.content, response.filename, response.content_type, response.version


file_client = FileServiceClient()
