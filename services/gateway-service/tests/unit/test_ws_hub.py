from unittest.mock import AsyncMock

from app.services import ws_hub


async def test_emit_to_session_calls_sio(monkeypatch):
    """Проверяет emit в комнату сессии"""
    emit = AsyncMock()
    monkeypatch.setattr(ws_hub.sio, "emit", emit)
    await ws_hub.emit_to_session("sid1", "task.built", {"task_id": "t1"})
    emit.assert_awaited_once_with("task.built", {"task_id": "t1"}, room="sid1")


async def test_join_session_room_calls_enter(monkeypatch):
    """Проверяет вход в комнату"""
    enter = AsyncMock()
    monkeypatch.setattr(ws_hub.sio, "enter_room", enter)
    await ws_hub.join_session_room("socket1", "sid1")
    enter.assert_awaited_once_with("socket1", "sid1")


async def test_join_creates_room_in_real_socketio_manager(monkeypatch):
    """Настоящий manager подтверждает вступление без сетевого соединения."""
    import socketio

    server = socketio.AsyncServer(async_mode="asgi")
    socket_id = await server.manager.connect("engineio-id", "/")
    monkeypatch.setattr(ws_hub, "sio", server)
    await ws_hub.join_session_room(socket_id, "private-session")
    assert "private-session" in server.rooms(socket_id)
