from __future__ import annotations

import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer
from app.kafka.producer import KafkaProducer
from app.kafka.schemas import (
    MessageEnvelope,
    TaskCreatedPayload,
    TaskFailedPayload,
)
from app.services.parser_pipeline import ParserPipeline
from pydantic import ValidationError

logger = logging.getLogger(__name__)

STAGE = "parser"


class TaskCreatedConsumer:
    """Консьюмер task.created: парсит pptx и публикует task.parsed или task.failed"""

    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        topic_created: str,
        topic_parsed: str,
        topic_failed: str,
        pipeline: ParserPipeline,
        producer: KafkaProducer,
    ) -> None:
        """Сохраняет конфигурацию и зависимости"""
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._topic_created = topic_created
        self._topic_parsed = topic_parsed
        self._topic_failed = topic_failed
        self._pipeline = pipeline
        self._producer = producer
        self._consumer: AIOKafkaConsumer | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Создаёт и запускает консьюмер"""
        self._consumer = AIOKafkaConsumer(
            self._topic_created,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await self._consumer.start()
        logger.info("TaskCreatedConsumer запущен: topic=%s", self._topic_created)

    async def stop(self) -> None:
        """Останавливает консьюмер"""
        self._stop_event.set()
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None

    async def run(self) -> None:
        """Читает сообщения до stop(), обрабатывая каждое и коммитя offset"""
        if self._consumer is None:
            raise RuntimeError("TaskCreatedConsumer не запущен, вызовите start()")
        try:
            async for message in self._consumer:
                if self._stop_event.is_set():
                    break
                await self._handle_message(message.value)
                await self._consumer.commit()
        except asyncio.CancelledError:
            logger.info("TaskCreatedConsumer остановлен по отмене")
            raise

    async def _handle_message(self, raw: bytes) -> None:
        """Десериализует, валидирует и обрабатывает одно сообщение"""
        envelope = self._decode_envelope(raw)
        if envelope is None:
            return

        try:
            payload = TaskCreatedPayload.model_validate(envelope.payload)
        except ValidationError as error:
            logger.error("Невалидный payload task.created: %s", error)
            await self._publish_failed(envelope, f"invalid payload: {error}")
            return

        try:
            parsed = await self._pipeline.process(envelope.task_id, payload)
        except Exception as error:
            logger.exception("Техническая ошибка парсинга task_id=%s", envelope.task_id)
            await self._publish_failed(envelope, str(error) or error.__class__.__name__)
            return

        await self._producer.publish(
            self._topic_parsed,
            MessageEnvelope(
                task_id=envelope.task_id,
                attempt=envelope.attempt,
                payload=parsed.model_dump(),
            ),
        )

    def _decode_envelope(self, raw: bytes) -> MessageEnvelope | None:
        """Парсит байты в MessageEnvelope или логирует и возвращает None"""
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            logger.error("Не удалось десериализовать сообщение: %s", error)
            return None
        try:
            return MessageEnvelope.model_validate(data)
        except ValidationError as error:
            logger.error("Невалидный конверт: %s", error)
            return None

    async def _publish_failed(self, envelope: MessageEnvelope, reason: str) -> None:
        """Публикует технический фейл в task.failed"""
        failed = TaskFailedPayload(stage=STAGE, reason=reason)
        await self._producer.publish(
            self._topic_failed,
            MessageEnvelope(
                task_id=envelope.task_id,
                attempt=envelope.attempt,
                payload=failed.model_dump(),
                error=reason,
            ),
        )