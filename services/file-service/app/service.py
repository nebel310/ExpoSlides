import uuid
from pathlib import Path

import grpc
from google.protobuf.empty_pb2 import Empty

from file_service_pb2 import (
    DeleteFileRequest,
    DownloadFileRequest,
    DownloadFileResponse,
    HealthCheckResponse,
    UploadFileRequest,
    UploadFileResponse,
)
from file_service_pb2_grpc import FileServiceServicer

from .config import settings
from .minio_storage import MinioStorage
from .validators import validate_pptx


class FileService(FileServiceServicer):
    """gRPC сервис для загрузки, скачивания и удаления файлов"""

    async def UploadFile(self, request: UploadFileRequest, context: grpc.aio.ServicerContext) -> UploadFileResponse:
        """Обработать загрузку файла, провалидировать и сохранить в MinIO"""
        filename = request.filename
        content = request.content
        content_type = request.content_type

        if len(content) > settings.max_upload_size:
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "File too large")

        if not validate_pptx(filename, content_type, content):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid file type, only .pptx allowed")

        file_id = str(uuid.uuid4())
        extension = Path(filename).suffix or ".pptx"
        object_name = f"{file_id}{extension}"

        await MinioStorage.save_file(content, object_name, content_type)

        return UploadFileResponse(
            file_id=file_id,
            original_name=filename,
            size=len(content),
        )

    async def DownloadFile(self, request: DownloadFileRequest, context: grpc.aio.ServicerContext) -> DownloadFileResponse:
        """Обработать скачивание файла по идентификатору"""
        file_id = request.file_id
        for ext in [".pptx", ".json", ".txt"]:
            candidate = f"{file_id}{ext}"
            data = await MinioStorage.get_file(candidate)
            if data:
                content, content_type, original_name = data
                return DownloadFileResponse(
                    content=content,
                    filename=original_name,
                    content_type=content_type,
                )
        await context.abort(grpc.StatusCode.NOT_FOUND, "File not found")

    async def DeleteFile(self, request: DeleteFileRequest, context: grpc.aio.ServicerContext) -> Empty:
        """Удалить файл по идентификатору"""
        file_id = request.file_id
        for ext in [".pptx", ".json", ".txt"]:
            candidate = f"{file_id}{ext}"
            data = await MinioStorage.get_file(candidate)
            if data:
                await MinioStorage.delete_file(candidate)
                return Empty()
        await context.abort(grpc.StatusCode.NOT_FOUND, "File not found")

    async def HealthCheck(self, request: Empty, context: grpc.aio.ServicerContext) -> HealthCheckResponse:
        """Вернуть статус сервиса"""
        return HealthCheckResponse(status="ok")