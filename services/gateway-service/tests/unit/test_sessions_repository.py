from app.repositories.sessions import SessionRepository


async def test_create_and_exists(redis):
    """Проверяет создание и проверку сессии"""
    assert not await SessionRepository.exists(redis, "sid1")
    await SessionRepository.create(redis, "sid1")
    assert await SessionRepository.exists(redis, "sid1")


async def test_touch_extends_ttl(redis):
    """Проверяет обновление TTL"""
    await SessionRepository.create(redis, "sid1")
    await SessionRepository.touch(redis, "sid1")
    ttl = await redis.ttl(SessionRepository._key("sid1"))
    assert 0 < ttl <= SessionRepository.TTL


async def test_add_task_and_get(redis):
    """Проверяет добавление задач в сессию"""
    await SessionRepository.create(redis, "sid1")
    await SessionRepository.add_task(redis, "sid1", "t1")
    await SessionRepository.add_task(redis, "sid1", "t2")
    ids = await SessionRepository.get_task_ids(redis, "sid1")
    assert sorted(ids) == ["t1", "t2"]


async def test_add_task_idempotent(redis):
    """Проверяет что повторное добавление не дублирует"""
    await SessionRepository.create(redis, "sid1")
    await SessionRepository.add_task(redis, "sid1", "t1")
    await SessionRepository.add_task(redis, "sid1", "t1")
    ids = await SessionRepository.get_task_ids(redis, "sid1")
    assert ids == ["t1"]


async def test_get_task_ids_empty(redis):
    """Проверяет пустую сессию"""
    await SessionRepository.create(redis, "sid1")
    ids = await SessionRepository.get_task_ids(redis, "sid1")
    assert ids == []


async def test_exists_unknown(redis):
    """Проверяет несуществующую сессию"""
    assert not await SessionRepository.exists(redis, "unknown")