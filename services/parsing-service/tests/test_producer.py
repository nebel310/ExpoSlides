from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.kafka.producer import KafkaProducer
from app.kafka.schemas import MessageEnvelope


@pytest.fixture
def fake_aiokafka(monkeypatch) -> MagicMock:
    """Подменяет AIOKafkaProducer на мок"""
    fake = MagicMock()
    fake.start = AsyncMock()
    fake.stop = AsyncMock()
    fake.send_and_wait = AsyncMock()
    monkeypatch.setattr("app.kafka.producer.AIOKafkaProducer", lambda **kwargs: fake)
    return fake


@pytest.mark.asyncio
async def test_start_and_stop(fake_aiokafka):
    """start создаёт и запускает продюсер, stop — останавливает"""
    producer = KafkaProducer("kafka:9092")
    await producer.start()
    fake_aiokafka.start.assert_awaited_once()
    await producer.stop()
    fake_aiokafka.stop.assert_awaited_once()
    assert producer._producer is None


@pytest.mark.asyncio
async def test_publish_serializes_envelope(fake_aiokafka):
    """publish отправляет JSON-конверт в указанный топик"""
    producer = KafkaProducer("kafka:9092")
    await producer.start()
    envelope = MessageEnvelope(task_id="t-1", payload={"a": 1})
    await producer.publish("task.parsed", envelope)
    topic, raw = fake_aiokafka.send_and_wait.call_args[0]
    assert topic == "task.parsed"
    data = json.loads(raw.decode("utf-8"))
    assert data["task_id"] == "t-1"
    assert data["attempt"] == 1
    assert data["payload"] == {"a": 1}
    assert data["error"] is None


@pytest.mark.asyncio
async def test_publish_without_start_raises():
    """publish до start поднимает RuntimeError"""
    producer = KafkaProducer("kafka:9092")
    with pytest.raises(RuntimeError):
        await producer.publish("task.parsed", MessageEnvelope(task_id="t"))