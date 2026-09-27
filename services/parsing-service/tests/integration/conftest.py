from __future__ import annotations

import os
from typing import AsyncIterator, Awaitable, Callable

import file_service_pb2_grpc
import grpc
import pytest
import pytest_asyncio
from app.grpc.file_service_client import FileServiceClient
from google.protobuf import empty_pb2

FILE_SERVICE_HOST = os.environ.get("FILE_SERVICE_GRPC_HOST", "localhost")
FILE_SERVICE_PORT = int(os.environ.get("FILE_SERVICE_GRPC_PORT", "50051"))
FILE_SERVICE_TARGET = f"{FILE_SERVICE_HOST}:{FILE_SERVICE_PORT}"


PPTX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)


UploadFactory = Callable[..., Awaitable[str]]


async def _is_file_service_alive() -> bool:
    """Проверяет доступность file-service через HealthCheck"""
    channel = grpc.aio.insecure_channel(FILE_SERVICE_TARGET)
    try:
        stub = file_service_pb2_grpc.FileServiceStub(channel)
        await stub.HealthCheck(empty_pb2.Empty(), timeout=3.0)
        return True
    except Exception:
        return False
    finally:
        await channel.close()


@pytest_asyncio.fixture
async def real_file_client() -> AsyncIterator[FileServiceClient]:
    """Реальный gRPC-клиент к file-service (function-scoped)"""
    if not await _is_file_service_alive():
        pytest.skip(
            f"file-service недоступен на {FILE_SERVICE_TARGET}. "
            "Запусти docker compose up -d file-service minio postgres"
        )

    client = FileServiceClient(FILE_SERVICE_HOST, FILE_SERVICE_PORT)
    await client.connect()
    try:
        yield client
    finally:
        await client.close()


@pytest_asyncio.fixture
async def uploaded_pptx(
    real_file_client: FileServiceClient,
) -> AsyncIterator[UploadFactory]:
    """Фабрика: загружает pptx и удаляет после теста"""
    created: list[str] = []

    async def _upload(content: bytes, task_id: str = "integration-test") -> str:
        file_id = await real_file_client.upload_file(
            filename="template.pptx",
            content=content,
            content_type=PPTX_CONTENT_TYPE,
            task_id=task_id,
        )
        created.append(file_id)
        return file_id

    try:
        yield _upload
    finally:
        for file_id in created:
            try:
                await real_file_client.delete_file(file_id)
            except Exception:
                pass


@pytest_asyncio.fixture
async def uploaded_pptx_factory(
    real_file_client: FileServiceClient,
) -> AsyncIterator[UploadFactory]:
    """Фабрика с параметром filename"""
    created: list[str] = []

    async def _upload(
        content: bytes,
        task_id: str = "integration-test",
        filename: str = "template.pptx",
    ) -> str:
        file_id = await real_file_client.upload_file(
            filename=filename,
            content=content,
            content_type=PPTX_CONTENT_TYPE,
            task_id=task_id,
        )
        created.append(file_id)
        return file_id

    try:
        yield _upload
    finally:
        for file_id in created:
            try:
                await real_file_client.delete_file(file_id)
            except Exception:
                pass