import fakeredis.aioredis
import pytest_asyncio
from app.database import get_redis
from app.main import fastapi_app
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def redis():
    """Создаёт изолированный fake Redis"""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def client(redis):
    """Создаёт HTTP-клиент с подменённым Redis"""
    async def _override():
        return redis
    fastapi_app.dependency_overrides[get_redis] = _override
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    fastapi_app.dependency_overrides.clear()