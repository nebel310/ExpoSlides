import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.network import (
    ContentReadyPayload,
    MessageEnvelope,
    _normalize_formats,
    process_message,
)
from pydantic import ValidationError


def test_message_envelope_defaults():
    """MessageEnvelope заполняет attempt=1"""
    envelope = MessageEnvelope(
        task_id=str(uuid4()),
        payload={},
    )
    assert envelope.attempt == 1
    assert envelope.error is None


def test_message_envelope_requires_task_id():
    """task_id обязателен"""
    with pytest.raises(ValidationError):
        MessageEnvelope(payload={})


def test_content_ready_payload_default_formats():
    """formats по умолчанию = ['pptx']"""
    payload = ContentReadyPayload(
        structure_file_id=uuid4(),
        content_file_id=uuid4(),
        template_file_id=uuid4(),
        script_file_id=uuid4(),
    )
    assert payload.formats == ["pptx"]


def test_content_ready_payload_full():
    """Payload принимает все поля"""
    payload = ContentReadyPayload(
        structure_file_id=uuid4(),
        content_file_id=uuid4(),
        template_file_id=uuid4(),
        script_file_id=uuid4(),
        formats=["pptx", "pdf", "html"],
    )
    assert "pdf" in payload.formats


def test_normalize_formats_no_pptx():
    """pptx добавляется всегда"""
    assert _normalize_formats(["pdf"]) == {"pptx", "pdf"}


def test_normalize_formats_unknown_only():
    """Неизвестные форматы отбрасываются, pptx остаётся"""
    assert _normalize_formats(["exe"]) == {"pptx"}


async def test_process_message_publishes_failure_on_exception():
    """Ошибка обработки превращается в task.failed со stage=builder"""
    pipeline = MagicMock()
    pipeline.process = AsyncMock(side_effect=RuntimeError("boom"))
    producer = MagicMock()
    producer.send_and_wait = AsyncMock()
    settings = MagicMock()
    settings.kafka_topic_task_failed = "task.failed"
    settings.kafka_topic_task_built = "task.built"

    raw = json.dumps({
        "task_id": str(uuid4()),
        "attempt": 1,
        "payload": {
            "structure_file_id": str(uuid4()),
            "content_file_id": str(uuid4()),
            "template_file_id": str(uuid4()),
            "script_file_id": str(uuid4()),
        },
    }).encode()

    await process_message(raw, pipeline, producer, settings)

    producer.send_and_wait.assert_awaited_once()
    args, _ = producer.send_and_wait.call_args
    assert args[0] == "task.failed"
    body = json.loads(args[1].decode())
    assert body["payload"]["stage"] == "builder"
    assert body["error"]


async def test_process_message_skips_invalid_envelope():
    """Невалидный конверт не публикует ничего"""
    pipeline = MagicMock()
    pipeline.process = AsyncMock()
    producer = MagicMock()
    producer.send_and_wait = AsyncMock()
    settings = MagicMock()

    await process_message(b"not-json", pipeline, producer, settings)
    producer.send_and_wait.assert_not_awaited()