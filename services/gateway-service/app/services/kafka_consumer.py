import json
import logging
from typing import Any

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.database import get_redis
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
            group_id=settings.kafka_group_id,
            enable_auto_commit=False,
            auto_offset_reset="latest",
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
        """Основной цикл чтения сообщений"""
        consumer = self._consumer
        if consumer is None:
            raise RuntimeError("GatewayKafkaConsumer не запущен")
        redis = await get_redis()
        async for message in consumer:
            if not self._running:
                break
            try:
                await self._handle(redis, message.topic, message.value)
            except Exception as error:
                logger.error("Ошибка обработки %s: %s", message.topic, error)
                logger.debug("Детали", exc_info=True)
            await consumer.commit()

    async def _handle(self, redis, topic: str, raw: bytes) -> None:
        """Обрабатывает одно сообщение Kafka"""
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("Невалидный JSON в %s", topic)
            return
        task_id = payload.get("task_id")
        if not task_id:
            return
        inner = payload.get("payload") or {}
        updates: dict[str, Any] = {}
        if topic == settings.kafka_topic_task_parsed:
            updates["status"] = "generating_content"
            updates["structure_file_id"] = inner.get("structure_file_id")
        elif topic == settings.kafka_topic_task_content_ready:
            updates["status"] = "building"
            updates["content_file_id"] = inner.get("content_file_id")
        elif topic == settings.kafka_topic_task_built:
            updates["status"] = "done"
            updates["result_file_id"] = inner.get("result_file_id")
        elif topic == settings.kafka_topic_task_failed:
            updates["status"] = "failed"
            updates["error"] = payload.get("error") or inner.get("reason")
        else:
            return
        task = await TaskRepository.update(redis, task_id, **updates)
        if task is None:
            return
        sid = task.get("sid")
        if not sid:
            logger.warning("У задачи %s нет sid", task_id)
            return
        await emit_to_session(sid, topic, {
            "task_id": task_id,
            "status": task["status"],
            "payload": {
                "structure_file_id": task.get("structure_file_id"),
                "content_file_id": task.get("content_file_id"),
                "result_file_id": task.get("result_file_id"),
                "error": task.get("error"),
            },
        })
        logger.info("Событие %s -> task_id=%s status=%s", topic, task_id, task["status"])


kafka_consumer = GatewayKafkaConsumer()