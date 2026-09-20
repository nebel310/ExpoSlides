from __future__ import annotations

import os
from collections.abc import AsyncIterator

import grpc
import pytest
import pytest_asyncio

from app.grpc.file_service_client import FileServiceClient

FILE_SERVICE_HOST = os.environ.get("FILE_SERVICE_GRPC_HOST", "localhost")
FILE_SERVICE_PORT = int(os.environ.get("FILE_SERVICE_GRPC_PORT", "50051"))


def pytest_configure(config: pytest.Config) -> None:
    """Регистрирует маркер integration без правки pyproject"""
    config.addinivalue_line(
        "markers",
        "integration: тесты, требующие запущенный file-service",
    )


def _file_service_available(host: str, port: int) -> bool:
    """Проверяет доступность file-service коротким healthcheck-вызовом"""
    try:
        channel = grpc.insecure_channel(f"{host}:{port}")
        grpc.channel_ready_future(channel).result(timeout=2)
        channel.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def file_service_target() -> tuple[str, str]:
    """Возвращает host и port file-service или скипает тесты"""
    if not _file_service_available(FILE_SERVICE_HOST, FILE_SERVICE_PORT):
        pytest.skip(
            f"file-service недоступен на {FILE_SERVICE_HOST}:{FILE_SERVICE_PORT}, "
            "запусти `docker compose up -d file-service`",
        )
    return FILE_SERVICE_HOST, str(FILE_SERVICE_PORT)


@pytest_asyncio.fixture
async def file_client(
    file_service_target: tuple[str, str],
) -> AsyncIterator[FileServiceClient]:
    """Подключённый FileServiceClient с авто-закрытием"""
    host, port = file_service_target
    client = FileServiceClient(host=host, port=int(port))
    await client.connect()
    try:
        yield client
    finally:
        await client.close()