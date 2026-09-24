import logging

from app.database import get_redis
from app.repositories.sessions import SessionRepository
from app.services.sio_server import sio
from app.services.ws_hub import join_session_room

logger = logging.getLogger(__name__)


@sio.event
async def connect(sid: str, environ: dict, auth: dict | None) -> bool:
    """Обрабатывает подключение клиента"""
    session_id = (auth or {}).get("sid")
    if not session_id:
        logger.warning("WS без sid: %s", sid)
        return False
    redis = await get_redis()
    if not await SessionRepository.exists(redis, session_id):
        logger.warning("WS с неизвестным sid: %s", session_id)
        return False
    await SessionRepository.touch(redis, session_id)
    join_session_room(sid, session_id)
    logger.info("WS подключён: socket=%s sid=%s", sid, session_id)
    return True


@sio.event
async def disconnect(sid: str) -> None:
    """Обрабатывает отключение клиента"""
    logger.info("WS отключён: %s", sid)