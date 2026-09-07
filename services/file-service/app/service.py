import uuid
from pathlib import Path

import grpc
from google.protobuf.empty_pb2 import Empty
from sqlalchemy import select

from file_service_pb2 import (
    DeleteFileRequest,
    DownloadFileRequest,
    DownloadFileResponse,
    GetFileInfoRequest,
    GetFileInfoResponse,
    HealthCheckResponse,
    UploadFileRequest,
    UploadFileResponse,
)
from file_service_pb2_grpc import FileServiceServicer

from .config import settings
from .database import async_session
from .minio_storage import MinioStorage
from .models import File
from .validators import get_extension_for_type, validate_file




class FileService(FileServiceServicer):
    """gRPC сервис для загрузки, скачивания и удаления файлов"""

    async def UploadFile(self, request: UploadFileRequest, context: grpc.aio.ServicerContext) -> UploadFileResponse:
        """Обработать загрузку файла, провалидировать и сохранить в MinIO и БД"""
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

        async with async_session() as session:
            file_record = File(
                id=file_id,
                object_key=object_name,
                original_name=filename,
                content_type=request.content_type or "application/octet-stream",
                size=len(content),
                task_id=request.task_id or None,
            )
            session.add(file_record)
            await session.commit()

        return UploadFileResponse(
            file_id=file_id,
            original_name=filename,
            size=len(content),
            file_type=file_type,
        )

    async def DownloadFile(self, request: DownloadFileRequest, context: grpc.aio.ServicerContext) -> DownloadFileResponse:
        """Обработать скачивание файла по идентификатору"""
        file_id = request.file_id

        async with async_session() as session:
            result = await session.execute(select(File).where(File.id == file_id))
            file_record = result.scalar_one_or_none()
            if file_record is None:
                await context.abort(grpc.StatusCode.NOT_FOUND, "File not found")

        data = await MinioStorage.get_file(file_record.object_key)
        if data is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "File not found in storage")

        content, content_type, _ = data
        return DownloadFileResponse(
            content=content,
            filename=file_record.original_name,
            content_type=content_type,
        )

    async def DeleteFile(self, request: DeleteFileRequest, context: grpc.aio.ServicerContext) -> Empty:
        """Удалить файл по идентификатору"""
        file_id = request.file_id

        async with async_session() as session:
            result = await session.execute(select(File).where(File.id == file_id))
            file_record = result.scalar_one_or_none()
            if file_record is None:
                await context.abort(grpc.StatusCode.NOT_FOUND, "File not found")

            await MinioStorage.delete_file(file_record.object_key)
            await session.delete(file_record)
            await session.commit()

        return Empty()

    async def GetFileInfo(self, request: GetFileInfoRequest, context: grpc.aio.ServicerContext) -> GetFileInfoResponse:
        """Вернуть метаданные файла по идентификатору"""
        file_id = request.file_id

        async with async_session() as session:
            result = await session.execute(select(File).where(File.id == file_id))
            file_record = result.scalar_one_or_none()
            if file_record is None:
                await context.abort(grpc.StatusCode.NOT_FOUND, "File not found")

        return GetFileInfoResponse(
            file_id=file_record.id,
            original_name=file_record.original_name,
            object_key=file_record.object_key,
            content_type=file_record.content_type,
            size=file_record.size,
            task_id=file_record.task_id or "",
            created_at=file_record.created_at.isoformat(),
        )

    async def HealthCheck(self, request: Empty, context: grpc.aio.ServicerContext) -> HealthCheckResponse:
        """Вернуть статус сервиса"""
        return HealthCheckResponse(status="ok")