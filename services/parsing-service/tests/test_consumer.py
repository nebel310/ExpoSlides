from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.kafka.consumer import TaskCreatedConsumer
from app.kafka.schemas import TaskCreatedPayload, TaskParsedPayload


@pytest.fixture
def fake_pipeline() -> MagicMock:
    """Мок ParserPipeline с async process"""
    pipeline = MagicMock()
    pipeline.process = AsyncMock(
        return_value=TaskParsedPayload(
            structure_file_id="s-1",
            template_file_id="tpl-1",
            script_file_id="scr-1",
        )
    )
    return pipeline


@pytest.fixture
def fake_producer() -> MagicMock:
    """Мок KafkaProducer с async publish"""
    producer = MagicMock()
    producer.publish = AsyncMock()
    return producer


@pytest.fixture
def consumer(fake_pipeline: MagicMock, fake_producer: MagicMock) -> TaskCreatedConsumer:
    """Консьюмер с мок-зависимостями, без реального Kafka"""
    return TaskCreatedConsumer(
        bootstrap_servers="kafka:9092",
        group_id="parser-service",
        topic_created="task.created",
        topic_parsed="task.parsed",
        topic_failed="task.failed",
        pipeline=fake_pipeline,
        producer=fake_producer,
    )


def _encode(envelope: dict) -> bytes:
    """Сериализует dict в JSON-байты для эмуляции сообщения"""
    return json.dumps(envelope).encode("utf-8")


@pytest.mark.asyncio
async def test_handle_message_success(consumer, fake_pipeline, fake_producer):
    """Успешный путь: publish в task.parsed с TaskParsedPayload"""
    raw = _encode(
        {
            "task_id": "task-1",
            "attempt": 1,
            "payload": {"template_file_id": "tpl-1", "script_file_id": "scr-1"},
            "error": None,
        }
    )

    await consumer._handle_message(raw)

    fake_pipeline.process.assert_awaited_once()
    args = fake_pipeline.process.call_args
    assert args[0][0] == "task-1"
    assert isinstance(args[0][1], TaskCreatedPayload)

    fake_producer.publish.assert_awaited_once()
    topic, envelope = fake_producer.publish.call_args[0]
    assert topic == "task.parsed"
    assert envelope.task_id == "task-1"
    assert envelope.payload["structure_file_id"] == "s-1"


@pytest.mark.asyncio
async def test_handle_message_pipeline_error_publishes_failed(
    consumer, fake_pipeline, fake_producer
):
    """Ошибка пайплайна: publish в task.failed со stage=parser"""
    fake_pipeline.process.side_effect = RuntimeError("boom")
    raw = _encode(
        {
            "task_id": "task-2",
            "attempt": 2,
            "payload": {"template_file_id": "tpl-2", "script_file_id": "scr-2"},
        }
    )

    await consumer._handle_message(raw)

    fake_producer.publish.assert_awaited_once()
    topic, envelope = fake_producer.publish.call_args[0]
    assert topic == "task.failed"
    assert envelope.payload["stage"] == "parser"
    assert "boom" in envelope.payload["reason"]
    assert envelope.error is not None


@pytest.mark.asyncio
async def test_handle_message_invalid_payload_publishes_failed(consumer, fake_producer):
    """Невалидный payload task.created: publish в task.failed"""
    raw = _encode(
        {
            "task_id": "task-3",
            "attempt": 1,
            "payload": {"template_file_id": "tpl-3"},
        }
    )

    await consumer._handle_message(raw)

    fake_producer.publish.assert_awaited_once()
    topic, envelope = fake_producer.publish.call_args[0]
    assert topic == "task.failed"
    assert envelope.payload["stage"] == "parser"


@pytest.mark.asyncio
async def test_handle_message_invalid_json_is_ignored(consumer, fake_producer):
    """Невалидный JSON: без публикации, только лог"""
    await consumer._handle_message(b"not-json")

    fake_producer.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_message_invalid_envelope_is_ignored(consumer, fake_producer):
    """JSON без task_id: без публикации, только лог"""
    await consumer._handle_message(_encode({"payload": {}}))

    fake_producer.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_without_start_raises():
    """run() до start() поднимает RuntimeError"""
    pipeline = MagicMock()
    pipeline.process = AsyncMock()
    producer = MagicMock()
    producer.publish = AsyncMock()
    instance = TaskCreatedConsumer(
        bootstrap_servers="kafka:9092",
        group_id="g",
        topic_created="a",
        topic_parsed="b",
        topic_failed="c",
        pipeline=pipeline,
        producer=producer,
    )
    with pytest.raises(RuntimeError):
        await instance.run()