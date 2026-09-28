from unittest.mock import AsyncMock

from app.repositories.files import FileRepository
from app.services import task_service as ts_module


async def _bootstrap(client, redis) -> str:
    """Создаёт сессию через bootstrap"""
    response = await client.post("/api/session/bootstrap")
    sid = response.json()["sid"]
    for file_id in ("tf", "sf"):
        await FileRepository.grant(redis, sid, file_id)
    return sid


async def test_create_task_ok(client, redis, monkeypatch):
    """Проверяет создание задачи"""
    publish = AsyncMock()
    monkeypatch.setattr(ts_module.kafka_producer, "publish", publish)
    sid = await _bootstrap(client, redis)
    response = await client.post(
        "/api/tasks",
        json={"template_file_id": "tf", "script_file_id": "sf"},
        cookies={"exposlides_sid": sid},
    )
    assert response.status_code == 200
    body = response.json()
    assert "task_id" in body
    publish.assert_awaited_once()


async def test_create_task_without_session(client):
    """Проверяет создание задачи без сессии"""
    response = await client.post(
        "/api/tasks",
        json={"template_file_id": "tf", "script_file_id": "sf"},
    )
    assert response.status_code == 401


async def test_create_task_invalid_body(client, redis):
    """Проверяет невалидное тело запроса"""
    sid = await _bootstrap(client, redis)
    response = await client.post(
        "/api/tasks",
        json={"template_file_id": "tf"},
        cookies={"exposlides_sid": sid},
    )
    assert response.status_code == 422


async def test_list_tasks_empty(client, redis):
    """Проверяет пустой список задач"""
    sid = await _bootstrap(client, redis)
    response = await client.get(
        "/api/tasks",
        cookies={"exposlides_sid": sid},
    )
    assert response.status_code == 200
    assert response.json() == {"tasks": []}


async def test_list_tasks_with_one(client, redis, monkeypatch):
    """Проверяет список из одной задачи"""
    publish = AsyncMock()
    monkeypatch.setattr(ts_module.kafka_producer, "publish", publish)
    sid = await _bootstrap(client, redis)
    create = await client.post(
        "/api/tasks",
        json={"template_file_id": "tf", "script_file_id": "sf"},
        cookies={"exposlides_sid": sid},
    )
    task_id = create.json()["task_id"]
    response = await client.get(
        "/api/tasks",
        cookies={"exposlides_sid": sid},
    )
    body = response.json()
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["task_id"] == task_id
    assert body["tasks"][0]["status"] == "queued"


async def test_get_task_ok(client, redis, monkeypatch):
    """Проверяет получение задачи"""
    publish = AsyncMock()
    monkeypatch.setattr(ts_module.kafka_producer, "publish", publish)
    sid = await _bootstrap(client, redis)
    create = await client.post(
        "/api/tasks",
        json={"template_file_id": "tf", "script_file_id": "sf"},
        cookies={"exposlides_sid": sid},
    )
    task_id = create.json()["task_id"]
    response = await client.get(
        f"/api/tasks/{task_id}",
        cookies={"exposlides_sid": sid},
    )
    assert response.status_code == 200
    assert response.json()["task_id"] == task_id


async def test_get_task_unknown(client, redis):
    """Проверяет неизвестный task_id"""
    sid = await _bootstrap(client, redis)
    response = await client.get(
        "/api/tasks/unknown",
        cookies={"exposlides_sid": sid},
    )
    assert response.status_code == 404


async def test_get_task_other_session(client, redis, monkeypatch):
    """Проверяет доступ к задаче другой сессии"""
    publish = AsyncMock()
    monkeypatch.setattr(ts_module.kafka_producer, "publish", publish)
    sid_a = await _bootstrap(client, redis)
    create = await client.post(
        "/api/tasks",
        json={"template_file_id": "tf", "script_file_id": "sf"},
        cookies={"exposlides_sid": sid_a},
    )
    task_id = create.json()["task_id"]
    client.cookies.clear()
    sid_b = await _bootstrap(client, redis)
    assert sid_b != sid_a
    response = await client.get(
        f"/api/tasks/{task_id}",
        cookies={"exposlides_sid": sid_b},
    )
    assert response.status_code == 404


async def test_list_tasks_without_session(client):
    """Проверяет список без сессии"""
    response = await client.get("/api/tasks")
    assert response.status_code == 401
