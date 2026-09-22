from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from app.kafka.schemas import MessageEnvelope
from app.models.presentation import Presentation
from tests.e2e.conftest import (
    MESSAGE_TIMEOUT_SEC,
    TOPIC_CREATED,
    TOPIC_FAILED,
    TOPIC_PARSED,
)
from tests.e2e.helpers import (
    make_pptx_with_bullets,
    make_pptx_with_image,
    make_pptx_with_table,
    make_simple_pptx,
)


pytestmark = pytest.mark.e2e


# ---------- Внутренние помощники ----------


async def _publish_task_created(
    producer: AIOKafkaProducer,
    task_id: str,
    template_file_id: str,
    script_file_id: str = "script-e2e",
) -> None:
    """Кладёт MessageEnvelope в task.created"""
    envelope = MessageEnvelope(
        task_id=task_id,
        payload={
            "template_file_id": template_file_id,
            "script_file_id": script_file_id,
        },
    )
    await producer.send_and_wait(TOPIC_CREATED, envelope.model_dump_json().encode("utf-8"))


async def _wait_for_message(
    consumer: AIOKafkaConsumer,
    task_id: str,
    timeout: float = MESSAGE_TIMEOUT_SEC,
) -> MessageEnvelope:
    """Ждёт сообщение с нужным task_id из топика consumer'а"""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise TimeoutError(f"Не дождались task_id={task_id} за {timeout}с")

        batch = await consumer.getmany(timeout_ms=int(remaining * 1000), max_records=50)
        for _, messages in batch.items():
            for msg in messages:
                try:
                    data = json.loads(msg.value.decode("utf-8"))
                except Exception:
                    continue
                if data.get("task_id") == task_id:
                    return MessageEnvelope.model_validate(data)


async def _read_structure(file_client, structure_file_id: str) -> dict:
    """Скачивает structure.json"""
    raw = await file_client.download_file(structure_file_id)
    return json.loads(raw)


# ---------- Успешный путь ----------


@pytest.mark.asyncio
async def test_e2e_simple_pptx_produces_parsed(
    parser_service_ready,
    file_client,
    uploaded_pptx_factory,
    kafka_producer,
    kafka_consumer_factory,
    structure_file_cleanup,
) -> None:
    """task.created → task.parsed со скачиваемым structure.json"""
    task_id = f"e2e-{uuid4().hex}"
    template_id = await uploaded_pptx_factory(
        make_simple_pptx(title="E2E Alpha", subtitle="Subtitle"),
        task_id=task_id,
    )

    consumer = await kafka_consumer_factory([TOPIC_PARSED, TOPIC_FAILED])
    await _publish_task_created(kafka_producer, task_id, template_id)

    envelope = await _wait_for_message(consumer, task_id)
    assert envelope.error is None
    assert envelope.payload["template_file_id"] == template_id
    assert envelope.payload["structure_file_id"]

    await structure_file_cleanup(envelope.payload["structure_file_id"])

    structure = await _read_structure(file_client, envelope.payload["structure_file_id"])
    parsed = Presentation.model_validate(structure)
    assert parsed.schema_version == "2.0.0"
    assert len(parsed.slides) >= 1


@pytest.mark.asyncio
async def test_e2e_structure_contains_title_text(
    parser_service_ready,
    file_client,
    uploaded_pptx_factory,
    kafka_producer,
    kafka_consumer_factory,
    structure_file_cleanup,
) -> None:
    """Текст с титульного слайда попадает в структуру"""
    task_id = f"e2e-{uuid4().hex}"
    template_id = await uploaded_pptx_factory(
        make_simple_pptx(title="Unique-Title-42", subtitle="Unique-Sub-77"),
        task_id=task_id,
    )

    consumer = await kafka_consumer_factory([TOPIC_PARSED, TOPIC_FAILED])
    await _publish_task_created(kafka_producer, task_id, template_id)
    envelope = await _wait_for_message(consumer, task_id)
    await structure_file_cleanup(envelope.payload["structure_file_id"])

    structure = await _read_structure(file_client, envelope.payload["structure_file_id"])
    texts = [
        run["text"]
        for slide in structure["slides"]
        for element in slide["elements"]
        for paragraph in element.get("text", {}).get("paragraphs", [])
        for run in paragraph["runs"]
    ]
    assert "Unique-Title-42" in texts
    assert "Unique-Sub-77" in texts


@pytest.mark.asyncio
async def test_e2e_bullets_are_parsed(
    parser_service_ready,
    file_client,
    uploaded_pptx_factory,
    kafka_producer,
    kafka_consumer_factory,
    structure_file_cleanup,
) -> None:
    """Буллеты с слайда попадают в структуру"""
    task_id = f"e2e-{uuid4().hex}"
    template_id = await uploaded_pptx_factory(
        make_pptx_with_bullets(bullets=4),
        task_id=task_id,
    )

    consumer = await kafka_consumer_factory([TOPIC_PARSED, TOPIC_FAILED])
    await _publish_task_created(kafka_producer, task_id, template_id)
    envelope = await _wait_for_message(consumer, task_id)
    await structure_file_cleanup(envelope.payload["structure_file_id"])

    structure = await _read_structure(file_client, envelope.payload["structure_file_id"])
    all_text = json.dumps(structure, ensure_ascii=False)
    for i in range(1, 5):
        assert f"Bullet {i}" in all_text


@pytest.mark.asyncio
async def test_e2e_table_is_parsed(
    parser_service_ready,
    file_client,
    uploaded_pptx_factory,
    kafka_producer,
    kafka_consumer_factory,
    structure_file_cleanup,
) -> None:
    """Таблица 3×2 попадает в структуру"""
    task_id = f"e2e-{uuid4().hex}"
    template_id = await uploaded_pptx_factory(
        make_pptx_with_table(rows=3, cols=2),
        task_id=task_id,
    )

    consumer = await kafka_consumer_factory([TOPIC_PARSED, TOPIC_FAILED])
    await _publish_task_created(kafka_producer, task_id, template_id)
    envelope = await _wait_for_message(consumer, task_id)
    await structure_file_cleanup(envelope.payload["structure_file_id"])

    structure = await _read_structure(file_client, envelope.payload["structure_file_id"])
    table_elements = [
        element
        for slide in structure["slides"]
        for element in slide["elements"]
        if element["type"] == "table"
    ]
    assert len(table_elements) == 1
    assert table_elements[0]["table"]["rows"] == 3
    assert table_elements[0]["table"]["cols"] == 2


@pytest.mark.asyncio
async def test_e2e_image_asset_uploaded(
    parser_service_ready,
    file_client,
    uploaded_pptx_factory,
    kafka_producer,
    kafka_consumer_factory,
    structure_file_cleanup,
    tmp_path: Path,
) -> None:
    """Картинка выгружается в file-service и asset_ref её видит"""
    task_id = f"e2e-{uuid4().hex}"
    template_id = await uploaded_pptx_factory(
        make_pptx_with_image(tmp_path, slides_with_image=1),
        task_id=task_id,
    )

    consumer = await kafka_consumer_factory([TOPIC_PARSED, TOPIC_FAILED])
    await _publish_task_created(kafka_producer, task_id, template_id)
    envelope = await _wait_for_message(consumer, task_id)
    await structure_file_cleanup(envelope.payload["structure_file_id"])

    structure = await _read_structure(file_client, envelope.payload["structure_file_id"])
    assert len(structure["assets"]) >= 1
    asset = structure["assets"][0]
    assert asset["content_type"] == "image/png"
    assert asset["file_id"]

    downloaded = await file_client.download_file(asset["file_id"])
    assert downloaded.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_e2e_assets_deduplicated(
    parser_service_ready,
    file_client,
    uploaded_pptx_factory,
    kafka_producer,
    kafka_consumer_factory,
    structure_file_cleanup,
    tmp_path: Path,
) -> None:
    """Одна и та же картинка на 3 слайдах → один ассет"""
    task_id = f"e2e-{uuid4().hex}"
    template_id = await uploaded_pptx_factory(
        make_pptx_with_image(tmp_path, slides_with_image=3),
        task_id=task_id,
    )

    consumer = await kafka_consumer_factory([TOPIC_PARSED, TOPIC_FAILED])
    await _publish_task_created(kafka_producer, task_id, template_id)
    envelope = await _wait_for_message(consumer, task_id)
    await structure_file_cleanup(envelope.payload["structure_file_id"])

    structure = await _read_structure(file_client, envelope.payload["structure_file_id"])
    assert len(structure["assets"]) == 1

    asset_ids = [
        element["image"]["asset_id"]
        for slide in structure["slides"]
        for element in slide["elements"]
        if element["type"] == "image"
    ]
    assert len(asset_ids) == 3
    assert len(set(asset_ids)) == 1


@pytest.mark.asyncio
async def test_e2e_two_tasks_isolated(
    parser_service_ready,
    file_client,
    uploaded_pptx_factory,
    kafka_producer,
    kafka_consumer_factory,
    structure_file_cleanup,
) -> None:
    """Две задачи → два разных structure_file_id"""
    task_a = f"e2e-{uuid4().hex}"
    task_b = f"e2e-{uuid4().hex}"
    template_id = await uploaded_pptx_factory(make_simple_pptx(), task_id="shared-template")

    consumer = await kafka_consumer_factory([TOPIC_PARSED, TOPIC_FAILED])
    await _publish_task_created(kafka_producer, task_a, template_id)
    envelope_a = await _wait_for_message(consumer, task_a)
    await _publish_task_created(kafka_producer, task_b, template_id)
    envelope_b = await _wait_for_message(consumer, task_b)

    await structure_file_cleanup(envelope_a.payload["structure_file_id"])
    await structure_file_cleanup(envelope_b.payload["structure_file_id"])

    assert envelope_a.payload["structure_file_id"] != envelope_b.payload["structure_file_id"]


# ---------- Путь с ошибкой ----------


@pytest.mark.asyncio
async def test_e2e_missing_template_goes_to_failed(
    parser_service_ready,
    kafka_producer,
    kafka_consumer_factory,
) -> None:
    """Несуществующий template_file_id → task.failed с stage=parser"""
    task_id = f"e2e-{uuid4().hex}"

    consumer = await kafka_consumer_factory([TOPIC_PARSED, TOPIC_FAILED])
    await _publish_task_created(
        kafka_producer,
        task_id,
        template_file_id="00000000-0000-0000-0000-000000000000",
    )

    envelope = await _wait_for_message(consumer, task_id)
    assert envelope.error
    assert envelope.payload["stage"] == "parser"


@pytest.mark.asyncio
async def test_e2e_invalid_pptx_bytes_goes_to_failed(
    parser_service_ready,
    file_client,
    uploaded_pptx_factory,
    kafka_producer,
    kafka_consumer_factory,
) -> None:
    """Битый pptx (но валидный ZIP) → task.failed"""
    # Создаём валидный pptx, потом ломаем питоновский открыватель —
    # вариант: загрузить пустой zip с правильным расширением.
    # file-service проверит zip + [Content_Types].xml + ppt/ — то есть
    # подделать сложно. Поэтому используем заведомо валидный pptx, но
    # с пустой презентацией (без слайдов) — парсер обработает успешно.
    # Тест на "невалидный pptx" перекладываем в юнит. Здесь проверяем
    # только транспорт: парсер получит, но получит ошибку на уровне
    # чтения структуры, если файл повреждён на уровне pptx.
    #
    # Реалистичный сценарий: file-service отдаст корректные байты,
    # но парсер упадёт, если PowerPoint-структура сломана. Мы не можем
    # подделать это через file-service (он валидирует содержимое),
    # поэтому тест скипается.
    pytest.skip(
        "Невалидный pptx не загрузить через file-service — валидация содержимого. "
        "Сценарий закрыт юнит-тестом test_parse_not_pptx_file_raises."
    )


# ---------- Детерминированность ----------


@pytest.mark.asyncio
async def test_e2e_content_hash_deterministic(
    parser_service_ready,
    file_client,
    uploaded_pptx_factory,
    kafka_producer,
    kafka_consumer_factory,
    structure_file_cleanup,
) -> None:
    """Один и тот же pptx в двух задачах → одинаковый content_hash слайда"""
    content = make_simple_pptx(title="Deterministic", subtitle="Same")

    task_a = f"e2e-{uuid4().hex}"
    task_b = f"e2e-{uuid4().hex}"
    template_a = await uploaded_pptx_factory(content, task_id=task_a)
    template_b = await uploaded_pptx_factory(content, task_id=task_b)

    consumer = await kafka_consumer_factory([TOPIC_PARSED, TOPIC_FAILED])

    await _publish_task_created(kafka_producer, task_a, template_a)
    env_a = await _wait_for_message(consumer, task_a)

    await _publish_task_created(kafka_producer, task_b, template_b)
    env_b = await _wait_for_message(consumer, task_b)

    await structure_file_cleanup(env_a.payload["structure_file_id"])
    await structure_file_cleanup(env_b.payload["structure_file_id"])

    struct_a = await _read_structure(file_client, env_a.payload["structure_file_id"])
    struct_b = await _read_structure(file_client, env_b.payload["structure_file_id"])

    assert struct_a["slides"][0]["content_hash"] == struct_b["slides"][0]["content_hash"]