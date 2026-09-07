import uuid

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
from .validators import get_extension_for_type, validate_file




class FileService(FileServiceServicer):
    """gRPC сервис для загрузки, скачивания и удаления файлов"""

    async def UploadFile(self, request: UploadFileRequest, context: grpc.aio.ServicerContext) -> UploadFileResponse:
        """Обработать загрузку файла, провалидировать и сохранить в MinIO"""
        filename = request.filename
        content = request.content

        if len(content) > settings.max_upload_size:
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "File too large")

        file_type = validate_file(filename, content)
        if file_type is None:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid file type or content")

        file_id = str(uuid.uuid4())
        extension = get_extension_for_type(file_type)
        object_name = f"{file_id}{extension}"

        await MinioStorage.save_file(
            content,
            object_name,
            request.content_type or "application/octet-stream",
            metadata={"original_name": filename},
        )

        return UploadFileResponse(
            file_id=file_id,
            original_name=filename,
            size=len(content),
        )


    async def DownloadFile(self, request: DownloadFileRequest, context: grpc.aio.ServicerContext) -> DownloadFileResponse:
        """Обработать скачивание файла по идентификатору"""
        file_id = request.file_id
        for ext in [".pptx", ".pdf", ".json", ".txt"]:
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
        for ext in [".pptx", ".pdf", ".json", ".txt"]:
            candidate = f"{file_id}{ext}"
            data = await MinioStorage.get_file(candidate)
            if data:
                await MinioStorage.delete_file(candidate)
                return Empty()
        await context.abort(grpc.StatusCode.NOT_FOUND, "File not found")

    async def HealthCheck(self, request: Empty, context: grpc.aio.ServicerContext) -> HealthCheckResponse:
        """Вернуть статус сервиса"""
        return HealthCheckResponse(status="ok")