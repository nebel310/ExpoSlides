import json
import time
from typing import Any, Optional

import redis.asyncio as aioredis

from app.config import settings


class TaskRepository:
    """Репозиторий задач в Redis"""
    PREFIX = "task:"
    TTL = settings.redis_session_ttl

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