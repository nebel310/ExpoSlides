from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.kafka_producer import GatewayKafkaProducer


async def test_publish_without_start():
    """Проверяет ошибку публикации без запуска"""
    producer = GatewayKafkaProducer()
    with pytest.raises(RuntimeError):
        await producer.publish("task.created", {"a": 1})


async def test_start_and_publish(monkeypatch):
    """Проверяет публикацию после старта"""
    instance = MagicMock()
    instance.start = AsyncMock()
    instance.send_and_wait = AsyncMock()
    monkeypatch.setattr(
        "app.services.kafka_producer.AIOKafkaProducer",
        lambda **kwargs: instance,
    )
    producer = GatewayKafkaProducer()
    await producer.start()
    await producer.publish("task.created", {"a": 1})
    instance.send_and_wait.assert_awaited_once()
    args, _ = instance.send_and_wait.call_args
    assert args[0] == "task.created"


async def test_stop_idempotent(monkeypatch):
    """Проверяет безопасную остановку"""
    producer = GatewayKafkaProducer()
    await producer.stop()
    instance = MagicMock()
    instance.start = AsyncMock()
    instance.stop = AsyncMock()
    monkeypatch.setattr(
        "app.services.kafka_producer.AIOKafkaProducer",
        lambda **kwargs: instance,
    )
    await producer.start()
    await producer.stop()
    assert producer._producer is None