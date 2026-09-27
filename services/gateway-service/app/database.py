import redis.asyncio as aioredis
from app.config import settings

redis_client: aioredis.Redis = aioredis.from_url(
    settings.redis_url,
    decode_responses=True,
)


async def get_redis() -> aioredis.Redis:
    """Возвращает глобальный Redis-клиент"""
    return redis_client


async def close_redis() -> None:
    """Закрывает Redis-клиент"""
    await redis_client.aclose()