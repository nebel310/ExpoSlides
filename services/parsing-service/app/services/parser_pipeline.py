from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from app.file_service_client import FileServiceClient
from app.kafka.schemas import TaskCreatedPayload, TaskParsedPayload
from app.models.presentation import Presentation
from app.parsers.pptx_parser import PPTXParser

logger = logging.getLogger(__name__)

STRUCTURE_FILENAME = "structure.json"
STRUCTURE_CONTENT_TYPE = "application/json"


class ParserPipeline:
    """Пайплайн: скачать pptx, распарсить, загрузить structure.json"""

    def __init__(self, file_client: FileServiceClient) -> None:
        """Сохраняет клиент file-service"""
        self._file_client = file_client

    async def process(self, task_id: str, payload: TaskCreatedPayload) -> TaskParsedPayload:
        """Прогоняет пайплайн и возвращает payload для task.parsed"""
        logger.info("Парсинг задачи %s: template=%s", task_id, payload.template_file_id)
        pptx_bytes = await self._file_client.download_file(
            payload.template_file_id, version=0
        )
        presentation = await self._parse_pptx_bytes(pptx_bytes)
        structure_json = presentation.model_dump_json(indent=2).encode("utf-8")
        structure_file_id = await self._file_client.upload_file(
            filename=STRUCTURE_FILENAME,
            content=structure_json,
            content_type=STRUCTURE_CONTENT_TYPE,
            task_id=task_id,
        )
        logger.info("Структура загружена: %s", structure_file_id)
        return TaskParsedPayload(
            structure_file_id=structure_file_id,
            template_file_id=payload.template_file_id,
            script_file_id=payload.script_file_id,
        )

    async def _parse_pptx_bytes(self, pptx_bytes: bytes) -> Presentation:
        """Парсит pptx из байтов через временный файл"""
        tmp_path = await asyncio.to_thread(self._write_temp_pptx, pptx_bytes)
        try:
            return await PPTXParser.parse(tmp_path)
        finally:
            await asyncio.to_thread(tmp_path.unlink, True)

    @staticmethod
    def _write_temp_pptx(content: bytes) -> Path:
        """Записывает байты во временный .pptx и возвращает путь"""
        fd, name = tempfile.mkstemp(suffix=".pptx")
        os.close(fd)
        path = Path(name)
        path.write_bytes(content)
        return path