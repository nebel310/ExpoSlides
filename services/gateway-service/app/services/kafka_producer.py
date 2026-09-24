import json
import logging
from typing import Any

from aiokafka import AIOKafkaProducer

from app.config import settings

logger = logging.getLogger(__name__)


class GatewayKafkaProducer:
    """Продюсер Kafka для gateway-service"""

    def __init__(self) -> None:
        """Инициализирует продюсер без подключения"""
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        """Запускает продюсер"""
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda value: json.dumps(value, ensure_ascii=False).encode("utf-8"),
        )
        await self._producer.start()
        logger.info("GatewayKafkaProducer запущен")

    async def stop(self) -> None:
        """Останавливает продюсер"""
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Публикует сообщение в топик"""
        if self._producer is None:
            raise RuntimeError("GatewayKafkaProducer не запущен")
        await self._producer.send_and_wait(topic, payload)


kafka_producer = GatewayKafkaProducer()