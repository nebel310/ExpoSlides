from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class MessageEnvelope(BaseModel):
    """Общий конверт сообщения в Kafka"""

    task_id: UUID
    attempt: int = Field(default=1, ge=1)
    payload: dict[str, Any]
    error: str | None = None


class TaskParsedPayload(BaseModel):
    """Payload топика task.parsed"""

    structure_file_id: UUID
    template_file_id: UUID
    script_file_id: UUID


class TaskContentReadyPayload(BaseModel):
    """Payload топика task.content_ready"""

    structure_file_id: UUID
    content_file_id: UUID
    template_file_id: UUID
    script_file_id: UUID


class TaskContentRetryPayload(BaseModel):
    """Payload топика task.content_retry"""

    structure_file_id: UUID
    script_file_id: UUID
    template_file_id: UUID
    feedback_file_id: UUID
    attempt: int = Field(ge=1)


class TaskFailedPayload(BaseModel):
    """Payload топика task.failed"""

    stage: Literal["parser", "content", "evaluation", "builder"]
    reason: str = Field(min_length=1)