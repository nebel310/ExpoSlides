import uuid

import grpc
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
from google.protobuf.empty_pb2 import Empty
from sqlalchemy import func, select

from .config import settings
from .database import async_session
from .minio_storage import MinioStorage
from .models import File
from .validators import get_extension_for_type, validate_file


class FileService(FileServiceServicer):
    """gRPC сервис для загрузки, скачивания и удаления версий файлов"""

    async def UploadFile(self, request: UploadFileRequest, context: grpc.aio.ServicerContext) -> UploadFileResponse:
        """Загрузить новую версию файла (или создать новый файл)"""
        filename = request.filename
        content = request.content

        if len(content) > settings.max_upload_size:
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "File too large")

        file_type = validate_file(filename, content)
        if file_type is None:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid file type or content")

        extension = get_extension_for_type(file_type)
        content_type = request.content_type or "application/octet-stream"

        async with async_session() as session:
            if request.file_id:
                file_id = request.file_id
                result = await session.execute(
                    select(func.max(File.version)).where(File.file_id == file_id)
                )
                max_version = result.scalar()
                if max_version is None:
                    await context.abort(grpc.StatusCode.NOT_FOUND, "File not found")
                version = max_version + 1
            else:
                file_id = str(uuid.uuid4())
                version = 1

            object_name = f"{file_id}/v{version}{extension}"

            await MinioStorage.save_file(
                content,
                object_name,
                content_type,
                metadata={"original_name": filename},
            )

            file_record = File(
                file_id=file_id,
                version=version,
                object_key=object_name,
                original_name=filename,
                content_type=content_type,
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
            version=version,
        )

    async def DownloadFile(self, request: DownloadFileRequest, context: grpc.aio.ServicerContext) -> DownloadFileResponse:
        """Скачать файл по идентификатору и версии"""
        file_record = await self._get_file_record(request.file_id, request.version, context)

        data = await MinioStorage.get_file(file_record.object_key)
        if data is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "File not found in storage")

        content, content_type, _ = data
        return DownloadFileResponse(
            content=content,
            filename=file_record.original_name,
            content_type=content_type,
            version=file_record.version,
        )

    async def DeleteFile(self, request: DeleteFileRequest, context: grpc.aio.ServicerContext) -> Empty:
        """Удалить все версии файла по идентификатору"""
        async with async_session() as session:
            result = await session.execute(select(File).where(File.file_id == request.file_id))
            records = result.scalars().all()
            if not records:
                await context.abort(grpc.StatusCode.NOT_FOUND, "File not found")

            for record in records:
                await MinioStorage.delete_file(record.object_key)
                await session.delete(record)
            await session.commit()

        return Empty()

    async def GetFileInfo(self, request: GetFileInfoRequest, context: grpc.aio.ServicerContext) -> GetFileInfoResponse:
        """Вернуть метаданные файла по идентификатору и версии"""
        file_record = await self._get_file_record(request.file_id, request.version, context)

        return GetFileInfoResponse(
            file_id=file_record.file_id,
            original_name=file_record.original_name,
            object_key=file_record.object_key,
            content_type=file_record.content_type,
            size=file_record.size,
            task_id=file_record.task_id or "",
            created_at=file_record.created_at.isoformat(),
            version=file_record.version,
        )

    async def HealthCheck(self, request: Empty, context: grpc.aio.ServicerContext) -> HealthCheckResponse:
        """Вернуть статус сервиса"""
        return HealthCheckResponse(status="ok")

    @classmethod
    async def _get_file_record(cls, file_id: str, version: int, context: grpc.aio.ServicerContext) -> File:
        """Получить запись файла по id и версии (0 — последняя версия)"""
        async with async_session() as session:
            if version == 0:
                result = await session.execute(
                    select(File).where(File.file_id == file_id).order_by(File.version.desc()).limit(1)
                )
            else:
                result = await session.execute(
                    select(File).where(File.file_id == file_id, File.version == version)
                )
            file_record = result.scalar_one_or_none()
            if file_record is None:
                await context.abort(grpc.StatusCode.NOT_FOUND, "File not found")
            return file_record