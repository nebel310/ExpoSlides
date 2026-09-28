
import pytest
import pytest_asyncio
from aiokafka import AIOKafkaProducer
from app.config import settings
from app.grpc.file_service_client import FileServiceClient
from helpers import (
    FILE_SERVICE_HOST,
    FILE_SERVICE_PORT,
    KAFKA_BOOTSTRAP,
    new_suffix,
)


@pytest.fixture
def custom_topics(monkeypatch):
    """Подменить имена топиков на уникальные для изоляции теста"""
    suffix = new_suffix()
    topics = {
        "parsed": f"test.task.parsed.{suffix}",
        "content_ready": f"test.task.content_ready.{suffix}",
        "content_retry": f"test.task.content_retry.{suffix}",
        "failed": f"test.task.failed.{suffix}",
    }
    monkeypatch.setattr(settings, "kafka_topic_task_parsed", topics["parsed"])
    monkeypatch.setattr(settings, "kafka_topic_task_content_ready", topics["content_ready"])
    monkeypatch.setattr(settings, "kafka_topic_task_content_retry", topics["content_retry"])
    monkeypatch.setattr(settings, "kafka_topic_task_failed", topics["failed"])
    return topics


@pytest_asyncio.fixture
async def file_client():
    """Реальный клиент file-service"""
    client = FileServiceClient(host=FILE_SERVICE_HOST, port=FILE_SERVICE_PORT)
    await client.start()
    try:
        yield client
    finally:
        await client.stop()


@pytest_asyncio.fixture
async def raw_producer():
    """Продюсер для публикации входных сообщений из теста"""
    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=lambda value: __import__("json")
        .dumps(value, ensure_ascii=False)
        .encode("utf-8"),
    )
    await producer.start()
    try:
        yield producer
    finally:
        await producer.stop()