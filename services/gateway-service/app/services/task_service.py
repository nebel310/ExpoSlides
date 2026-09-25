import logging
import time
import uuid
from typing import Any

import redis.asyncio as aioredis

from app.config import settings
from app.errors import TaskNotFoundError
from app.repositories.sessions import SessionRepository
from app.repositories.tasks import TaskRepository
from app.services.kafka_producer import kafka_producer

logger = logging.getLogger(__name__)


class TaskService:
    """Бизнес-логика задач gateway"""

    @classmethod
    @classmethod
    async def create_task(
        cls,
        redis: aioredis.Redis,
        sid: str,
        template_file_id: str,
        script_file_id: str,
        formats: list[str] | None = None,
    ) -> dict[str, Any]:
        """Создаёт задачу, сохраняет в Redis и публикует task.created"""
        task_id = str(uuid.uuid4())
        now = time.time()
        task: dict[str, Any] = {
            "task_id": task_id,
            "sid": sid,
            "status": "queued",
            "template_file_id": template_file_id,
            "script_file_id": script_file_id,
            "structure_file_id": None,
            "content_file_id": None,
            "result_file_id": None,
            "error": None,
            "formats": formats or ["pptx"],
            "extra_files": {},
            "created_at": now,
            "updated_at": now,
        }
        await TaskRepository.save(redis, task)
        await SessionRepository.add_task(redis, sid, task_id)
        await kafka_producer.publish(
            settings.kafka_topic_task_created,
            {
                "task_id": task_id,
                "attempt": 1,
                "payload": {
                    "template_file_id": template_file_id,
                    "script_file_id": script_file_id,
                    "session_id": sid,
                    "formats": task["formats"],
                },
                "error": None,
            },
        )
        logger.info("Задача создана: task_id=%s sid=%s", task_id, sid)
        return task

    @classmethod
    async def get_task(cls, redis: aioredis.Redis, task_id: str) -> dict[str, Any]:
        """Возвращает задачу или падает"""
        task = await TaskRepository.get(redis, task_id)
        if task is None:
            raise TaskNotFoundError(f"Задача не найдена: {task_id}")
        return task

    @classmethod
    async def list_tasks(cls, redis: aioredis.Redis, sid: str) -> list[dict[str, Any]]:
        """Возвращает задачи сессии, отсортированные по created_at"""
        task_ids = await SessionRepository.get_task_ids(redis, sid)
        tasks: list[dict[str, Any]] = []
        for task_id in task_ids:
            task = await TaskRepository.get(redis, task_id)
            if task is not None:
                tasks.append(task)
        tasks.sort(key=lambda item: item["created_at"], reverse=True)
        return tasks


task_service = TaskService()