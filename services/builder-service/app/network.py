"""Сетевой builder: task.content_ready → файл PPTX → task.built."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import tempfile
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any
from uuid import UUID

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.structs import TopicPartition
from app.builder import PPTXBuilder
from app.models.content import GeneratedContent
from app.models.presentation import Presentation
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)
PPTX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


class Settings(BaseSettings):
    """Настройки сетевого процесса; файловый CLI их не загружает."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_group_id: str = "builder-service"
    kafka_topic_task_content_ready: str = "task.content_ready"
    kafka_topic_task_built: str = "task.built"
    kafka_topic_task_failed: str = "task.failed"
    file_service_grpc_host: str = "file-service"
    file_service_grpc_port: int = Field(default=50051, ge=1, le=65535)
    file_service_timeout: float = Field(default=60, gt=0)
    log_level: str = "INFO"


class MessageEnvelope(BaseModel):
    """Общий Kafka-конверт; payload проверяется после идентификации задачи."""

    task_id: UUID
    attempt: int = Field(default=1, ge=1)
    payload: dict[str, Any]
    error: str | None = None


class ContentReadyPayload(BaseModel):
    """Файлы, опубликованные content-service."""

    structure_file_id: UUID
    content_file_id: UUID
    template_file_id: UUID
    script_file_id: UUID


class BuilderPipeline:
    """Собирает файл через существующий builder, сохраняя порядок и стили."""

    def __init__(self, file_client: Any) -> None:
        self.file_client = file_client

    async def process(self, envelope: MessageEnvelope) -> dict[str, str]:
        payload = ContentReadyPayload.model_validate(envelope.payload)
        if envelope.error:
            raise ValueError("Входное событие содержит ошибку content-service")
        structure = await self.file_client.download_file(str(payload.structure_file_id))
        content = await self.file_client.download_file(str(payload.content_file_id))
        template = await self.file_client.download_file(str(payload.template_file_id))
        template_data = Presentation.model_validate_json(structure)
        content_data = GeneratedContent.model_validate_json(content)
        with tempfile.TemporaryDirectory(prefix="exposlides-builder-") as directory:
            source = Path(directory) / "template.pptx"
            target = Path(directory) / "result.pptx"
            await asyncio.to_thread(source.write_bytes, template)
            # PPTXBuilder сохраняет атомарно и повторно открывает созданный файл.
            await PPTXBuilder.build(source, template_data, content_data, target)
            result_bytes = await asyncio.to_thread(target.read_bytes)
        result_id = await self.file_client.upload_file(
            filename="result.pptx",
            content=result_bytes,
            content_type=PPTX_CONTENT_TYPE,
            task_id=str(envelope.task_id),
        )
        return {
            **payload.model_dump(mode="json"),
            "result_file_id": str(UUID(result_id)),
        }


async def process_message(
    raw: bytes, pipeline: BuilderPipeline, producer: Any, settings: Settings
) -> None:
    """Подтверждать вход можно только после подтверждённой публикации результата."""
    try:
        envelope = MessageEnvelope.model_validate_json(raw)
    except ValidationError:
        # Без корректного task_id нельзя адресовать task.failed.
        logger.warning("Пропущен невалидный Kafka-конверт builder")
        return
    try:
        payload = await pipeline.process(envelope)
    except Exception as exc:
        logger.error("Ошибка сборки задачи %s: %s", envelope.task_id, type(exc).__name__)
        logger.debug("Детали ошибки builder", exc_info=True)
        reason = "Не удалось собрать или сохранить PPTX"
        topic = settings.kafka_topic_task_failed
        payload = {"stage": "builder", "reason": reason}
        error = reason
    else:
        topic = settings.kafka_topic_task_built
        error = None
    result = {
        "task_id": str(envelope.task_id),
        "attempt": envelope.attempt,
        "payload": payload,
        "error": error,
    }
    # Ошибку брокера не превращаем в успех: worker завершится без commit,
    # и после перезапуска Kafka повторно доставит исходное сообщение.
    await producer.send_and_wait(
        topic,
        json.dumps(result, ensure_ascii=False).encode("utf-8"),
        key=str(envelope.task_id).encode("utf-8"),
    )


async def consume(consumer: Any, pipeline: BuilderPipeline, producer: Any, settings: Settings) -> None:
    async for message in consumer:
        await process_message(message.value, pipeline, producer, settings)
        await consumer.commit({
            TopicPartition(message.topic, message.partition): message.offset + 1,
        })


async def serve(settings: Settings | None = None, stop_event: asyncio.Event | None = None) -> None:
    """Запустить worker и закрыть все соединения при сигнале или ошибке."""
    from app.file_client import FileServiceClient

    settings = settings or Settings()
    stop_event = stop_event or asyncio.Event()
    loop = asyncio.get_running_loop()
    installed_signals = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
            installed_signals.append(sig)
        except (NotImplementedError, RuntimeError):
            pass
    file_client = FileServiceClient(settings)
    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    consumer = AIOKafkaConsumer(
        settings.kafka_topic_task_content_ready,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    try:
        async with AsyncExitStack() as stack:
            for client in (file_client, producer, consumer):
                stack.push_async_callback(client.stop)
                await client.start()
            worker = asyncio.create_task(consume(
                consumer, BuilderPipeline(file_client), producer, settings
            ))
            stopper = asyncio.create_task(stop_event.wait())
            try:
                done, _ = await asyncio.wait(
                    (worker, stopper), return_when=asyncio.FIRST_COMPLETED
                )
                if worker in done:
                    await worker
            finally:
                worker.cancel()
                stopper.cancel()
                await asyncio.gather(worker, stopper, return_exceptions=True)
    finally:
        for sig in installed_signals:
            loop.remove_signal_handler(sig)


def main() -> None:
    settings = Settings()
    logging.basicConfig(level=settings.log_level.upper())
    asyncio.run(serve(settings))


if __name__ == "__main__":
    main()
