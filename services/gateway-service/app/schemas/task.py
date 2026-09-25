from typing import Literal, Optional

from pydantic import BaseModel, Field


TaskStatus = Literal[
    "queued",
    "generating_content",
    "building",
    "done",
    "failed",
]


class TaskInfo(BaseModel):
    """Информация о задаче"""
    task_id: str
    status: TaskStatus
    template_file_id: str
    script_file_id: str
    structure_file_id: Optional[str] = None
    content_file_id: Optional[str] = None
    result_file_id: Optional[str] = None
    error: Optional[str] = None
    formats: list[str] = Field(default_factory=lambda: ["pptx"])
    extra_files: dict[str, str] = Field(default_factory=dict)
    created_at: float
    updated_at: float


class TaskListResponse(BaseModel):
    """Список задач сессии"""
    tasks: list[TaskInfo]


class CreateTaskRequest(BaseModel):
    """Запрос на создание задачи"""
    template_file_id: str
    script_file_id: str
    formats: list[str] = Field(default_factory=lambda: ["pptx"])


class CreateTaskResponse(BaseModel):
    """Ответ на создание задачи"""
    task_id: str