import json
import logging
from typing import Awaitable, Callable

from aiokafka import AIOKafkaConsumer, ConsumerRecord
from app.config import settings
from app.models.messages import (
    MessageEnvelope,
    TaskContentRetryPayload,
    TaskParsedPayload,
)
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

Handler = Callable[[MessageEnvelope, BaseModel, str], Awaitable[None]]

TOPIC_PAYLOAD_MODELS: dict[str, type[BaseModel]] = {}


class KafkaConsumer:
    """Асинхронный консьюмер Kafka с диспетчеризацией по топикам"""

    def __init__(
        self,
        handler: Handler,
        topics: list[str] | None = None,
        bootstrap_servers: str | None = None,
        group_id: str | None = None,
    ) -> None:
        """Создать консьюмер с указанным handler и списком топиков"""
        self._handler = handler
        self._bootstrap_servers = bootstrap_servers or settings.kafka_bootstrap_servers
        self._group_id = group_id or settings.kafka_group_id
        self._topics = topics or [
            settings.kafka_topic_task_parsed,
            settings.kafka_topic_task_content_retry,
        ]
        self._topic_models: dict[str, type[BaseModel]] = {
            settings.kafka_topic_task_parsed: TaskParsedPayload,
            settings.kafka_topic_task_content_retry: TaskContentRetryPayload,
        }
        self._consumer: AIOKafkaConsumer | None = None
        self._running = False

    async def start(self) -> None:
        """Запустить консьюмер и подписаться на топики"""
        logger.info(
            "Запуск Kafka consumer: group=%s, topics=%s",
            self._group_id,
            self._topics,
        )
        self._consumer = AIOKafkaConsumer(
            *self._topics,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await self._consumer.start()
        self._running = True

    async def stop(self) -> None:
        """Остановить консьюмер"""
        self._running = False
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None

    async def run(self) -> None:
        """Читать сообщения и обрабатывать их до остановки"""
        consumer = self._require_consumer()
        async for message in consumer:
            if not self._running:
                break
            await self.process_message(message)
            await consumer.commit()

    async def process_message(self, message: ConsumerRecord) -> None:
        """Обработать одно сообщение: распарсить, провалидировать, вызвать handler"""
        envelope, payload = self._parse_message(message)
        if envelope is None or payload is None:
            return
        try:
            await self._handler(envelope, payload, message.topic)
        except Exception as error:
            logger.error(
                "Ошибка обработки сообщения из %s (task_id=%s): %s",
                message.topic,
                envelope.task_id,
                error,
            )
            logger.debug("Детали ошибки обработки", exc_info=True)

    def _parse_message(
        self, message: ConsumerRecord
    ) -> tuple[MessageEnvelope | None, BaseModel | None]:
        """Распарсить и провалидировать конверт и payload по топику"""
        model = self._topic_models.get(message.topic)
        if model is None:
            logger.warning("Неизвестный топик: %s", message.topic)
            return None, None

        try:
            raw = json.loads(message.value.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            logger.warning("Невалидный JSON в %s: %s", message.topic, error)
            return None, None

        try:
            envelope = MessageEnvelope.model_validate(raw)
        except ValidationError as error:
            logger.warning("Невалидный конверт в %s: %s", message.topic, error)
            return None, None

        try:
            payload = model.model_validate(envelope.payload)
        except ValidationError as error:
            logger.warning(
                "Невалидный payload в %s (task_id=%s): %s",
                message.topic,
                envelope.task_id,
                error,
            )
            return None, None

        return envelope, payload

    def _require_consumer(self) -> AIOKafkaConsumer:
        """Вернуть консьюмер или упасть, если он не запущен"""
        if self._consumer is None:
            raise RuntimeError("KafkaConsumer не запущен: вызовите start()")
        return self._consumer