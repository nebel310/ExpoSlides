from __future__ import annotations

import json

import pytest
from app.kafka.consumer import STAGE, TaskCreatedConsumer
from app.kafka.schemas import (
    MessageEnvelope,
    TaskParsedPayload,
)


class FakePipeline:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple] = []

    async def process(self, task_id, payload):
        self.calls.append((task_id, payload))
        if self.error is not None:
            raise self.error
        return self.result


def _build_consumer(pipeline, producer) -> TaskCreatedConsumer:
    return TaskCreatedConsumer(
        bootstrap_servers="k:9092",
        group_id="g",
        topic_created="tc",
        topic_parsed="tp",
        topic_failed="tf",
        pipeline=pipeline,
        producer=producer,
    )


def _encode_envelope(
    task_id: str = "t1",
    template_id: str = "x",
    script_id: str = "y",
    attempt: int = 1,
) -> bytes:
    return json.dumps(
        {
            "task_id": task_id,
            "attempt": attempt,
            "payload": {
                "template_file_id": template_id,
                "script_file_id": script_id,
            },
        }
    ).encode("utf-8")


# ---------- Успешный путь ----------


@pytest.mark.asyncio
async def test_handle_message_publishes_parsed(fake_producer) -> None:
    pipeline = FakePipeline(
        result=TaskParsedPayload(
            structure_file_id="s",
            template_file_id="t",
            script_file_id="c",
        )
    )
    consumer = _build_consumer(pipeline, fake_producer)

    await consumer._handle_message(_encode_envelope())

    assert len(fake_producer.messages) == 1
    topic, raw = fake_producer.messages[0]
    assert topic == "tp"
    parsed = MessageEnvelope.model_validate_json(raw)
    assert parsed.task_id == "t1"
    assert parsed.payload["structure_file_id"] == "s"


@pytest.mark.asyncio
async def test_handle_message_passes_ids_to_pipeline(fake_producer) -> None:
    pipeline = FakePipeline(
        result=TaskParsedPayload(
            structure_file_id="s",
            template_file_id="t",
            script_file_id="c",
        )
    )
    consumer = _build_consumer(pipeline, fake_producer)

    await consumer._handle_message(_encode_envelope(template_id="tt", script_id="ss"))

    assert len(pipeline.calls) == 1
    task_id, payload = pipeline.calls[0]
    assert task_id == "t1"
    assert payload.template_file_id == "tt"
    assert payload.script_file_id == "ss"


# ---------- Ошибки пайплайна ----------


@pytest.mark.asyncio
async def test_handle_message_publishes_failed_on_pipeline_error(fake_producer) -> None:
    pipeline = FakePipeline(error=RuntimeError("boom"))
    consumer = _build_consumer(pipeline, fake_producer)

    await consumer._handle_message(_encode_envelope())

    assert len(fake_producer.messages) == 1
    topic, raw = fake_producer.messages[0]
    assert topic == "tf"
    parsed = MessageEnvelope.model_validate_json(raw)
    assert parsed.task_id == "t1"
    assert parsed.error == "boom"
    assert parsed.payload["stage"] == STAGE


@pytest.mark.asyncio
async def test_handle_message_error_with_empty_message_uses_class_name(fake_producer) -> None:
    pipeline = FakePipeline(error=RuntimeError())
    consumer = _build_consumer(pipeline, fake_producer)

    await consumer._handle_message(_encode_envelope())

    _, raw = fake_producer.messages[0]
    parsed = MessageEnvelope.model_validate_json(raw)
    assert "RuntimeError" in parsed.error


# ---------- Битый JSON ----------


@pytest.mark.asyncio
async def test_handle_message_broken_json_skips(fake_producer) -> None:
    pipeline = FakePipeline(
        result=TaskParsedPayload(
            structure_file_id="s",
            template_file_id="t",
            script_file_id="c",
        )
    )
    consumer = _build_consumer(pipeline, fake_producer)

    await consumer._handle_message(b"not a json")

    assert fake_producer.messages == []
    assert pipeline.calls == []


@pytest.mark.asyncio
async def test_handle_message_non_utf8_skips(fake_producer) -> None:
    pipeline = FakePipeline()
    consumer = _build_consumer(pipeline, fake_producer)

    await consumer._handle_message(b"\xff\xfe\x00\x00")

    assert fake_producer.messages == []


# ---------- Невалидный payload ----------


@pytest.mark.asyncio
async def test_handle_message_invalid_payload_publishes_failed(fake_producer) -> None:
    pipeline = FakePipeline()
    consumer = _build_consumer(pipeline, fake_producer)

    raw = json.dumps(
        {"task_id": "t1", "payload": {"wrong": "schema"}}
    ).encode("utf-8")

    await consumer._handle_message(raw)

    assert len(fake_producer.messages) == 1
    topic, _ = fake_producer.messages[0]
    assert topic == "tf"
    assert pipeline.calls == []


@pytest.mark.asyncio
async def test_handle_message_invalid_envelope_skips(fake_producer) -> None:
    pipeline = FakePipeline()
    consumer = _build_consumer(pipeline, fake_producer)

    raw = json.dumps({"payload": {}}).encode("utf-8")
    await consumer._handle_message(raw)

    assert fake_producer.messages == []


# ---------- Жизненный цикл ----------


def test_consumer_not_started_state() -> None:
    consumer = _build_consumer(FakePipeline(), None)
    assert consumer._consumer is None


def test_stage_constant() -> None:
    assert STAGE == "parser"