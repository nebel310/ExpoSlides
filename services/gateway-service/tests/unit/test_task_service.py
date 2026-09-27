from unittest.mock import AsyncMock

import pytest
from app.errors import TaskNotFoundError
from app.repositories.sessions import SessionRepository
from app.repositories.tasks import TaskRepository
from app.services import task_service as ts_module
from app.services.task_service import TaskService


async def test_create_task_persists_and_publishes(redis, monkeypatch):
    """Проверяет создание задачи и публикацию события"""
    publish = AsyncMock()
    monkeypatch.setattr(ts_module.kafka_producer, "publish", publish)
    await SessionRepository.create(redis, "sid1")
    task = await TaskService.create_task(
        redis=redis,
        sid="sid1",
        template_file_id="tf",
        script_file_id="sf",
    )
    assert task["status"] == "queued"
    assert task["sid"] == "sid1"
    saved = await TaskRepository.get(redis, task["task_id"])
    assert saved is not None
    task_ids = await SessionRepository.get_task_ids(redis, "sid1")
    assert task["task_id"] in task_ids
    publish.assert_awaited_once()
    args, _ = publish.call_args
    assert args[0] == "task.created"
    payload = args[1]
    assert payload["payload"]["session_id"] == "sid1"
    assert payload["payload"]["template_file_id"] == "tf"
    assert payload["attempt"] == 1


async def test_get_task_returns_existing(redis):
    """Проверяет получение существующей задачи"""
    await TaskRepository.save(redis, {
        "task_id": "t1", "sid": "sid1", "status": "queued",
        "template_file_id": "tf", "script_file_id": "sf",
        "structure_file_id": None, "content_file_id": None,
        "result_file_id": None, "error": None,
        "created_at": 1.0, "updated_at": 1.0,
    })
    task = await TaskService.get_task(redis, "t1")
    assert task["task_id"] == "t1"


async def test_get_task_missing(redis):
    """Проверяет ошибку на отсутствующую задачу"""
    with pytest.raises(TaskNotFoundError):
        await TaskService.get_task(redis, "nope")


async def test_list_tasks_sorted_desc(redis):
    """Проверяет сортировку по created_at"""
    for i, created in enumerate([1.0, 3.0, 2.0], start=1):
        await TaskRepository.save(redis, {
            "task_id": f"t{i}", "sid": "sid1", "status": "queued",
            "template_file_id": "tf", "script_file_id": "sf",
            "structure_file_id": None, "content_file_id": None,
            "result_file_id": None, "error": None,
            "created_at": created, "updated_at": created,
        })
        await SessionRepository.add_task(redis, "sid1", f"t{i}")
    tasks = await TaskService.list_tasks(redis, "sid1")
    assert [t["task_id"] for t in tasks] == ["t2", "t3", "t1"]


async def test_list_tasks_empty(redis):
    """Проверяет пустой список"""
    await SessionRepository.create(redis, "sid1")
    tasks = await TaskService.list_tasks(redis, "sid1")
    assert tasks == []


async def test_list_tasks_skips_missing(redis):
    """Проверяет что пропавшие задачи не ломают список"""
    await SessionRepository.create(redis, "sid1")
    await SessionRepository.add_task(redis, "sid1", "ghost")
    tasks = await TaskService.list_tasks(redis, "sid1")
    assert tasks == []