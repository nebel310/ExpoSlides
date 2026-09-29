import os
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

GATEWAY_URL = os.getenv("GATEWAY_TEST_URL", "http://localhost:1000")
KAFKA_BOOTSTRAP = os.getenv("KAFKA_TEST_BOOTSTRAP", "localhost:9093")
TOPIC_CREATED = "task.created"
TOPIC_PARSED = "task.parsed"
TOPIC_CONTENT_READY = "task.content_ready"
TOPIC_BUILT = "task.built"
TOPIC_FAILED = "task.failed"


def _require_infra() -> None:
    """Пропускает тест, если gateway недоступен"""
    try:
        response = httpx.get(f"{GATEWAY_URL}/health", timeout=2.0)
    except Exception:
        pytest.skip(f"gateway недоступен по адресу {GATEWAY_URL}")
    if response.status_code != 200:
        pytest.skip(f"gateway вернул {response.status_code}")


@pytest_asyncio.fixture(scope="session", autouse=True)
async def infra() -> AsyncIterator[None]:
    """Один раз за сессию проверяет доступность инфраструктуры"""
    _require_infra()
    yield


@pytest_asyncio.fixture
async def gateway_client() -> AsyncIterator[httpx.AsyncClient]:
    """HTTP-клиент к живому gateway"""
    async with httpx.AsyncClient(base_url=GATEWAY_URL, timeout=30.0) as client:
        yield client


@pytest_asyncio.fixture
async def kafka_producer() -> AsyncIterator[AIOKafkaProducer]:
    """Продюсер для ручной публикации task.content_ready"""
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
    await producer.start()
    try:
        yield producer
    finally:
        await producer.stop()


@pytest_asyncio.fixture
async def kafka_consumer() -> AsyncIterator[AIOKafkaConsumer]:
    """Консьюмер для чтения task.parsed и task.built"""
    consumer = AIOKafkaConsumer(
        TOPIC_PARSED,
        TOPIC_BUILT,
        TOPIC_FAILED,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=f"gateway-integration-{os.getpid()}",
        enable_auto_commit=True,
        auto_offset_reset="latest",
    )
    await consumer.start()
    try:
        yield consumer
    finally:
        await consumer.stop()