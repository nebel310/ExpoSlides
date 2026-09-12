from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from app.grpc.file_service_client import FileServiceClient
from app.kafka.schemas import MessageEnvelope

TOPIC_CREATED = "task.created"
TOPIC_PARSED = "task.parsed"
TOPIC_FAILED = "task.failed"
E2E_TIMEOUT = 30.0
PPTX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)

pytestmark = pytest.mark.e2e


async def _wait_for_message(
    consumer: AIOKafkaConsumer,
    task_id: str,
    timeout: float = E2E_TIMEOUT,
) -> tuple[str, MessageEnvelope]:
    """Ждёт сообщение с нужным task_id из task.parsed или task.failed"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError(
                f"Не дождались сообщения с task_id={task_id} за {timeout}с"
            )
        batch = await consumer.getmany(
            timeout_ms=int(remaining * 1000), max_records=100
        )
        for topic_partition, messages in batch.items():
            for message in messages:
                data = json.loads(message.value.decode("utf-8"))
                if data.get("task_id") == task_id:
                    envelope = MessageEnvelope.model_validate(data)
                    return topic_partition.topic, envelope


@pytest.mark.asyncio
async def test_parser_service_parses_pptx_end_to_end(
    e2e_environment,
    file_client,
    kafka_producer,
    results_consumer,
    simple_pptx_bytes,
):
    """task.created -> парсинг -> task.parsed с валидным structure.json"""
    task_id = f"e2e-{uuid4().hex}"
    template_file_id = await file_client.upload_file(
        filename="template.pptx",
        content=simple_pptx_bytes,
        content_type=PPTX_CONTENT_TYPE,
        task_id=task_id,
    )

    structure_file_id: str | None = None
    try:
        envelope = MessageEnvelope(
            task_id=task_id,
            attempt=1,
            payload={
                "template_file_id": template_file_id,
                "script_file_id": "dummy-script",
            },
        )
        await kafka_producer.send_and_wait(
            TOPIC_CREATED, envelope.model_dump_json().encode("utf-8")
        )

        topic, response = await _wait_for_message(results_consumer, task_id)
        assert topic == TOPIC_PARSED, (
            f"Ожидался {TOPIC_PARSED}, пришло {topic}: {response}"
        )

        structure_file_id = response.payload["structure_file_id"]
        assert response.payload["template_file_id"] == template_file_id
        assert response.payload["script_file_id"] == "dummy-script"
        assert response.attempt == 1

        raw = await file_client.download_file(structure_file_id, version=0)
        structure = json.loads(raw.decode("utf-8"))
        assert structure["file_type"] == "pptx"
        assert len(structure["slides"]) == 1
        titles = [
            element["text"]["full_text"]
            for element in structure["slides"][0]["elements"]
            if element.get("text")
        ]
        assert any("E2E Test" in text for text in titles)
    finally:
        for file_id in (template_file_id, structure_file_id):
            if not file_id:
                continue
            try:
                await file_client.delete_file(file_id)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_parser_service_publishes_task_failed_for_missing_template(
    e2e_environment,
    kafka_producer,
    results_consumer,
):
    """Несуществующий template_file_id приводит к task.failed со stage=parser"""
    task_id = f"e2e-missing-{uuid4().hex}"
    envelope = MessageEnvelope(
        task_id=task_id,
        attempt=1,
        payload={
            "template_file_id": "00000000-0000-0000-0000-000000000000",
            "script_file_id": "dummy-script",
        },
    )
    await kafka_producer.send_and_wait(
        TOPIC_CREATED, envelope.model_dump_json().encode("utf-8")
    )

    topic, response = await _wait_for_message(results_consumer, task_id)
    assert topic == TOPIC_FAILED, (
        f"Ожидался {TOPIC_FAILED}, пришло {topic}: {response}"
    )
    assert response.payload["stage"] == "parser"
    assert isinstance(response.payload["reason"], str)
    assert response.payload["reason"]
    assert response.error is not None