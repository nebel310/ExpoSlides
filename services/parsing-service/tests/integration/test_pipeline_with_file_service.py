from __future__ import annotations

import json

import pytest

from app.kafka.schemas import TaskCreatedPayload
from app.services.parser_pipeline import ParserPipeline
from tests.integration.helpers import build_pptx_with_table, build_simple_pptx

pytestmark = pytest.mark.integration

PPTX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)


async def _upload_pptx(file_client, content: bytes, task_id: str) -> str:
    """Загружает pptx в file-service и возвращает file_id"""
    return await file_client.upload_file(
        filename="template.pptx",
        content=content,
        content_type=PPTX_CONTENT_TYPE,
        task_id=task_id,
    )


async def _download_json(file_client, file_id: str) -> dict:
    """Скачивает JSON-файл из file-service и парсит"""
    raw = await file_client.download_file(file_id, version=0)
    return json.loads(raw.decode("utf-8"))


async def _cleanup(file_client, *file_ids: str) -> None:
    """Удаляет файлы, игнорируя ошибки"""
    for file_id in file_ids:
        try:
            await file_client.delete_file(file_id)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_pipeline_produces_valid_structure_json(file_client):
    """Полный прогон: pptx → file-service → parser → structure.json"""
    task_id = "it-task-simple"
    template_file_id = await _upload_pptx(file_client, build_simple_pptx(), task_id)
    structure_file_id: str | None = None
    try:
        pipeline = ParserPipeline(file_client)
        payload = TaskCreatedPayload(
            template_file_id=template_file_id,
            script_file_id="script-not-used",
        )

        result = await pipeline.process(task_id, payload)
        structure_file_id = result.structure_file_id

        assert result.template_file_id == template_file_id
        assert result.script_file_id == "script-not-used"
        assert structure_file_id != template_file_id

        structure = await _download_json(file_client, structure_file_id)

        assert structure["file_type"] == "pptx"
        assert structure["slide_width"] > 0
        assert structure["slide_height"] > 0
        assert len(structure["slides"]) == 2
        assert len(structure["layouts"]) >= 2

        first_slide = structure["slides"][0]
        assert first_slide["index"] == 1
        texts = [
            element["text"]["full_text"]
            for element in first_slide["elements"]
            if element.get("text")
        ]
        assert any("Integration Test" in t for t in texts)
    finally:
        await _cleanup(file_client, template_file_id, structure_file_id or "")


@pytest.mark.asyncio
async def test_pipeline_parses_table_slide(file_client):
    """Слайд с таблицей попадает в structure.json как TABLE с данными"""
    task_id = "it-task-table"
    template_file_id = await _upload_pptx(file_client, build_pptx_with_table(), task_id)
    structure_file_id: str | None = None
    try:
        pipeline = ParserPipeline(file_client)
        payload = TaskCreatedPayload(
            template_file_id=template_file_id,
            script_file_id="script-not-used",
        )

        result = await pipeline.process(task_id, payload)
        structure_file_id = result.structure_file_id
        structure = await _download_json(file_client, structure_file_id)

        assert len(structure["slides"]) == 1
        slide = structure["slides"][0]
        tables = [el for el in slide["elements"] if el["type"] == "table"]
        assert len(tables) == 1
        table = tables[0]["table"]
        assert table["rows"] == 3
        assert table["cols"] == 3
        assert table["cells"][0][0] == "cell-0-0"
        assert table["cells"][2][2] == "cell-2-2"
    finally:
        await _cleanup(file_client, template_file_id, structure_file_id or "")


@pytest.mark.asyncio
async def test_pipeline_two_runs_produce_different_structures(file_client):
    """Разные pptx дают разные structure_file_id и разное число слайдов"""
    task_a = "it-task-a"
    task_b = "it-task-b"
    tpl_a: str | None = None
    tpl_b: str | None = None
    struct_a: str | None = None
    struct_b: str | None = None
    try:
        tpl_a = await _upload_pptx(file_client, build_simple_pptx(), task_a)
        tpl_b = await _upload_pptx(file_client, build_pptx_with_table(), task_b)

        pipeline = ParserPipeline(file_client)
        res_a = await pipeline.process(
            task_a,
            TaskCreatedPayload(template_file_id=tpl_a, script_file_id="s"),
        )
        res_b = await pipeline.process(
            task_b,
            TaskCreatedPayload(template_file_id=tpl_b, script_file_id="s"),
        )
        struct_a = res_a.structure_file_id
        struct_b = res_b.structure_file_id

        assert struct_a != struct_b

        json_a = await _download_json(file_client, struct_a)
        json_b = await _download_json(file_client, struct_b)
        assert len(json_a["slides"]) == 2
        assert len(json_b["slides"]) == 1
    finally:
        await _cleanup(
            file_client,
            tpl_a or "",
            tpl_b or "",
            struct_a or "",
            struct_b or "",
        )


@pytest.mark.asyncio
async def test_pipeline_fails_on_missing_template(file_client):
    """Несуществующий template_file_id даёт ошибку gRPC"""
    import grpc

    pipeline = ParserPipeline(file_client)
    payload = TaskCreatedPayload(
        template_file_id="does-not-exist-00000000",
        script_file_id="script",
    )

    with pytest.raises(grpc.aio.AioRpcError):
        await pipeline.process("it-task-missing", payload)