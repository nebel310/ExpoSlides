import asyncio
import json
import logging
from typing import Any

from aiokafka import AIOKafkaConsumer
from aiokafka.structs import TopicPartition
from app.config import settings
from app.database import get_redis
from app.repositories.files import FileRepository
from app.repositories.tasks import TaskRepository
from app.services.ws_hub import emit_to_session

logger = logging.getLogger(__name__)


class GatewayKafkaConsumer:
    """Консьюмер Kafka: обновляет задачи и шлёт WS-события"""

    def __init__(self) -> None:
        """Инициализирует консьюмер без подключения"""
        self._consumer: AIOKafkaConsumer | None = None
        self._running = False

    async def start(self) -> None:
        """Запускает консьюмер"""
        self._consumer = AIOKafkaConsumer(
            settings.kafka_topic_task_parsed,
            settings.kafka_topic_task_content_ready,
            settings.kafka_topic_task_built,
            settings.kafka_topic_task_failed,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.gateway_kafka_group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await self._consumer.start()
        self._running = True
        logger.info("GatewayKafkaConsumer запущен")

    async def stop(self) -> None:
        """Останавливает консьюмер"""
        self._running = False
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None

    async def run(self) -> None:
        """Повторять текущее сообщение; offset менять только после полного успеха."""
        consumer = self._consumer
        if consumer is None:
            raise RuntimeError("GatewayKafkaConsumer не запущен")
        redis = await get_redis()
        async for message in consumer:
            delay = 0.25
            while self._running:
                try:
                    await self._handle(redis, message.topic, message.value)
                    await consumer.commit({
                        TopicPartition(message.topic, message.partition): message.offset + 1,
                    })
                    break
                except Exception as error:
                    logger.warning(
                        "Повтор обработки %s после %s", message.topic, type(error).__name__,
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 5)
            if not self._running:
                break

    async def _handle(self, redis, topic: str, raw: bytes) -> None:
        """Невалидное событие пропускается; ошибки Redis/WS остаются повторяемыми."""
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("Невалидный JSON в %s", topic)
            return
        if not isinstance(payload, dict):
            return
        task_id, attempt = payload.get("task_id"), payload.get("attempt", 1)
        inner = payload.get("payload")
        if (
            not isinstance(task_id, str) or not task_id or len(task_id) > 256
            or type(attempt) is not int or attempt < 1 or not isinstance(inner, dict)
        ):
            return
        stages = {
            settings.kafka_topic_task_parsed: ("generating_content", "structure_file_id"),
            settings.kafka_topic_task_content_ready: ("building", "content_file_id"),
            settings.kafka_topic_task_built: ("done", "result_file_id"),
        }
        fields: dict[str, Any]
        file_id = None
        failure_stage = None
        if topic in stages:
            status, field = stages[topic]
            file_id = inner.get(field)
            if not isinstance(file_id, str) or not file_id or len(file_id) > 256:
                return
            fields = {field: file_id, "error": None}
            if topic == settings.kafka_topic_task_built:
                extra_files = inner.get("extra_files") or {}
                if not isinstance(extra_files, dict) or any(
                    key not in {"pdf", "html"} or not isinstance(value, str)
                    or not value or len(value) > 256
                    for key, value in extra_files.items()
                ):
                    return
                fields["extra_files"] = extra_files
        elif topic == settings.kafka_topic_task_failed:
            status = "failed"
            reason = payload.get("error") or inner.get("reason")
            failure_stage = inner.get("stage")
            if (
                not isinstance(reason, str) or not isinstance(failure_stage, str)
                or failure_stage not in {"parser", "content", "builder"}
            ):
                return
            fields = {"error": reason[:2000]}
        else:
            return
        task = await TaskRepository.apply_event(
            redis, task_id, attempt=attempt, status=status, fields=fields,
            failure_stage=failure_stage,
        )
        if task is None:
            return
        sid = task.get("sid")
        if not sid:
            logger.warning("У задачи %s нет sid", task_id)
            return
        if file_id is not None:
            await FileRepository.grant(redis, sid, file_id)
        if topic == settings.kafka_topic_task_built:
            for extra_file_id in (task.get("extra_files") or {}).values():
                await FileRepository.grant(redis, sid, extra_file_id)
        await emit_to_session(sid, topic, {
            "task_id": task_id,
            "attempt": task.get("attempt", 1),
            "status": task["status"],
            "payload": {
                "structure_file_id": task.get("structure_file_id"),
                "content_file_id": task.get("content_file_id"),
                "result_file_id": task.get("result_file_id"),
                "extra_files": task.get("extra_files") or {},
                "error": task.get("error"),
            },
        })
        logger.info("Событие %s -> task_id=%s status=%s", topic, task_id, task["status"])


kafka_consumer = GatewayKafkaConsumer()
