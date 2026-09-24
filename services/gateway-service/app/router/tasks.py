import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import get_redis
from app.errors import TaskNotFoundError
from app.repositories.sessions import SessionRepository
from app.schemas.task import (
    CreateTaskRequest,
    CreateTaskResponse,
    TaskInfo,
    TaskListResponse,
)
from app.services.task_service import task_service
from app.utils.cookies import get_sid_from_request


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


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
    task = await task_service.create_task(
        redis=redis,
        sid=sid,
        template_file_id=body.template_file_id,
        script_file_id=body.script_file_id,
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