import os
import sys
from pathlib import Path

import grpc
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from file_service_pb2_grpc import FileServiceStub


@pytest.fixture(scope="module")
def grpc_channel():
    """Создать gRPC канал до file-service"""
    host = os.getenv("FILE_SERVICE_GRPC_HOST", "localhost")
    port = os.getenv("FILE_SERVICE_GRPC_PORT", "50051")
    channel = grpc.insecure_channel(f"{host}:{port}")
    yield channel
    channel.close()


@pytest.fixture(scope="module")
def file_service_stub(grpc_channel):
    """Вернуть stub файлового сервиса"""
    return FileServiceStub(grpc_channel)