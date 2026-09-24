import json

from app.repositories.tasks import TaskRepository


def _task(task_id: str = "t1") -> dict:
    """Создаёт шаблон задачи"""
    return {
        "task_id": task_id,
        "sid": "sid1",
        "status": "queued",
        "template_file_id": "tf",
        "script_file_id": "sf",
        "structure_file_id": None,
        "content_file_id": None,
        "result_file_id": None,
        "error": None,
        "created_at": 1.0,
        "updated_at": 1.0,
    }


async def test_save_and_get(redis):
    """Проверяет сохранение и получение задачи"""
    task = _task()
    await TaskRepository.save(redis, task)
    loaded = await TaskRepository.get(redis, "t1")
    assert loaded is not None
    assert loaded["task_id"] == "t1"
    assert loaded["status"] == "queued"


async def test_get_missing(redis):
    """Проверяет отсутствующую задачу"""
    assert await TaskRepository.get(redis, "nope") is None


async def test_update_single_field(redis):
    """Проверяет частичное обновление"""
    await TaskRepository.save(redis, _task())
    updated = await TaskRepository.update(redis, "t1", status="done", result_file_id="r1")
    assert updated is not None
    assert updated["status"] == "done"
    assert updated["result_file_id"] == "r1"
    assert updated["template_file_id"] == "tf"


async def test_update_bumps_updated_at(redis):
    """Проверяет что updated_at меняется"""
    task = _task()
    task["updated_at"] = 0.0
    await TaskRepository.save(redis, task)
    updated = await TaskRepository.update(redis, "t1", status="done")
    assert updated["updated_at"] > 0.0


async def test_update_missing(redis):
    """Проверяет обновление несуществующей задачи"""
    assert await TaskRepository.update(redis, "nope", status="done") is None


async def test_save_sets_ttl(redis):
    """Проверяет что TTL выставляется"""
    await TaskRepository.save(redis, _task())
    ttl = await redis.ttl("task:t1")
    assert 0 < ttl <= TaskRepository.TTL


async def test_save_json_serializable(redis):
    """Проверяет что задача хранится как JSON"""
    await TaskRepository.save(redis, _task())
    raw = await redis.get("task:t1")
    parsed = json.loads(raw)
    assert parsed["task_id"] == "t1"