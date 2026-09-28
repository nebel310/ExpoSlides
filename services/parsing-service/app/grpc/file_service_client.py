from __future__ import annotations

import logging

import file_service_pb2
import file_service_pb2_grpc
import grpc

logger = logging.getLogger(__name__)


class FileServiceClient:
    """Асинхронный gRPC-клиент file-service"""

    def __init__(self, host: str, port: int) -> None:
        """Сохраняет адрес file-service и готовит пустой канал"""
        self._target = f"{host}:{port}"
        self._channel: grpc.aio.Channel | None = None
        self._stub: file_service_pb2_grpc.FileServiceStub | None = None

    async def connect(self) -> None:
        """Открывает gRPC-канал и создаёт стаб"""
        self._channel = grpc.aio.insecure_channel(self._target)
        self._stub = file_service_pb2_grpc.FileServiceStub(self._channel)
        logger.info("FileServiceClient подключён к %s", self._target)

    async def close(self) -> None:
        """Закрывает gRPC-канал"""
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
            self._stub = None

    def _get_stub(self) -> file_service_pb2_grpc.FileServiceStub:
        """Возвращает активный стаб или бросает RuntimeError"""
        if self._stub is None:
            raise RuntimeError("FileServiceClient не подключён, вызовите connect()")
        return self._stub

    async def download_file(self, file_id: str, version: int = 0) -> bytes:
        """Скачивает файл из file-service по file_id"""
        stub = self._get_stub()
        request = file_service_pb2.DownloadFileRequest(file_id=file_id, version=version)
        response = await stub.DownloadFile(request)
        return response.content

    async def upload_file(
        self,
        filename: str,
        content: bytes,
        content_type: str,
        task_id: str,
        file_id: str | None = None,
    ) -> str:
        """Загружает файл в file-service и возвращает file_id"""
        stub = self._get_stub()
        request = file_service_pb2.UploadFileRequest(
            filename=filename,
            content=content,
            content_type=content_type,
            task_id=task_id,
        )
        if file_id is not None:
            request.file_id = file_id
        response = await stub.UploadFile(request)
        return response.file_id
    
    async def delete_file(self, file_id: str) -> None:
        """Удаляет файл и все его версии из file-service"""
        stub = self._get_stub()
        request = file_service_pb2.DeleteFileRequest(file_id=file_id)
        await stub.DeleteFile(request)