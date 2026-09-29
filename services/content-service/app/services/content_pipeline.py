import json
import logging
from typing import Awaitable, Callable

from app.config import settings
from app.domain.contract import ContentGenerationRequest, ContentGenerationResult
from app.domain.generate import generate_content
from app.grpc.file_service_client import FileServiceClient
from app.kafka.producer import KafkaProducer
from app.models.messages import (
    MessageEnvelope,
    TaskContentReadyPayload,
    TaskContentRetryPayload,
    TaskFailedPayload,
    TaskParsedPayload,
)
from app.models.response import GenerationResponse

logger = logging.getLogger(__name__)

DomainFn = Callable[[ContentGenerationRequest], Awaitable[ContentGenerationResult]]


class ContentPipeline:
    """Оркестрация I/O между file-service, доменом и Kafka"""

    def __init__(
        self,
        file_client: FileServiceClient,
        producer: KafkaProducer,
        domain_fn: DomainFn = generate_content,
        retry_limit: int | None = None,
    ) -> None:
        """Создать pipeline с клиентами и лимитом внешних ретраев"""
        self._file_client = file_client
        self._producer = producer
        self._domain_fn = domain_fn
        self._retry_limit = (
            retry_limit if retry_limit is not None else settings.content_validation_retries
        )

    async def handle(
        self,
        envelope: MessageEnvelope,
        payload: TaskParsedPayload | TaskContentRetryPayload,
        topic: str,
    ) -> None:
        """Обработать входящее сообщение из task.parsed или task.content_retry"""
        logger.info(
            "Pipeline принял сообщение из %s (task_id=%s, attempt=%d)",
            topic,
            envelope.task_id,
            envelope.attempt,
        )
        try:
            if isinstance(payload, TaskContentRetryPayload):
                await self._handle_retry(envelope, payload)
            else:
                await self._handle_parsed(envelope, payload)
        except Exception as error:
            logger.error(
                "Технический фейл pipeline (task_id=%s): %s",
                envelope.task_id,
                error,
            )
            logger.debug("Детали ошибки pipeline", exc_info=True)
            await self._publish_failed(envelope, envelope.attempt, str(error))

    async def _handle_parsed(
        self,
        envelope: MessageEnvelope,
        payload: TaskParsedPayload,
    ) -> None:
        """Первый проход: скачать structure и script, сгенерировать контент"""
        await self._run(
            envelope=envelope,
            attempt=envelope.attempt,
            structure_file_id=str(payload.structure_file_id),
            script_file_id=str(payload.script_file_id),
            template_file_id=str(payload.template_file_id),
            feedback_file_id=None,
            formats=payload.formats,
        )

    async def _handle_retry(
        self,
        envelope: MessageEnvelope,
        payload: TaskContentRetryPayload,
    ) -> None:
        """Внешний ретрай: скачать feedback, перегенерировать контент"""
        attempt = payload.attempt or envelope.attempt
        if attempt >= self._retry_limit:
            reason = (
                f"Превышен лимит внешних ретраев: attempt={attempt}, "
                f"limit={self._retry_limit}"
            )
            logger.warning("task_id=%s: %s", envelope.task_id, reason)
            await self._publish_failed(envelope, attempt, reason)
            return

        await self._run(
            envelope=envelope,
            attempt=attempt,
            structure_file_id=str(payload.structure_file_id),
            script_file_id=str(payload.script_file_id),
            template_file_id=str(payload.template_file_id),
            feedback_file_id=str(payload.feedback_file_id),
            formats=payload.formats,
        )

    async def _run(
        self,
        envelope: MessageEnvelope,
        attempt: int,
        structure_file_id: str,
        script_file_id: str,
        template_file_id: str,
        feedback_file_id: str | None,
        formats: list[str],
    ) -> None:
        """Общий путь: скачать → домен → залить content.json → опубликовать"""
        structure_bytes = await self._file_client.download_file(structure_file_id)
        structure = json.loads(structure_bytes.decode("utf-8"))

        script_bytes = await self._file_client.download_file(script_file_id)
        script = script_bytes.decode("utf-8")

        feedback: str | None = None
        if feedback_file_id is not None:
            feedback_bytes = await self._file_client.download_file(feedback_file_id)
            feedback = feedback_bytes.decode("utf-8")
            logger.info(
                "task_id=%s: получен feedback длиной %d",
                envelope.task_id,
                len(feedback),
            )

        request = ContentGenerationRequest(
            structure=structure,
            script=script,
            feedback=feedback,
        )
        result = await self._domain_fn(request)

        response = GenerationResponse(
            content=result.content,
            validation_report=result.validation_report,
            error=result.reason,
        )
        content_bytes = json.dumps(response.model_dump(), ensure_ascii=False).encode("utf-8")
        content_file_id = await self._file_client.upload_file(
            filename="content.json",
            content=content_bytes,
            content_type="application/json",
            task_id=str(envelope.task_id),
        )

        ready_payload = TaskContentReadyPayload(
            structure_file_id=structure_file_id,
            content_file_id=content_file_id,
            template_file_id=template_file_id,
            script_file_id=script_file_id,
            formats=formats,
        )
        ready_envelope = MessageEnvelope(
            task_id=envelope.task_id,
            attempt=attempt,
            payload=ready_payload.model_dump(mode="json"),
            error=None,
        )
        await self._producer.publish(settings.kafka_topic_task_content_ready, ready_envelope)
        logger.info(
            "task_id=%s: опубликован task.content_ready (content_file_id=%s)",
            envelope.task_id,
            content_file_id,
        )

    async def _publish_failed(
        self,
        envelope: MessageEnvelope,
        attempt: int,
        reason: str,
    ) -> None:
        """Опубликовать task.failed с stage=content, ошибки публикации не пробрасываем"""
        failed_payload = TaskFailedPayload(stage="content", reason=reason or "unknown error")
        failed_envelope = MessageEnvelope(
            task_id=envelope.task_id,
            attempt=attempt,
            payload=failed_payload.model_dump(mode="json"),
            error=reason,
        )
        try:
            await self._producer.publish(settings.kafka_topic_task_failed, failed_envelope)
            logger.info("task_id=%s: опубликован task.failed", envelope.task_id)
        except Exception as error:
            logger.error(
                "Не удалось опубликовать task.failed (task_id=%s): %s",
                envelope.task_id,
                error,
            )
