import asyncio
import json
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaConsumer

from app.domain.contract import ContentGenerationResult
from app.errors import ContentValidationError
from app.kafka.consumer import KafkaConsumer
from app.kafka.producer import KafkaProducer
from app.services.content_pipeline import ContentPipeline

from helpers import (
    KAFKA_BOOTSTRAP,
    PIPELINE_TIMEOUT,
    STUB_CONTENT,
    VALID_SCRIPT,
    VALID_STRUCTURE,
    create_topics,
    make_parsed_envelope,
    upload_inputs,
)


async def _start_output_consumer(topics: dict) -> AIOKafkaConsumer:
    """Подписаться на выходные топики теста"""
    consumer = AIOKafkaConsumer(
        topics["content_ready"],
        topics["failed"],
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=f"content-test-{uuid4().hex}",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    return consumer


async def _start_pipeline(file_client, domain_fn, topics: dict):
    """Поднять producer, consumer и pipeline в текущем loop"""
    producer = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
    await producer.start()
    pipeline = ContentPipeline(
        file_client=file_client,
        producer=producer,
        domain_fn=domain_fn,
        retry_limit=2,
    )
    consumer = KafkaConsumer(
        handler=pipeline.handle,
        topics=[topics["parsed"], topics["content_retry"]],
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=f"content-pipeline-{uuid4().hex}",
    )
    await consumer.start()
    task = asyncio.create_task(consumer.run())
    return producer, consumer, task


async def _stop_pipeline(producer, consumer, task) -> None:
    """Погасить pipeline и его компоненты"""
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await consumer.stop()
    await producer.stop()


@pytest.mark.asyncio
async def test_pipeline_valid_generation_publishes_content_ready(
    file_client,
    raw_producer,
    custom_topics,
):
    """Полный цикл: task.parsed → домен (stub) → task.content_ready"""
    await create_topics(list(custom_topics.values()))
    output = await _start_output_consumer(custom_topics)

    domain_calls: list = []

    async def domain_fn_stub(request):
        domain_calls.append(request)
        return ContentGenerationResult(content=STUB_CONTENT, passed=True, reason=None)

    producer, consumer, consumer_task = await _start_pipeline(
        file_client, domain_fn_stub, custom_topics
    )

    try:
        task_id = str(uuid4())
        ids = await upload_inputs(file_client, task_id)
        await raw_producer.send_and_wait(
            custom_topics["parsed"], make_parsed_envelope(task_id, ids)
        )

        msg = await asyncio.wait_for(output.getone(), timeout=PIPELINE_TIMEOUT)
        assert msg.topic == custom_topics["content_ready"]

        data = json.loads(msg.value.decode("utf-8"))
        assert data["task_id"] == task_id
        assert data["attempt"] == 1
        assert data["payload"]["structure_file_id"] == ids["structure_file_id"]
        assert data["payload"]["template_file_id"] == ids["template_file_id"]
        assert data["payload"]["script_file_id"] == ids["script_file_id"]

        content_file_id = data["payload"]["content_file_id"]
        content_bytes = await file_client.download_file(content_file_id)
        content = json.loads(content_bytes.decode("utf-8"))
        assert content == STUB_CONTENT

        assert len(domain_calls) == 1
        request = domain_calls[0]
        assert request.script == VALID_SCRIPT
        assert request.structure == VALID_STRUCTURE
        assert request.feedback is None

    finally:
        await _stop_pipeline(producer, consumer, consumer_task)
        await output.stop()


@pytest.mark.asyncio
async def test_pipeline_invalid_generation_publishes_task_failed(
    file_client,
    raw_producer,
    custom_topics,
):
    """Полный цикл: task.parsed → домен (stub) падает → task.failed"""
    await create_topics(list(custom_topics.values()))
    output = await _start_output_consumer(custom_topics)

    async def domain_fn_stub(request):
        raise ContentValidationError("Контент не прошёл валидацию после повторов")

    producer, consumer, consumer_task = await _start_pipeline(
        file_client, domain_fn_stub, custom_topics
    )

    try:
        task_id = str(uuid4())
        ids = await upload_inputs(file_client, task_id)
        await raw_producer.send_and_wait(
            custom_topics["parsed"], make_parsed_envelope(task_id, ids)
        )

        msg = await asyncio.wait_for(output.getone(), timeout=PIPELINE_TIMEOUT)
        assert msg.topic == custom_topics["failed"]

        data = json.loads(msg.value.decode("utf-8"))
        assert data["task_id"] == task_id
        assert data["payload"]["stage"] == "content"
        assert "валидацию" in data["payload"]["reason"].lower()
        assert data["attempt"] == 1

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(output.getone(), timeout=2.0)

    finally:
        await _stop_pipeline(producer, consumer, consumer_task)
        await output.stop()