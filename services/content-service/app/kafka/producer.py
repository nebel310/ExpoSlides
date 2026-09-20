import json
import logging

from aiokafka import AIOKafkaProducer
from pydantic import BaseModel

from app.config import settings
from app.models.messages import MessageEnvelope

logger = logging.getLogger(__name__)


class KafkaProducer:
    """Асинхронный продюсер Kafka с общим конвертом сообщений"""

    def __init__(self, bootstrap_servers: str | None = None) -> None:
        """Создать продюсер с адресом из аргумента или настроек"""
        self._bootstrap_servers = bootstrap_servers or settings.kafka_bootstrap_servers
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        """Запустить продюсер и установить соединение с брокером"""
        logger.info("Запуск Kafka producer: %s", self._bootstrap_servers)
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            value_serializer=lambda value: json.dumps(value, ensure_ascii=False).encode("utf-8"),
        )
        await self._producer.start()

    async def stop(self) -> None:
        """Остановить продюсер"""
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def publish(self, topic: str, envelope: MessageEnvelope) -> None:
        """Опубликовать конверт в указанный топик"""
        producer = self._require_producer()
        value = envelope.model_dump(mode="json")
        await producer.send_and_wait(topic, value)
        logger.debug(
            "Опубликовано в %s: task_id=%s, attempt=%d",
            topic,
            envelope.task_id,
            envelope.attempt,
        )

    def _require_producer(self) -> AIOKafkaProducer:
        """Вернуть продюсер или упасть, если он не запущен"""
        if self._producer is None:
            raise RuntimeError("KafkaProducer не запущен: вызовите start()")
        return self._producer