import redis.asyncio as aioredis
from app.database import get_redis
from app.errors import TaskNotFoundError
from app.repositories.files import FileRepository
from app.repositories.sessions import SessionRepository
from app.schemas.task import (
    CreateTaskRequest,
    CreateTaskResponse,
    TaskInfo,
    TaskListResponse,
)
from app.services.task_service import task_service
from app.utils.cookies import get_sid_from_request
from fastapi import APIRouter, Depends, HTTPException, Request

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

ALLOWED_FORMATS = {"pptx", "pdf", "html"}


async def _require_sid(request: Request, redis: aioredis.Redis) -> str:
    """Возвращает sid или падает с 401"""
    sid = get_sid_from_request(request)
    if not sid or not await SessionRepository.exists(redis, sid):
        raise HTTPException(status_code=401, detail="Сессия не найдена")
    await SessionRepository.touch(redis, sid)
    return sid


@router.post("", response_model=CreateTaskResponse)
async def create_task(
    body: CreateTaskRequest,
    request: Request,
    redis: aioredis.Redis = Depends(get_redis),
) -> CreateTaskResponse:
    """Создаёт задачу на генерацию презентации"""
    sid = await _require_sid(request, redis)
    for file_id in (body.template_file_id, body.script_file_id):
        if not await FileRepository.owns(redis, sid, file_id):
            raise HTTPException(status_code=404, detail="Файл не найден")
    unknown = set(body.formats) - ALLOWED_FORMATS
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Неизвестные форматы: {sorted(unknown)}",
        )
    task = await task_service.create_task(
        redis=redis,
        sid=sid,
        template_file_id=body.template_file_id,
        script_file_id=body.script_file_id,
        formats=body.formats,
    )
    return CreateTaskResponse(task_id=task["task_id"])


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    request: Request,
    redis: aioredis.Redis = Depends(get_redis),
) -> TaskListResponse:
    """Возвращает список задач текущей сессии"""
    sid = await _require_sid(request, redis)
    tasks = await task_service.list_tasks(redis, sid)
    return TaskListResponse(tasks=[TaskInfo(**task) for task in tasks])


@router.get("/{task_id}", response_model=TaskInfo)
async def get_task(
    task_id: str,
    request: Request,
    redis: aioredis.Redis = Depends(get_redis),
) -> TaskInfo:
    """Возвращает одну задачу"""
    sid = await _require_sid(request, redis)
    try:
        task = await task_service.get_task(redis, task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if task["sid"] != sid:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return TaskInfo(**task)
