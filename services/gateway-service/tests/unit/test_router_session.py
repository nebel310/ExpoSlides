async def test_bootstrap_creates_new_session(client):
    """Проверяет создание новой сессии"""
    response = await client.post("/api/session/bootstrap")
    assert response.status_code == 200
    sid = response.json()["sid"]
    assert len(sid) == 36
    assert response.cookies.get("exposlides_sid") == sid


async def test_bootstrap_reuses_cookie(client):
    """Проверяет повторное использование cookie"""
    first = await client.post("/api/session/bootstrap")
    sid = first.json()["sid"]
    second = await client.post("/api/session/bootstrap")
    assert second.json()["sid"] == sid
    assert second.cookies.get("exposlides_sid") in (None, sid)


async def test_me_without_cookie(client):
    """Проверяет запрос me без cookie"""
    response = await client.get("/api/session/me")
    assert response.status_code == 401


async def test_me_with_cookie(client):
    """Проверяет запрос me с валидной cookie"""
    first = await client.post("/api/session/bootstrap")
    sid = first.json()["sid"]
    response = await client.get("/api/session/me", cookies={"exposlides_sid": sid})
    assert response.status_code == 200
    assert response.json()["sid"] == sid


async def test_me_with_unknown_sid(client):
    """Проверяет me с неизвестной cookie"""
    response = await client.get(
        "/api/session/me",
        cookies={"exposlides_sid": "deadbeef"},
    )
    assert response.status_code == 401