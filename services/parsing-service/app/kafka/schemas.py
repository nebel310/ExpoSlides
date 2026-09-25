from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MessageEnvelope(BaseModel):
    """Общий конверт Kafka-сообщения пайплайна"""

    task_id: str
    attempt: int = 1
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class TaskCreatedPayload(BaseModel):
    """Payload топика task.created"""

    template_file_id: str
    script_file_id: str
    formats: list[str] = Field(default_factory=lambda: ["pptx"])


class TaskParsedPayload(BaseModel):
    """Payload топика task.parsed"""

    structure_file_id: str
    template_file_id: str
    script_file_id: str
    formats: list[str] = Field(default_factory=lambda: ["pptx"])


class TaskFailedPayload(BaseModel):
    """Payload топика task.failed"""

    stage: str
    reason: str