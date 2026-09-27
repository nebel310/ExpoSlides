"""Доступ сессий к загруженным файлам и результатам их задач."""

import redis.asyncio as aioredis
from app.config import settings


class FileRepository:
    @staticmethod
    def key(sid: str) -> str:
        return f"session:{sid}:files"

    @classmethod
    async def grant(cls, redis: aioredis.Redis, sid: str, file_id: str) -> None:
        """Вызывать только после загрузки или принятого события собственной задачи."""
        async with redis.pipeline(transaction=True) as pipe:
            pipe.sadd(cls.key(sid), file_id)
            pipe.expire(cls.key(sid), settings.redis_session_ttl)
            await pipe.execute()

    @classmethod
    async def owns(cls, redis: aioredis.Redis, sid: str, file_id: str) -> bool:
        return bool(await redis.sismember(cls.key(sid), file_id))
