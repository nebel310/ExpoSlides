from __future__ import annotations

import pytest
from app.kafka.schemas import (
    MessageEnvelope,
    TaskCreatedPayload,
    TaskFailedPayload,
    TaskParsedPayload,
)
from pydantic import ValidationError


def test_message_envelope_minimal() -> None:
    env = MessageEnvelope(task_id="t1")
    assert env.task_id == "t1"
    assert env.attempt == 1
    assert env.payload == {}
    assert env.error is None


def test_message_envelope_full() -> None:
    env = MessageEnvelope(task_id="t1", attempt=3, payload={"a": 1}, error="bad")
    assert env.attempt == 3
    assert env.payload == {"a": 1}
    assert env.error == "bad"


def test_message_envelope_missing_task_id() -> None:
    with pytest.raises(ValidationError):
        MessageEnvelope()


def test_message_envelope_wrong_type() -> None:
    with pytest.raises(ValidationError):
        MessageEnvelope(task_id=123)


def test_message_envelope_json_roundtrip() -> None:
    env = MessageEnvelope(task_id="t1", payload={"x": 1})
    restored = MessageEnvelope.model_validate_json(env.model_dump_json())
    assert restored.task_id == env.task_id
    assert restored.payload == env.payload


def test_task_created_payload_valid() -> None:
    p = TaskCreatedPayload(template_file_id="a", script_file_id="b")
    assert p.template_file_id == "a"
    assert p.script_file_id == "b"


def test_task_created_payload_missing_field() -> None:
    with pytest.raises(ValidationError):
        TaskCreatedPayload(template_file_id="a")


def test_task_parsed_payload_valid() -> None:
    p = TaskParsedPayload(
        structure_file_id="s", template_file_id="t", script_file_id="c"
    )
    assert p.structure_file_id == "s"


def test_task_parsed_payload_missing_field() -> None:
    with pytest.raises(ValidationError):
        TaskParsedPayload(structure_file_id="s", template_file_id="t")


def test_task_failed_payload_valid() -> None:
    p = TaskFailedPayload(stage="parser", reason="bad")
    assert p.stage == "parser"
    assert p.reason == "bad"


def test_task_failed_payload_missing_field() -> None:
    with pytest.raises(ValidationError):
        TaskFailedPayload(stage="parser")