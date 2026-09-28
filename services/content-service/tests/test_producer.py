from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.kafka.producer import KafkaProducer
from app.models.messages import MessageEnvelope


def _make_envelope() -> MessageEnvelope:
    """Собрать валидный конверт для тестов"""
    return MessageEnvelope(
        task_id=uuid4(),
        attempt=1,
        payload={"structure_file_id": str(uuid4())},
        error=None,
    )


@pytest.mark.asyncio
async def test_start_creates_producer_and_starts():
    """Проверить, что start создаёт и запускает AIOKafkaProducer"""
    with patch("app.kafka.producer.AIOKafkaProducer") as mock_cls:
        mock_producer = MagicMock()
        mock_producer.start = AsyncMock()
        mock_cls.return_value = mock_producer
        producer = KafkaProducer(bootstrap_servers="kafka:9092")
        await producer.start()
        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args.kwargs
        assert call_kwargs["bootstrap_servers"] == "kafka:9092"
        mock_producer.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_stops_producer():
    """Проверить, что stop останавливает продюсер"""
    with patch("app.kafka.producer.AIOKafkaProducer") as mock_cls:
        mock_producer = MagicMock()
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()
        mock_cls.return_value = mock_producer
        producer = KafkaProducer(bootstrap_servers="kafka:9092")
        await producer.start()
        await producer.stop()
        mock_producer.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_without_start_is_safe():
    """Проверить, что stop без start не падает"""
    producer = KafkaProducer(bootstrap_servers="kafka:9092")
    await producer.stop()


@pytest.mark.asyncio
async def test_publish_valid_envelope():
    """Проверить публикацию валидного конверта"""
    with patch("app.kafka.producer.AIOKafkaProducer") as mock_cls:
        mock_producer = MagicMock()
        mock_producer.start = AsyncMock()
        mock_producer.send_and_wait = AsyncMock()
        mock_cls.return_value = mock_producer
        producer = KafkaProducer(bootstrap_servers="kafka:9092")
        await producer.start()
        envelope = _make_envelope()
        await producer.publish("task.content_ready", envelope)
        mock_producer.send_and_wait.assert_awaited_once()
        topic_arg, value_arg = mock_producer.send_and_wait.await_args.args
        assert topic_arg == "task.content_ready"
        assert value_arg["task_id"] == str(envelope.task_id)
        assert value_arg["attempt"] == 1
        assert value_arg["payload"] == envelope.payload
        assert value_arg["error"] is None


@pytest.mark.asyncio
async def test_publish_before_start_raises():
    """Проверить ошибку при publish без start"""
    producer = KafkaProducer(bootstrap_servers="kafka:9092")
    with pytest.raises(RuntimeError):
        await producer.publish("task.content_ready", _make_envelope())


@pytest.mark.asyncio
async def test_publish_propagates_send_error():
    """Проверить проброс ошибки отправки наверх"""
    with patch("app.kafka.producer.AIOKafkaProducer") as mock_cls:
        mock_producer = MagicMock()
        mock_producer.start = AsyncMock()
        mock_producer.send_and_wait = AsyncMock(side_effect=RuntimeError("broker down"))
        mock_cls.return_value = mock_producer
        producer = KafkaProducer(bootstrap_servers="kafka:9092")
        await producer.start()
        with pytest.raises(RuntimeError):
            await producer.publish("task.content_ready", _make_envelope())


@pytest.mark.asyncio
async def test_value_serializer_encodes_json_utf8():
    """Проверить, что value_serializer сериализует в UTF-8 JSON"""
    with patch("app.kafka.producer.AIOKafkaProducer") as mock_cls:
        mock_producer = MagicMock()
        mock_producer.start = AsyncMock()
        mock_cls.return_value = mock_producer
        producer = KafkaProducer(bootstrap_servers="kafka:9092")
        await producer.start()
        serializer = mock_cls.call_args.kwargs["value_serializer"]
        encoded = serializer({"key": "значение"})
        assert isinstance(encoded, bytes)
        assert "значение" in encoded.decode("utf-8")