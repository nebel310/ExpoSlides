import logging

from app.services.sio_server import sio

logger = logging.getLogger(__name__)


async def join_session_room(socket_id: str, session_id: str) -> None:
    """Добавляет сокет в комнату сессии"""
    await sio.enter_room(socket_id, session_id)
    logger.info("Socket %s присоединён к комнате %s", socket_id, session_id)


async def emit_to_session(session_id: str, event: str, payload: dict) -> None:
    """Отправляет событие всем сокетам сессии"""
    await sio.emit(event, payload, room=session_id)
