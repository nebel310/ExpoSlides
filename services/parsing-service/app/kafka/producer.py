from __future__ import annotations

import logging

from aiokafka import AIOKafkaProducer
from app.kafka.schemas import MessageEnvelope

logger = logging.getLogger(__name__)


class KafkaProducer:
    """Асинхронный Kafka-продюсер с JSON-сериализацией конверта"""

    def __init__(self, bootstrap_servers: str) -> None:
        """Сохраняет адрес брокера и готовит пустой продюсер"""
        self._bootstrap_servers = bootstrap_servers
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        """Запускает продюсер"""
        self._producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap_servers)
        await self._producer.start()
        logger.info("KafkaProducer запущен: %s", self._bootstrap_servers)

    async def stop(self) -> None:
        """Останавливает продюсер"""
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def publish(self, topic: str, envelope: MessageEnvelope) -> None:
        """Публикует конверт в указанный топик"""
        if self._producer is None:
            raise RuntimeError("KafkaProducer не запущен, вызовите start()")
        payload = envelope.model_dump_json().encode("utf-8")
        await self._producer.send_and_wait(topic, payload)
        logger.info("Опубликовано в %s: task_id=%s", topic, envelope.task_id)