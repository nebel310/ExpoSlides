import redis.asyncio as aioredis

from app.config import settings


class SessionRepository:
    """Репозиторий сессий в Redis"""
    PREFIX = "session:"
    TTL = settings.redis_session_ttl

    @classmethod
    def _tasks_key(cls, sid: str) -> str:
        """Возвращает ключ множества задач сессии"""
        return f"{cls.PREFIX}{sid}:tasks"

    @classmethod
    async def create(cls, redis: aioredis.Redis, sid: str) -> None:
        """Создаёт новую сессию"""
        key = cls._tasks_key(sid)
        await redis.sadd(key, "__init__")
        await redis.srem(key, "__init__")
        await redis.expire(key, cls.TTL)

    @classmethod
    async def exists(cls, redis: aioredis.Redis, sid: str) -> bool:
        """Проверяет существование сессии"""
        return await redis.exists(cls._tasks_key(sid)) > 0

    @classmethod
    async def touch(cls, redis: aioredis.Redis, sid: str) -> None:
        """Обновляет TTL сессии"""
        await redis.expire(cls._tasks_key(sid), cls.TTL)

    @classmethod
    async def add_task(cls, redis: aioredis.Redis, sid: str, task_id: str) -> None:
        """Добавляет задачу в сессию"""
        key = cls._tasks_key(sid)
        await redis.sadd(key, task_id)
        await redis.expire(key, cls.TTL)

    @classmethod
    async def get_task_ids(cls, redis: aioredis.Redis, sid: str) -> list[str]:
        """Возвращает список task_id сессии"""
        return list(await redis.smembers(cls._tasks_key(sid)))