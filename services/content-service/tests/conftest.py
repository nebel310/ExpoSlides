import sys
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))


@pytest.fixture
def env_isolated(monkeypatch):
    """Изолировать тесты от .env файла сервиса"""
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    monkeypatch.setenv("KAFKA_GROUP_ID", "content-service")
    monkeypatch.setenv("KAFKA_TOPIC_TASK_PARSED", "task.parsed")
    monkeypatch.setenv("KAFKA_TOPIC_TASK_CONTENT_READY", "task.content_ready")
    monkeypatch.setenv("KAFKA_TOPIC_TASK_CONTENT_RETRY", "task.content_retry")
    monkeypatch.setenv("KAFKA_TOPIC_TASK_FAILED", "task.failed")
    monkeypatch.setenv("FILE_SERVICE_GRPC_HOST", "file-service")
    monkeypatch.setenv("FILE_SERVICE_GRPC_PORT", "50051")
    monkeypatch.setenv("CONTENT_SERVICE_PORT", "50053")
    return monkeypatch