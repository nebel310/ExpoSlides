from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.kafka.schemas import (
    MessageEnvelope,
    TaskCreatedPayload,
    TaskFailedPayload,
    TaskParsedPayload,
)


def test_envelope_defaults():
    """Конверт без payload/error получает attempt=1 и пустой payload"""
    envelope = MessageEnvelope(task_id="t-1")
    assert envelope.task_id == "t-1"
    assert envelope.attempt == 1
    assert envelope.payload == {}
    assert envelope.error is None


def test_envelope_full_roundtrip():
    """Конверт с payload и error сериализуется и парсится обратно без потерь"""
    envelope = MessageEnvelope(
        task_id="t-1",
        attempt=3,
        payload={"k": "v"},
        error="boom",
    )
    raw = envelope.model_dump_json()
    restored = MessageEnvelope.model_validate_json(raw)
    assert restored == envelope


def test_envelope_requires_task_id():
    """Конверт без task_id отклоняется"""
    with pytest.raises(ValidationError):
        MessageEnvelope()


def test_task_created_payload():
    """Payload task.created принимает оба file_id"""
    payload = TaskCreatedPayload(template_file_id="tpl", script_file_id="scr")
    assert payload.template_file_id == "tpl"
    assert payload.script_file_id == "scr"


def test_task_created_payload_missing_script():
    """Payload task.created без script_file_id отклоняется"""
    with pytest.raises(ValidationError):
        TaskCreatedPayload(template_file_id="tpl")


def test_task_parsed_payload():
    """Payload task.parsed принимает три file_id"""
    payload = TaskParsedPayload(
        structure_file_id="s",
        template_file_id="t",
        script_file_id="sc",
    )
    assert payload.structure_file_id == "s"


def test_task_failed_payload():
    """Payload task.failed принимает stage и reason"""
    payload = TaskFailedPayload(stage="parser", reason="bad pptx")
    assert payload.stage == "parser"
    assert payload.reason == "bad pptx"