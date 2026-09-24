import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.database import get_redis
from app.repositories.sessions import SessionRepository
from app.schemas.session import SessionBootstrapResponse
from app.utils.cookies import get_sid_from_request, new_sid, set_sid_cookie


router = APIRouter(prefix="/api/session", tags=["session"])


@router.post("/bootstrap", response_model=SessionBootstrapResponse)
async def bootstrap_session(
    request: Request,
    response: Response,
    redis: aioredis.Redis = Depends(get_redis),
) -> SessionBootstrapResponse:
    """Создаёт или обновляет анонимную сессию"""
    sid = get_sid_from_request(request)
    if sid and await SessionRepository.exists(redis, sid):
        await SessionRepository.touch(redis, sid)
    else:
        sid = new_sid()
        await SessionRepository.create(redis, sid)
        set_sid_cookie(response, sid)
    return SessionBootstrapResponse(sid=sid)


@router.get("/me", response_model=SessionBootstrapResponse)
async def get_session(
    request: Request,
    redis: aioredis.Redis = Depends(get_redis),
) -> SessionBootstrapResponse:
    """Возвращает текущий sid"""
    sid = get_sid_from_request(request)
    if not sid or not await SessionRepository.exists(redis, sid):
        raise HTTPException(status_code=401, detail="Сессия не найдена")
    await SessionRepository.touch(redis, sid)
    return SessionBootstrapResponse(sid=sid)