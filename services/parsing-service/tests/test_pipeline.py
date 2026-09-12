from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from pptx import Presentation as PPTXPresentation

from app.kafka.schemas import TaskCreatedPayload
from app.services.parser_pipeline import ParserPipeline


@pytest.fixture
def sample_pptx_bytes() -> bytes:
    """Минимальный pptx с одним слайдом для тестов пайплайна"""
    prs = PPTXPresentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Hello"
    buffer = BytesIO()
    prs.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def fake_file_client() -> MagicMock:
    """Мок FileServiceClient с async-методами download/upload"""
    client = MagicMock()
    client.download_file = AsyncMock()
    client.upload_file = AsyncMock(return_value="structure-id")
    return client


@pytest.fixture
def pipeline(fake_file_client: MagicMock) -> ParserPipeline:
    """Пайплайн с мок-клиентом file-service"""
    return ParserPipeline(fake_file_client)


@pytest.mark.asyncio
async def test_process_returns_parsed_payload(pipeline, fake_file_client, sample_pptx_bytes):
    """process возвращает TaskParsedPayload с корректными file_id"""
    fake_file_client.download_file.return_value = sample_pptx_bytes
    payload = TaskCreatedPayload(template_file_id="tpl-1", script_file_id="scr-1")

    result = await pipeline.process("task-1", payload)

    assert result.structure_file_id == "structure-id"
    assert result.template_file_id == "tpl-1"
    assert result.script_file_id == "scr-1"


@pytest.mark.asyncio
async def test_process_downloads_latest_version(pipeline, fake_file_client, sample_pptx_bytes):
    """process скачивает pptx по template_file_id с version=0"""
    fake_file_client.download_file.return_value = sample_pptx_bytes
    payload = TaskCreatedPayload(template_file_id="tpl-1", script_file_id="scr-1")

    await pipeline.process("task-1", payload)

    fake_file_client.download_file.assert_awaited_once_with("tpl-1", version=0)


@pytest.mark.asyncio
async def test_process_uploads_valid_json(pipeline, fake_file_client, sample_pptx_bytes):
    """process заливает structure.json с валидным JSON-содержимым"""
    fake_file_client.download_file.return_value = sample_pptx_bytes
    payload = TaskCreatedPayload(template_file_id="tpl-1", script_file_id="scr-1")

    await pipeline.process("task-1", payload)

    kwargs = fake_file_client.upload_file.call_args.kwargs
    assert kwargs["filename"] == "structure.json"
    assert kwargs["content_type"] == "application/json"
    assert kwargs["task_id"] == "task-1"
    parsed = json.loads(kwargs["content"].decode("utf-8"))
    assert parsed["file_type"] == "pptx"
    assert "slides" in parsed
    assert len(parsed["slides"]) == 1


@pytest.mark.asyncio
async def test_process_propagates_download_error(pipeline, fake_file_client):
    """Ошибка скачивания пробрасывается наверх"""
    fake_file_client.download_file.side_effect = RuntimeError("download failed")
    payload = TaskCreatedPayload(template_file_id="tpl-1", script_file_id="scr-1")

    with pytest.raises(RuntimeError, match="download failed"):
        await pipeline.process("task-1", payload)

    fake_file_client.upload_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_propagates_parse_error(pipeline, fake_file_client):
    """Ошибка парсинга (битый pptx) пробрасывается наверх"""
    fake_file_client.download_file.return_value = b"not-a-pptx"
    payload = TaskCreatedPayload(template_file_id="tpl-1", script_file_id="scr-1")

    with pytest.raises(Exception):
        await pipeline.process("task-1", payload)

    fake_file_client.upload_file.assert_not_awaited()