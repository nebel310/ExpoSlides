from urllib.parse import quote

import redis.asyncio as aioredis
from app.config import settings
from app.database import get_redis
from app.errors import FileServiceError
from app.repositories.files import FileRepository
from app.repositories.sessions import SessionRepository
from app.schemas.files import UploadFileResponse
from app.services.file_client import file_client
from app.utils.cookies import get_sid_from_request
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response as FastAPIResponse

router = APIRouter(prefix="/api/files", tags=["files"])


async def _require_sid(request: Request, redis: aioredis.Redis) -> str:
    """Возвращает sid или падает с 401"""
    sid = get_sid_from_request(request)
    if not sid or not await SessionRepository.exists(redis, sid):
        raise HTTPException(status_code=401, detail="Сессия не найдена")
    await SessionRepository.touch(redis, sid)
    return sid


@router.post("/upload", response_model=UploadFileResponse)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    redis: aioredis.Redis = Depends(get_redis),
) -> UploadFileResponse:
    """Загружает файл в file-service"""
    sid = await _require_sid(request, redis)
    content = await file.read(settings.max_upload_size + 1)
    if len(content) > settings.max_upload_size:
        raise HTTPException(status_code=413, detail="Файл слишком большой")
    content_type = file.content_type or "application/octet-stream"
    try:
        result = await file_client.upload_file(
            filename=file.filename or "file",
            content=content,
            content_type=content_type,
        )
    except FileServiceError as error:
        raise HTTPException(status_code=502, detail=str(error))
    response = UploadFileResponse(**result)
    await FileRepository.grant(redis, sid, response.file_id)
    return response


@router.get("/{file_id}")
async def download_file(
    file_id: str,
    request: Request,
    redis: aioredis.Redis = Depends(get_redis),
) -> FastAPIResponse:
    """Скачивает файл из file-service"""
    sid = await _require_sid(request, redis)
    if not await FileRepository.owns(redis, sid, file_id):
        raise HTTPException(status_code=404, detail="Файл не найден")
    try:
        content, filename, content_type, _ = await file_client.download_file(file_id)
    except FileServiceError as error:
        raise HTTPException(status_code=404, detail=str(error))
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }
    return FastAPIResponse(content=content, media_type=content_type, headers=headers)
