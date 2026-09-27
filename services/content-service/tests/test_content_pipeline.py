import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.domain.contract import ContentGenerationResult
from app.models.messages import (
    MessageEnvelope,
    TaskContentRetryPayload,
    TaskParsedPayload,
)
from app.services.content_pipeline import ContentPipeline


def _parsed_payload() -> TaskParsedPayload:
    """Собрать валидный payload task.parsed"""
    return TaskParsedPayload(
        structure_file_id=uuid4(),
        template_file_id=uuid4(),
        script_file_id=uuid4(),
    )


def _retry_payload(attempt: int = 2) -> TaskContentRetryPayload:
    """Собрать валидный payload task.content_retry"""
    return TaskContentRetryPayload(
        structure_file_id=uuid4(),
        script_file_id=uuid4(),
        template_file_id=uuid4(),
        feedback_file_id=uuid4(),
        attempt=attempt,
    )


def _envelope(payload) -> MessageEnvelope:
    """Собрать конверт с заданным payload"""
    return MessageEnvelope(
        task_id=uuid4(),
        attempt=1,
        payload=payload.model_dump(mode="json"),
        error=None,
    )


def _make_pipeline(
    file_client=None,
    producer=None,
    domain_fn=None,
    retry_limit=2,
) -> ContentPipeline:
    """Собрать pipeline с моками по умолчанию"""
    file_client = file_client or AsyncMock()
    producer = producer or AsyncMock()
    domain_fn = domain_fn or AsyncMock(
        return_value=ContentGenerationResult(
            content={1: {"placeholders": {"0": "текст"}}},
            passed=True,
            reason=None,
        )
    )
    return ContentPipeline(
        file_client=file_client,
        producer=producer,
        domain_fn=domain_fn,
        retry_limit=retry_limit,
    )


@pytest.mark.asyncio
async def test_handle_parsed_valid_publishes_ready():
    """Проверить полный путь task.parsed → task.content_ready"""
    content_file_id = str(uuid4())
    file_client = AsyncMock()
    file_client.download_file = AsyncMock(
        side_effect=[
            json.dumps({"slides": []}).encode("utf-8"),
            "текст скрипта".encode("utf-8"),
        ]
    )
    file_client.upload_file = AsyncMock(return_value=content_file_id)
    producer = AsyncMock()

    pipeline = _make_pipeline(file_client=file_client, producer=producer)
    payload = _parsed_payload()
    envelope = _envelope(payload)
    await pipeline.handle(envelope, payload, "task.parsed")

    assert file_client.download_file.await_count == 2
    file_client.upload_file.assert_awaited_once()
    uploaded = json.loads(file_client.upload_file.await_args.kwargs["content"])
    assert uploaded == {
        "content": {"1": {"placeholders": {"0": "текст"}, "notes": None}},
        "validation_report": None,
        "error": None,
    }
    producer.publish.assert_awaited_once()
    topic_arg, envelope_arg = producer.publish.await_args.args
    assert topic_arg == "task.content_ready"
    assert envelope_arg.task_id == envelope.task_id
    assert envelope_arg.attempt == 1
    assert envelope_arg.payload["content_file_id"] == content_file_id
    assert envelope_arg.payload["structure_file_id"] == str(payload.structure_file_id)
    assert envelope_arg.payload["template_file_id"] == str(payload.template_file_id)
    assert envelope_arg.payload["script_file_id"] == str(payload.script_file_id)


@pytest.mark.asyncio
async def test_handle_parsed_domain_error_publishes_failed():
    """Проверить публикацию task.failed при ошибке домена"""
    file_client = AsyncMock()
    file_client.download_file = AsyncMock(
        side_effect=[
            json.dumps({"slides": []}).encode("utf-8"),
            b"script",
        ]
    )
    producer = AsyncMock()
    domain_fn = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

    pipeline = _make_pipeline(
        file_client=file_client,
        producer=producer,
        domain_fn=domain_fn,
    )
    payload = _parsed_payload()
    await pipeline.handle(_envelope(payload), payload, "task.parsed")

    file_client.upload_file.assert_not_awaited()
    producer.publish.assert_awaited_once()
    topic_arg, envelope_arg = producer.publish.await_args.args
    assert topic_arg == "task.failed"
    assert envelope_arg.payload["stage"] == "content"
    assert "LLM unavailable" in envelope_arg.payload["reason"]


@pytest.mark.asyncio
async def test_handle_parsed_download_error_publishes_failed():
    """Проверить публикацию task.failed при ошибке скачивания"""
    file_client = AsyncMock()
    file_client.download_file = AsyncMock(side_effect=RuntimeError("file-service down"))
    producer = AsyncMock()
    domain_fn = AsyncMock()

    pipeline = _make_pipeline(
        file_client=file_client,
        producer=producer,
        domain_fn=domain_fn,
    )
    payload = _parsed_payload()
    await pipeline.handle(_envelope(payload), payload, "task.parsed")

    domain_fn.assert_not_awaited()
    producer.publish.assert_awaited_once()
    topic_arg, envelope_arg = producer.publish.await_args.args
    assert topic_arg == "task.failed"
    assert "file-service down" in envelope_arg.payload["reason"]


@pytest.mark.asyncio
async def test_handle_parsed_upload_error_publishes_failed():
    """Проверить публикацию task.failed при ошибке загрузки content.json"""
    file_client = AsyncMock()
    file_client.download_file = AsyncMock(
        side_effect=[
            json.dumps({"slides": []}).encode("utf-8"),
            b"script",
        ]
    )
    file_client.upload_file = AsyncMock(side_effect=RuntimeError("upload broken"))
    producer = AsyncMock()

    pipeline = _make_pipeline(file_client=file_client, producer=producer)
    payload = _parsed_payload()
    await pipeline.handle(_envelope(payload), payload, "task.parsed")

    producer.publish.assert_awaited_once()
    topic_arg, envelope_arg = producer.publish.await_args.args
    assert topic_arg == "task.failed"
    assert "upload broken" in envelope_arg.payload["reason"]


@pytest.mark.asyncio
async def test_handle_parsed_invalid_structure_json_publishes_failed():
    """Проверить публикацию task.failed при битом structure.json"""
    file_client = AsyncMock()
    file_client.download_file = AsyncMock(return_value=b"not a json {")
    producer = AsyncMock()

    pipeline = _make_pipeline(file_client=file_client, producer=producer)
    payload = _parsed_payload()
    await pipeline.handle(_envelope(payload), payload, "task.parsed")

    producer.publish.assert_awaited_once()
    topic_arg, _ = producer.publish.await_args.args
    assert topic_arg == "task.failed"


@pytest.mark.asyncio
async def test_handle_retry_within_limit_uses_feedback():
    """Проверить, что ретрай в пределах лимита скачивает feedback и зовёт домен"""
    content_file_id = str(uuid4())
    file_client = AsyncMock()
    file_client.download_file = AsyncMock(
        side_effect=[
            json.dumps({"slides": []}).encode("utf-8"),
            b"script",
            "улучши слайд 1".encode("utf-8"),
        ]
    )
    file_client.upload_file = AsyncMock(return_value=content_file_id)
    producer = AsyncMock()
    domain_fn = AsyncMock(
        return_value=ContentGenerationResult(content={1: {}}, passed=True, reason=None)
    )

    pipeline = _make_pipeline(
        file_client=file_client,
        producer=producer,
        domain_fn=domain_fn,
        retry_limit=3,
    )
    payload = _retry_payload(attempt=2)
    await pipeline.handle(_envelope(payload), payload, "task.content_retry")

    assert file_client.download_file.await_count == 3
    domain_fn.assert_awaited_once()
    request = domain_fn.await_args.args[0]
    assert request.feedback == "улучши слайд 1"
    producer.publish.assert_awaited_once()
    topic_arg, envelope_arg = producer.publish.await_args.args
    assert topic_arg == "task.content_ready"
    assert envelope_arg.attempt == 2


@pytest.mark.asyncio
async def test_handle_retry_exceeds_limit_publishes_failed():
    """Проверить публикацию task.failed при превышении лимита ретраев"""
    file_client = AsyncMock()
    producer = AsyncMock()
    domain_fn = AsyncMock()

    pipeline = _make_pipeline(
        file_client=file_client,
        producer=producer,
        domain_fn=domain_fn,
        retry_limit=2,
    )
    payload = _retry_payload(attempt=2)
    await pipeline.handle(_envelope(payload), payload, "task.content_retry")

    file_client.download_file.assert_not_awaited()
    domain_fn.assert_not_awaited()
    producer.publish.assert_awaited_once()
    topic_arg, envelope_arg = producer.publish.await_args.args
    assert topic_arg == "task.failed"
    assert envelope_arg.payload["stage"] == "content"
    assert "лимит" in envelope_arg.payload["reason"].lower()
    assert envelope_arg.attempt == 2


@pytest.mark.asyncio
async def test_handle_publish_failed_error_does_not_raise():
    """Проверить, что ошибка публикации task.failed не пробрасывается"""
    file_client = AsyncMock()
    file_client.download_file = AsyncMock(side_effect=RuntimeError("file-service down"))
    producer = AsyncMock()
    producer.publish = AsyncMock(side_effect=RuntimeError("broker down"))

    pipeline = _make_pipeline(file_client=file_client, producer=producer)
    payload = _parsed_payload()
    await pipeline.handle(_envelope(payload), payload, "task.parsed")
