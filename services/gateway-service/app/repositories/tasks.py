import json
import time
from typing import Any, Optional

import redis.asyncio as aioredis
from app.config import settings
from redis.exceptions import WatchError


class TaskRepository:
    """Репозиторий задач в Redis"""
    PREFIX = "task:"
    TTL = settings.redis_session_ttl
    STAGE_ORDER = {"queued": 0, "generating_content": 1, "building": 2, "done": 3}

    @classmethod
    def _key(cls, task_id: str) -> str:
        """Возвращает ключ задачи"""
        return f"{cls.PREFIX}{task_id}"

    @classmethod
    async def save(cls, redis: aioredis.Redis, task: dict[str, Any]) -> None:
        """Сохраняет задачу"""
        await redis.set(cls._key(task["task_id"]), json.dumps(task), ex=cls.TTL)

    @classmethod
    async def get(cls, redis: aioredis.Redis, task_id: str) -> Optional[dict[str, Any]]:
        """Возвращает задачу по id"""
        raw = await redis.get(cls._key(task_id))
        return json.loads(raw) if raw else None

    @classmethod
    async def update(cls, redis: aioredis.Redis, task_id: str, **fields: Any) -> Optional[dict[str, Any]]:
        """Обновляет поля задачи"""
        task = await cls.get(redis, task_id)
        if task is None:
            return None
        task.update(fields)
        task["updated_at"] = time.time()
        await cls.save(redis, task)
        return task

    @classmethod
    async def apply_event(
        cls, redis: aioredis.Redis, task_id: str, *, attempt: int,
        status: str, fields: dict[str, Any], failure_stage: str | None = None,
    ) -> dict[str, Any] | None:
        """Атомарно применить событие; позднее событие не откатывает новую версию.

        Точный повтор возвращает ту же задачу: если предыдущая отправка WS упала
        после записи в Redis, повторная доставка должна ещё раз отправить статус.
        """
        key = cls._key(task_id)
        while True:
            async with redis.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(key)
                    raw = await pipe.get(key)
                    if raw is None:
                        return None
                    task = json.loads(raw)
                    previous_attempt = task.get("attempt", 1)
                    previous_status = task["status"]
                    if attempt < previous_attempt:
                        return None
                    if attempt == previous_attempt:
                        same_event = previous_status == status and all(
                            task.get(name) == value for name, value in fields.items()
                        )
                        if same_event:
                            return task
                        if previous_status in {"done", "failed"}:
                            return None
                        previous_order = cls.STAGE_ORDER.get(previous_status, 0)
                        if status == "failed":
                            failure_order = {"parser": 0, "content": 1, "builder": 2}
                            if failure_order.get(failure_stage, 3) < previous_order:
                                return None
                        elif cls.STAGE_ORDER[status] <= previous_order:
                            return None
                    else:
                        task.update(content_file_id=None, result_file_id=None, extra_files={}, error=None)
                    task.update(fields)
                    task.update(status=status, attempt=attempt, updated_at=time.time())
                    pipe.multi()
                    pipe.set(key, json.dumps(task), ex=cls.TTL)
                    await pipe.execute()
                    return task
                except WatchError:
                    # Другая реплика уже продвинула задачу; проверяем её новое состояние.
                    continue
