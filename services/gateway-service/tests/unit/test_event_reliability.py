import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiokafka.structs import TopicPartition
from app.repositories.files import FileRepository
from app.repositories.tasks import TaskRepository
from app.services import kafka_consumer as module
from app.services.kafka_consumer import GatewayKafkaConsumer


async def seed(redis):
    await TaskRepository.save(redis, {
        "task_id": "task", "sid": "owner", "status": "queued", "attempt": 1,
        "error": None, "result_file_id": None,
    })


def event(topic="task.built", attempt=1, identifier="result"):
    field = {
        "task.parsed": "structure_file_id", "task.content_ready": "content_file_id",
        "task.built": "result_file_id",
    }[topic]
    return json.dumps({
        "task_id": "task", "attempt": attempt, "payload": {field: identifier},
    }).encode()


async def test_old_attempt_and_regressive_stages_cannot_replace_result(redis, monkeypatch):
    await seed(redis)
    emit = AsyncMock()
    monkeypatch.setattr(module, "emit_to_session", emit)
    consumer = GatewayKafkaConsumer()
    await consumer._handle(redis, "task.built", event(attempt=2))
    for topic, attempt in (("task.parsed", 1), ("task.content_ready", 2), ("task.built", 1)):
        await consumer._handle(redis, topic, event(topic, attempt, "late"))
    await consumer._handle(redis, "task.built", event(attempt=2, identifier="duplicate-build"))
    task = await TaskRepository.get(redis, "task")
    assert (task["status"], task["attempt"], task["result_file_id"]) == ("done", 2, "result")
    assert await FileRepository.owns(redis, "owner", "result")
    assert not await FileRepository.owns(redis, "owner", "late")
    assert not await FileRepository.owns(redis, "owner", "duplicate-build")
    emit.assert_awaited_once()


async def test_new_attempt_can_replace_terminal_state_and_clears_old_result(redis, monkeypatch):
    await seed(redis)
    monkeypatch.setattr(module, "emit_to_session", AsyncMock())
    consumer = GatewayKafkaConsumer()
    await consumer._handle(redis, "task.built", event())
    await consumer._handle(redis, "task.content_ready", event("task.content_ready", 2, "new"))
    task = await TaskRepository.get(redis, "task")
    assert task["status"] == "building"
    assert task["result_file_id"] is None
    assert task["content_file_id"] == "new"


async def test_failure_from_previous_stage_cannot_cancel_building(redis, monkeypatch):
    await seed(redis)
    monkeypatch.setattr(module, "emit_to_session", AsyncMock())
    consumer = GatewayKafkaConsumer()
    await consumer._handle(redis, "task.content_ready", event("task.content_ready"))
    await consumer._handle(redis, "task.failed", json.dumps({
        "task_id": "task", "attempt": 1,
        "payload": {"stage": "content", "reason": "late failure"},
    }).encode())
    assert (await TaskRepository.get(redis, "task"))["status"] == "building"


async def test_concurrent_updates_cannot_roll_back_done(redis, monkeypatch):
    await seed(redis)
    monkeypatch.setattr(module, "emit_to_session", AsyncMock())
    consumer = GatewayKafkaConsumer()
    await asyncio.gather(
        consumer._handle(redis, "task.built", event()),
        consumer._handle(redis, "task.content_ready", event("task.content_ready")),
    )
    assert (await TaskRepository.get(redis, "task"))["status"] == "done"


async def test_replay_after_ws_failure_redelivers_persisted_status(redis, monkeypatch):
    await seed(redis)
    emit = AsyncMock(side_effect=[OSError("temporary disconnect"), None])
    monkeypatch.setattr(module, "emit_to_session", emit)
    consumer = GatewayKafkaConsumer()
    with pytest.raises(OSError):
        await consumer._handle(redis, "task.built", event())
    saved = await TaskRepository.get(redis, "task")
    await consumer._handle(redis, "task.built", event())
    assert await TaskRepository.get(redis, "task") == saved
    assert emit.await_count == 2


@pytest.mark.parametrize("raw", [
    b"[]", b"null", b'{"task_id":true,"payload":{}}',
    b'{"task_id":"task","attempt":true,"payload":{"result_file_id":"bad"}}',
    b'{"task_id":"task","payload":{"result_file_id":[]}}',
    b'{"task_id":"task","payload":{"stage":[],"reason":"bad"}}',
])
async def test_malformed_event_does_not_poison_consumer(redis, monkeypatch, raw):
    await seed(redis)
    emit = AsyncMock()
    monkeypatch.setattr(module, "emit_to_session", emit)
    consumer = GatewayKafkaConsumer()
    await consumer._handle(redis, "task.built", raw)
    await consumer._handle(redis, "task.failed", raw)
    assert (await TaskRepository.get(redis, "task"))["status"] == "queued"
    emit.assert_not_awaited()


@pytest.mark.parametrize("failed_step", ["handle", "commit"])
async def test_transient_failure_retries_same_offset_before_commit(redis, monkeypatch, failed_step):
    message = SimpleNamespace(topic="task.built", partition=3, offset=42, value=event())

    class Broker:
        commit = AsyncMock(side_effect=[OSError("broker"), None] if failed_step == "commit" else None)

        def __aiter__(self):
            async def messages():
                yield message
            return messages()

    consumer = GatewayKafkaConsumer()
    consumer._consumer = Broker()
    consumer._running = True
    consumer._handle = AsyncMock(
        side_effect=[OSError("redis"), None] if failed_step == "handle" else None,
    )
    monkeypatch.setattr(module, "get_redis", AsyncMock(return_value=redis))
    monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())
    await consumer.run()
    assert consumer._handle.await_count == 2
    for call in consumer._consumer.commit.await_args_list:
        assert call.args == ({TopicPartition("task.built", 3): 43},)
    assert consumer._consumer.commit.await_count == (2 if failed_step == "commit" else 1)


async def test_stopping_failed_consumer_does_not_acknowledge_event(redis, monkeypatch):
    class Broker:
        commit = AsyncMock()

        def __aiter__(self):
            async def messages():
                yield SimpleNamespace(topic="task.built", partition=0, offset=0, value=event())
            return messages()

    consumer = GatewayKafkaConsumer()
    consumer._consumer = Broker()
    consumer._running = True
    consumer._handle = AsyncMock(side_effect=OSError("redis unavailable"))

    async def stop(_delay):
        consumer._running = False

    monkeypatch.setattr(module, "get_redis", AsyncMock(return_value=redis))
    monkeypatch.setattr(module.asyncio, "sleep", stop)
    await consumer.run()
    consumer._consumer.commit.assert_not_awaited()
