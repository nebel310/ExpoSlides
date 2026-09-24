from unittest.mock import AsyncMock

from app.services import ws_hub


async def test_emit_to_session_calls_sio(monkeypatch):
    """Проверяет emit в комнату сессии"""
    emit = AsyncMock()
    monkeypatch.setattr(ws_hub.sio, "emit", emit)
    await ws_hub.emit_to_session("sid1", "task.built", {"task_id": "t1"})
    emit.assert_awaited_once_with("task.built", {"task_id": "t1"}, room="sid1")


def test_join_session_room_calls_enter(monkeypatch):
    """Проверяет вход в комнату"""
    enter = lambda sid, room: None
    called = {}

    def fake_enter(sid, room):
        called["sid"] = sid
        called["room"] = room

    monkeypatch.setattr(ws_hub.sio, "enter_room", fake_enter)
    ws_hub.join_session_room("socket1", "sid1")
    assert called == {"sid": "socket1", "room": "sid1"}