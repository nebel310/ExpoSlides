import pytest
from app.schemas.files import UploadFileResponse
from app.schemas.session import SessionBootstrapResponse
from app.schemas.task import (
    CreateTaskRequest,
    CreateTaskResponse,
    TaskInfo,
    TaskListResponse,
)
from pydantic import ValidationError


def test_session_bootstrap_schema():
    """Проверяет схему ответа bootstrap"""
    obj = SessionBootstrapResponse(sid="abc")
    assert obj.sid == "abc"
    with pytest.raises(ValidationError):
        SessionBootstrapResponse()


def test_create_task_request_schema():
    """Проверяет схему запроса на создание задачи"""
    obj = CreateTaskRequest(template_file_id="t", script_file_id="s")
    assert obj.template_file_id == "t"
    assert obj.script_file_id == "s"
    with pytest.raises(ValidationError):
        CreateTaskRequest(template_file_id="t")


def test_create_task_response_schema():
    """Проверяет схему ответа на создание задачи"""
    obj = CreateTaskResponse(task_id="abc")
    assert obj.task_id == "abc"
    with pytest.raises(ValidationError):
        CreateTaskResponse()


def test_task_info_schema_valid():
    """Проверяет валидную схему задачи"""
    obj = TaskInfo(
        task_id="t1",
        status="queued",
        template_file_id="tf",
        script_file_id="sf",
        created_at=1.0,
        updated_at=2.0,
    )
    assert obj.status == "queued"
    assert obj.result_file_id is None
    assert obj.error is None


def test_task_info_schema_invalid_status():
    """Проверяет что неизвестный статус отклоняется"""
    with pytest.raises(ValidationError):
        TaskInfo(
            task_id="t1",
            status="unknown",
            template_file_id="tf",
            script_file_id="sf",
            created_at=1.0,
            updated_at=2.0,
        )


def test_task_list_response_schema():
    """Проверяет список задач"""
    obj = TaskListResponse(tasks=[])
    assert obj.tasks == []
    obj2 = TaskListResponse(tasks=[
        TaskInfo(
            task_id="t1", status="done",
            template_file_id="tf", script_file_id="sf",
            created_at=1.0, updated_at=2.0,
        )
    ])
    assert len(obj2.tasks) == 1


def test_upload_file_response_schema():
    """Проверяет схему ответа загрузки файла"""
    obj = UploadFileResponse(
        file_id="f1", filename="a.pptx",
        size=100, content_type="application/x", version=1,
    )
    assert obj.file_id == "f1"
    assert obj.version == 1
    with pytest.raises(ValidationError):
        UploadFileResponse(file_id="f1")