from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.kafka.consumer import KafkaConsumer
from app.models.messages import MessageEnvelope


def _make_record(topic: str, value: dict) -> MagicMock:
    """Собрать мок ConsumerRecord с заданным топиком и значением"""
    import json

    record = MagicMock()
    record.topic = topic
    record.value = json.dumps(value).encode("utf-8")
    record.partition = 0
    record.offset = 1
    return record


def _valid_parsed_message() -> dict:
    """Собрать валидное сообщение task.parsed"""
    return {
        "task_id": str(uuid4()),
        "attempt": 1,
        "payload": {
            "structure_file_id": str(uuid4()),
            "template_file_id": str(uuid4()),
            "script_file_id": str(uuid4()),
        },
        "error": None,
    }


def _valid_retry_message() -> dict:
    """Собрать валидное сообщение task.content_retry"""
    return {
        "task_id": str(uuid4()),
        "attempt": 2,
        "payload": {
            "structure_file_id": str(uuid4()),
            "script_file_id": str(uuid4()),
            "template_file_id": str(uuid4()),
            "feedback_file_id": str(uuid4()),
            "attempt": 2,
        },
        "error": None,
    }


@pytest.mark.asyncio
async def test_start_subscribes_to_topics():
    """Проверить подписку на два топика при старте"""
    with patch("app.kafka.consumer.AIOKafkaConsumer") as mock_cls:
        mock_consumer = MagicMock()
        mock_consumer.start = AsyncMock()
        mock_cls.return_value = mock_consumer
        handler = AsyncMock()
        consumer = KafkaConsumer(
            handler=handler,
            topics=["task.parsed", "task.content_retry"],
            bootstrap_servers="kafka:9092",
            group_id="content-service",
        )
        await consumer.start()
        mock_cls.assert_called_once()
        call_args = mock_cls.call_args
        assert "task.parsed" in call_args.args
        assert "task.content_retry" in call_args.args
        assert call_args.kwargs["enable_auto_commit"] is False
        mock_consumer.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_without_start_is_safe():
    """Проверить, что stop без start не падает"""
    consumer = KafkaConsumer(handler=AsyncMock())
    await consumer.stop()


@pytest.mark.asyncio
async def test_process_valid_parsed_calls_handler():
    """Проверить вызов handler для валидного task.parsed"""
    handler = AsyncMock()
    consumer = KafkaConsumer(
        handler=handler,
        topics=["task.parsed"],
        bootstrap_servers="kafka:9092",
        group_id="content-service",
    )
    record = _make_record("task.parsed", _valid_parsed_message())
    await consumer.process_message(record)
    handler.assert_awaited_once()
    envelope_arg, payload_arg, topic_arg = handler.await_args.args
    assert isinstance(envelope_arg, MessageEnvelope)
    assert envelope_arg.attempt == 1
    assert topic_arg == "task.parsed"
    assert payload_arg.structure_file_id is not None


@pytest.mark.asyncio
async def test_process_valid_retry_calls_handler():
    """Проверить вызов handler для валидного task.content_retry"""
    handler = AsyncMock()
    consumer = KafkaConsumer(
        handler=handler,
        topics=["task.content_retry"],
        bootstrap_servers="kafka:9092",
        group_id="content-service",
    )
    record = _make_record("task.content_retry", _valid_retry_message())
    await consumer.process_message(record)
    handler.assert_awaited_once()
    envelope_arg, payload_arg, topic_arg = handler.await_args.args
    assert topic_arg == "task.content_retry"
    assert payload_arg.attempt == 2


@pytest.mark.asyncio
async def test_process_unknown_topic_skips_handler():
    """Проверить, что неизвестный топик не вызывает handler"""
    handler = AsyncMock()
    consumer = KafkaConsumer(
        handler=handler,
        topics=["task.parsed"],
        bootstrap_servers="kafka:9092",
        group_id="content-service",
    )
    record = _make_record("task.unknown", _valid_parsed_message())
    await consumer.process_message(record)
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_invalid_json_skips_handler():
    """Проверить, что битый JSON не вызывает handler"""
    handler = AsyncMock()
    consumer = KafkaConsumer(
        handler=handler,
        topics=["task.parsed"],
        bootstrap_servers="kafka:9092",
        group_id="content-service",
    )
    record = MagicMock()
    record.topic = "task.parsed"
    record.value = b"not a json {"
    await consumer.process_message(record)
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_invalid_envelope_skips_handler():
    """Проверить, что невалидный конверт не вызывает handler"""
    handler = AsyncMock()
    consumer = KafkaConsumer(
        handler=handler,
        topics=["task.parsed"],
        bootstrap_servers="kafka:9092",
        group_id="content-service",
    )
    bad = _valid_parsed_message()
    bad["task_id"] = "not-a-uuid"
    record = _make_record("task.parsed", bad)
    await consumer.process_message(record)
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_invalid_payload_skips_handler():
    """Проверить, что невалидный payload не вызывает handler"""
    handler = AsyncMock()
    consumer = KafkaConsumer(
        handler=handler,
        topics=["task.parsed"],
        bootstrap_servers="kafka:9092",
        group_id="content-service",
    )
    bad = _valid_parsed_message()
    bad["payload"] = {"structure_file_id": str(uuid4())}
    record = _make_record("task.parsed", bad)
    await consumer.process_message(record)
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_handler_error_is_swallowed():
    """Проверить, что ошибка handler не пробрасывается наружу"""
    handler = AsyncMock(side_effect=RuntimeError("pipeline error"))
    consumer = KafkaConsumer(
        handler=handler,
        topics=["task.parsed"],
        bootstrap_servers="kafka:9092",
        group_id="content-service",
    )
    record = _make_record("task.parsed", _valid_parsed_message())
    await consumer.process_message(record)
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_commits_offset_after_handler():
    """Проверить, что run коммитит offset после обработки сообщения"""
    handler = AsyncMock()
    consumer = KafkaConsumer(
        handler=handler,
        topics=["task.parsed"],
        bootstrap_servers="kafka:9092",
        group_id="content-service",
    )

    record = _make_record("task.parsed", _valid_parsed_message())

    async def _fake_iter(_self):
        yield record

    with patch("app.kafka.consumer.AIOKafkaConsumer") as mock_cls:
        mock_consumer = MagicMock()
        mock_consumer.start = AsyncMock()
        mock_consumer.stop = AsyncMock()
        mock_consumer.commit = AsyncMock()
        mock_consumer.__aiter__ = _fake_iter
        mock_cls.return_value = mock_consumer
        await consumer.start()

        async def _stop_after_one():
            consumer._running = False

        original_process = consumer.process_message

        async def _process_then_stop(msg):
            await original_process(msg)
            await _stop_after_one()

        consumer.process_message = _process_then_stop
        await consumer.run()
        mock_consumer.commit.assert_awaited_once()