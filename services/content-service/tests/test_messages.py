from uuid import uuid4

import pytest
from app.models.messages import (
    MessageEnvelope,
    TaskContentReadyPayload,
    TaskContentRetryPayload,
    TaskFailedPayload,
    TaskParsedPayload,
)
from pydantic import ValidationError


def _envelope_dict(payload: dict) -> dict:
    return {
        "task_id": str(uuid4()),
        "attempt": 1,
        "payload": payload,
        "error": None,
    }


def test_envelope_valid():
    """Проверить валидный конверт сообщения"""
    envelope = MessageEnvelope(**_envelope_dict({"foo": "bar"}))
    assert envelope.attempt == 1
    assert envelope.error is None
    assert envelope.payload == {"foo": "bar"}


def test_envelope_valid_with_attempt_and_error():
    """Проверить конверт с заданными attempt и error"""
    payload = _envelope_dict({"foo": "bar"})
    payload["attempt"] = 3
    payload["error"] = "boom"
    envelope = MessageEnvelope(**payload)
    assert envelope.attempt == 3
    assert envelope.error == "boom"


def test_envelope_invalid_task_id():
    """Проверить отклонение невалидного task_id"""
    payload = _envelope_dict({"foo": "bar"})
    payload["task_id"] = "not-a-uuid"
    with pytest.raises(ValidationError):
        MessageEnvelope(**payload)


@pytest.mark.parametrize("attempt", [0, -1])
def test_envelope_invalid_attempt(attempt):
    """Проверить отклонение attempt меньше единицы"""
    payload = _envelope_dict({"foo": "bar"})
    payload["attempt"] = attempt
    with pytest.raises(ValidationError):
        MessageEnvelope(**payload)


def test_task_parsed_payload_valid():
    """Проверить валидный payload task.parsed"""
    payload = TaskParsedPayload(
        structure_file_id=uuid4(),
        template_file_id=uuid4(),
        script_file_id=uuid4(),
    )
    assert payload.structure_file_id is not None


def test_task_parsed_payload_invalid_file_id():
    """Проверить отклонение невалидного file_id"""
    with pytest.raises(ValidationError):
        TaskParsedPayload(
            structure_file_id="bad",
            template_file_id=uuid4(),
            script_file_id=uuid4(),
        )


def test_task_parsed_payload_missing_field():
    """Проверить отклонение payload без обязательного поля"""
    with pytest.raises(ValidationError):
        TaskParsedPayload(
            template_file_id=uuid4(),
            script_file_id=uuid4(),
        )


def test_task_content_ready_payload_valid():
    """Проверить валидный payload task.content_ready"""
    payload = TaskContentReadyPayload(
        structure_file_id=uuid4(),
        content_file_id=uuid4(),
        template_file_id=uuid4(),
        script_file_id=uuid4(),
    )
    assert payload.content_file_id is not None


def test_task_content_ready_payload_missing_content_file_id():
    """Проверить отклонение payload без content_file_id"""
    with pytest.raises(ValidationError):
        TaskContentReadyPayload(
            structure_file_id=uuid4(),
            template_file_id=uuid4(),
            script_file_id=uuid4(),
        )


def test_task_content_retry_payload_valid():
    """Проверить валидный payload task.content_retry"""
    payload = TaskContentRetryPayload(
        structure_file_id=uuid4(),
        script_file_id=uuid4(),
        template_file_id=uuid4(),
        feedback_file_id=uuid4(),
        attempt=2,
    )
    assert payload.attempt == 2


def test_task_content_retry_payload_invalid_attempt():
    """Проверить отклонение attempt меньше единицы в retry payload"""
    with pytest.raises(ValidationError):
        TaskContentRetryPayload(
            structure_file_id=uuid4(),
            script_file_id=uuid4(),
            template_file_id=uuid4(),
            feedback_file_id=uuid4(),
            attempt=0,
        )


@pytest.mark.parametrize(
    "stage",
    ["parser", "content", "evaluation", "builder"],
)
def test_task_failed_payload_valid_stages(stage):
    """Проверить валидные значения stage"""
    payload = TaskFailedPayload(stage=stage, reason="something went wrong")
    assert payload.stage == stage


def test_task_failed_payload_invalid_stage():
    """Проверить отклонение невалидного stage"""
    with pytest.raises(ValidationError):
        TaskFailedPayload(stage="unknown", reason="x")


def test_task_failed_payload_empty_reason():
    """Проверить отклонение пустого reason"""
    with pytest.raises(ValidationError):
        TaskFailedPayload(stage="content", reason="")