import json
from unittest.mock import AsyncMock

from app.services import kafka_consumer as kc_module
from app.services.kafka_consumer import GatewayKafkaConsumer


async def _seed_task(redis, task_id: str = "t1", sid: str = "sid1") -> None:
    """Кладёт задачу в redis"""
    from app.repositories.tasks import TaskRepository
    await TaskRepository.save(redis, {
        "task_id": task_id,
        "sid": sid,
        "status": "queued",
        "template_file_id": "tf",
        "script_file_id": "sf",
        "structure_file_id": None,
        "content_file_id": None,
        "result_file_id": None,
        "error": None,
        "created_at": 1.0,
        "updated_at": 1.0,
    })


async def test_handle_task_parsed(redis, monkeypatch):
    """Проверяет обработку task.parsed"""
    await _seed_task(redis)
    emit = AsyncMock()
    monkeypatch.setattr(kc_module, "emit_to_session", emit)
    consumer = GatewayKafkaConsumer()
    payload = {
        "task_id": "t1",
        "attempt": 1,
        "payload": {"structure_file_id": "s1"},
    }
    await consumer._handle(redis, "task.parsed", json.dumps(payload).encode())
    from app.repositories.tasks import TaskRepository
    task = await TaskRepository.get(redis, "t1")
    assert task["status"] == "generating_content"
    assert task["structure_file_id"] == "s1"
    emit.assert_awaited_once()
    args, kwargs = emit.call_args
    assert args[0] == "sid1"
    assert args[1] == "task.parsed"


async def test_handle_task_content_ready(redis, monkeypatch):
    """Проверяет обработку task.content_ready"""
    await _seed_task(redis)
    emit = AsyncMock()
    monkeypatch.setattr(kc_module, "emit_to_session", emit)
    consumer = GatewayKafkaConsumer()
    payload = {
        "task_id": "t1",
        "payload": {"content_file_id": "c1"},
    }
    await consumer._handle(redis, "task.content_ready", json.dumps(payload).encode())
    from app.repositories.tasks import TaskRepository
    task = await TaskRepository.get(redis, "t1")
    assert task["status"] == "building"
    assert task["content_file_id"] == "c1"


async def test_handle_task_built(redis, monkeypatch):
    """Проверяет обработку task.built"""
    await _seed_task(redis)
    emit = AsyncMock()
    monkeypatch.setattr(kc_module, "emit_to_session", emit)
    consumer = GatewayKafkaConsumer()
    payload = {
        "task_id": "t1",
        "payload": {"result_file_id": "r1"},
    }
    await consumer._handle(redis, "task.built", json.dumps(payload).encode())
    from app.repositories.tasks import TaskRepository
    task = await TaskRepository.get(redis, "t1")
    assert task["status"] == "done"
    assert task["result_file_id"] == "r1"


async def test_handle_task_failed(redis, monkeypatch):
    """Проверяет обработку task.failed"""
    await _seed_task(redis)
    emit = AsyncMock()
    monkeypatch.setattr(kc_module, "emit_to_session", emit)
    consumer = GatewayKafkaConsumer()
    payload = {
        "task_id": "t1",
        "payload": {"stage": "content", "reason": "boom"},
        "error": "boom",
    }
    await consumer._handle(redis, "task.failed", json.dumps(payload).encode())
    from app.repositories.tasks import TaskRepository
    task = await TaskRepository.get(redis, "t1")
    assert task["status"] == "failed"
    assert task["error"] == "boom"


async def test_handle_unknown_topic(redis, monkeypatch):
    """Проверяет игнорирование неизвестного топика"""
    await _seed_task(redis)
    emit = AsyncMock()
    monkeypatch.setattr(kc_module, "emit_to_session", emit)
    consumer = GatewayKafkaConsumer()
    await consumer._handle(redis, "task.unknown", b"{}")
    emit.assert_not_awaited()


async def test_handle_invalid_json(redis, monkeypatch):
    """Проверяет невалидный JSON"""
    emit = AsyncMock()
    monkeypatch.setattr(kc_module, "emit_to_session", emit)
    consumer = GatewayKafkaConsumer()
    await consumer._handle(redis, "task.parsed", b"not-json")
    emit.assert_not_awaited()


async def test_handle_missing_task_id(redis, monkeypatch):
    """Проверяет отсутствие task_id"""
    emit = AsyncMock()
    monkeypatch.setattr(kc_module, "emit_to_session", emit)
    consumer = GatewayKafkaConsumer()
    await consumer._handle(redis, "task.parsed", b"{}")
    emit.assert_not_awaited()


async def test_handle_task_not_in_redis(redis, monkeypatch):
    """Проверяет что событие без задачи в Redis игнорируется"""
    emit = AsyncMock()
    monkeypatch.setattr(kc_module, "emit_to_session", emit)
    consumer = GatewayKafkaConsumer()
    payload = {"task_id": "unknown", "payload": {"structure_file_id": "s"}}
    await consumer._handle(redis, "task.parsed", json.dumps(payload).encode())
    emit.assert_not_awaited()