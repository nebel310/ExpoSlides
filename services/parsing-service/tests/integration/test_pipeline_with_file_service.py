from __future__ import annotations

import json
from pathlib import Path

import grpc
import pytest
import pytest_asyncio
import os

import file_service_pb2
import file_service_pb2_grpc

from app.config import settings
from app.kafka.schemas import TaskCreatedPayload, TaskParsedPayload
from app.models.presentation import Presentation
from app.services.parser_pipeline import (
    STRUCTURE_CONTENT_TYPE,
    STRUCTURE_FILENAME,
    ParserPipeline,
)
from tests.integration.helpers import (
    make_pptx_with_bullets,
    make_pptx_with_image,
    make_pptx_with_table,
    make_simple_pptx,
)


pytestmark = pytest.mark.integration


# ---------- Файлы в file-service ----------


@pytest.mark.asyncio
async def test_upload_download_roundtrip(real_file_client, uploaded_pptx) -> None:
    """Загруженный pptx скачивается в том же виде"""
    original = make_simple_pptx(title="Roundtrip", subtitle="Test")

    file_id = await uploaded_pptx(original, task_id="roundtrip")
    downloaded = await real_file_client.download_file(file_id, version=0)

    assert downloaded == original


@pytest.mark.asyncio
async def test_upload_reports_pptx_type(real_file_client, uploaded_pptx) -> None:
    """file-service распознаёт загруженный pptx как pptx"""
    original = make_simple_pptx()
    file_id = await uploaded_pptx(original, task_id="type-check")

    info = await _get_file_info(real_file_client, file_id)

    assert info["content_type"] == (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
    assert info["file_type"] == "pptx"
    assert info["size"] == len(original)


@pytest.mark.asyncio
async def test_upload_invalid_content_raises(real_file_client) -> None:
    """Невалидное содержимое не принимается"""
    with pytest.raises(Exception):
        await real_file_client.upload_file(
            filename="bad.pptx",
            content=b"this is not a pptx",
            content_type="application/octet-stream",
            task_id="bad-upload",
        )


@pytest.mark.asyncio
async def test_delete_removes_file(real_file_client, uploaded_pptx) -> None:
    """После delete_file скачивание падает"""
    file_id = await uploaded_pptx(make_simple_pptx(), task_id="delete-check")

    await real_file_client.delete_file(file_id)

    with pytest.raises(Exception):
        await real_file_client.download_file(file_id)


# ---------- Пайплайн целиком ----------


@pytest.mark.asyncio
async def test_pipeline_returns_parsed_payload(
    real_file_client, uploaded_pptx_factory
) -> None:
    """Пайплайн возвращает корректный TaskParsedPayload"""
    template_id = await uploaded_pptx_factory(make_simple_pptx(), task_id="pipeline-1")
    pipeline = ParserPipeline(real_file_client)
    payload = TaskCreatedPayload(
        template_file_id=template_id, script_file_id="script-1"
    )

    result = await pipeline.process("task-pipeline-1", payload)

    assert isinstance(result, TaskParsedPayload)
    assert result.template_file_id == template_id
    assert result.script_file_id == "script-1"
    assert result.structure_file_id


@pytest.mark.asyncio
async def test_pipeline_structure_json_is_readable(
    real_file_client, uploaded_pptx_factory
) -> None:
    """structure.json читается и валидируется как Presentation"""
    template_id = await uploaded_pptx_factory(
        make_pptx_with_bullets(bullets=3), task_id="pipeline-2"
    )
    pipeline = ParserPipeline(real_file_client)
    payload = TaskCreatedPayload(
        template_file_id=template_id, script_file_id="script-2"
    )

    result = await pipeline.process("task-pipeline-2", payload)

    structure_bytes = await real_file_client.download_file(
        result.structure_file_id
    )
    parsed = Presentation.model_validate(json.loads(structure_bytes))

    assert parsed.schema_version == "2.0.0"
    assert len(parsed.slides) == 1
    assert parsed.slides[0].layout_type.value == "bullets"


@pytest.mark.asyncio
async def test_pipeline_structure_contains_title(
    real_file_client, uploaded_pptx_factory
) -> None:
    """Текст с титульного слайда попадает в структуру"""
    template_id = await uploaded_pptx_factory(
        make_simple_pptx(title="Project Alpha", subtitle="Q1 Review"),
        task_id="pipeline-3",
    )
    pipeline = ParserPipeline(real_file_client)
    payload = TaskCreatedPayload(
        template_file_id=template_id, script_file_id="script-3"
    )

    result = await pipeline.process("task-pipeline-3", payload)
    structure = await _read_structure(real_file_client, result.structure_file_id)

    slide = structure["slides"][0]
    texts = [
        run["text"]
        for element in slide["elements"]
        for paragraph in element.get("text", {}).get("paragraphs", [])
        for run in paragraph["runs"]
    ]
    assert "Project Alpha" in texts
    assert "Q1 Review" in texts


@pytest.mark.asyncio
async def test_pipeline_parses_table(
    real_file_client, uploaded_pptx_factory
) -> None:
    """Таблица из pptx попадает в структуру"""
    template_id = await uploaded_pptx_factory(
        make_pptx_with_table(rows=3, cols=2), task_id="pipeline-4"
    )
    pipeline = ParserPipeline(real_file_client)
    payload = TaskCreatedPayload(
        template_file_id=template_id, script_file_id="script-4"
    )

    result = await pipeline.process("task-pipeline-4", payload)
    structure = await _read_structure(real_file_client, result.structure_file_id)

    table_elements = [
        element
        for element in structure["slides"][0]["elements"]
        if element["type"] == "table"
    ]
    assert len(table_elements) == 1
    assert table_elements[0]["table"]["rows"] == 3
    assert table_elements[0]["table"]["cols"] == 2


@pytest.mark.asyncio
async def test_pipeline_missing_template_raises(real_file_client) -> None:
    """Несуществующий template_file_id → ошибка"""
    pipeline = ParserPipeline(real_file_client)
    payload = TaskCreatedPayload(
        template_file_id="00000000-0000-0000-0000-000000000000",
        script_file_id="script-x",
    )

    with pytest.raises(Exception):
        await pipeline.process("task-missing", payload)


# ---------- Ассеты ----------


@pytest.mark.asyncio
async def test_pipeline_uploads_image_asset(
    real_file_client, uploaded_pptx_factory, tmp_path: Path
) -> None:
    """Картинка из pptx выгружается в file-service и привязана к asset_ref"""
    template_id = await uploaded_pptx_factory(
        make_pptx_with_image(tmp_path, slides_with_image=1),
        task_id="assets-1",
    )
    pipeline = ParserPipeline(real_file_client)
    payload = TaskCreatedPayload(
        template_file_id=template_id, script_file_id="script-a1"
    )

    result = await pipeline.process("task-assets-1", payload)
    structure_bytes = await real_file_client.download_file(result.structure_file_id)
    structure = json.loads(structure_bytes)

    assert len(structure["assets"]) >= 1
    asset = structure["assets"][0]
    assert asset["content_type"] == "image/png"
    assert asset["file_id"]

    downloaded_asset = await real_file_client.download_file(asset["file_id"])
    assert downloaded_asset.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_pipeline_deduplicates_same_image(
    real_file_client, uploaded_pptx_factory, tmp_path: Path
) -> None:
    """Одна и та же картинка на нескольких слайдах → один ассет"""
    template_id = await uploaded_pptx_factory(
        make_pptx_with_image(tmp_path, slides_with_image=3),
        task_id="assets-2",
    )
    pipeline = ParserPipeline(real_file_client)
    payload = TaskCreatedPayload(
        template_file_id=template_id, script_file_id="script-a2"
    )

    result = await pipeline.process("task-assets-2", payload)
    structure = await _read_structure(real_file_client, result.structure_file_id)

    assert len(structure["assets"]) == 1
    # и три слайда ссылаются на него
    refs = [
        element["image"]["asset_id"]
        for slide in structure["slides"]
        for element in slide["elements"]
        if element["type"] == "image"
    ]
    assert len(refs) == 3
    assert len(set(refs)) == 1


# ---------- Изоляция задач ----------


@pytest.mark.asyncio
async def test_pipeline_isolates_tasks(
    real_file_client, uploaded_pptx_factory
) -> None:
    """Два прогона с разными task_id дают разные structure_file_id"""
    template_id = await uploaded_pptx_factory(
        make_simple_pptx(), task_id="isolation-1"
    )
    pipeline = ParserPipeline(real_file_client)
    payload = TaskCreatedPayload(
        template_file_id=template_id, script_file_id="script-iso"
    )

    first = await pipeline.process("task-iso-1", payload)
    second = await pipeline.process("task-iso-2", payload)

    assert first.structure_file_id != second.structure_file_id


@pytest.mark.asyncio
async def test_pipeline_deterministic_content_hash(
    real_file_client, uploaded_pptx_factory
) -> None:
    """Одинаковый pptx даёт одинаковый content_hash в структуре"""
    content = make_simple_pptx(title="Deterministic", subtitle="Yes")
    template_id = await uploaded_pptx_factory(content, task_id="hash-check")
    pipeline = ParserPipeline(real_file_client)
    payload = TaskCreatedPayload(
        template_file_id=template_id, script_file_id="script-hash"
    )

    first = await pipeline.process("task-hash-1", payload)
    second = await pipeline.process("task-hash-2", payload)

    structure_1 = await _read_structure(real_file_client, first.structure_file_id)
    structure_2 = await _read_structure(real_file_client, second.structure_file_id)

    assert (
        structure_1["slides"][0]["content_hash"]
        == structure_2["slides"][0]["content_hash"]
    )


# ---------- Хелперы ----------


async def _read_structure(file_client, structure_file_id: str) -> dict:
    """Скачивает structure.json и возвращает его как dict"""
    raw = await file_client.download_file(structure_file_id)
    return json.loads(raw)


async def _get_file_info(file_client, file_id: str) -> dict:
    """Запрашивает метаданные файла через стаб напрямую"""
    host = os.environ.get("FILE_SERVICE_GRPC_HOST", "localhost")
    port = os.environ.get("FILE_SERVICE_GRPC_PORT", "50051")
    target = f"{host}:{port}"

    async with grpc.aio.insecure_channel(target) as channel:
        stub = file_service_pb2_grpc.FileServiceStub(channel)
        response = await stub.GetFileInfo(
            file_service_pb2.GetFileInfoRequest(file_id=file_id, version=0)
        )
        return {
            "file_id": response.file_id,
            "content_type": response.content_type,
            "file_type": response.file_type,
            "size": response.size,
        }