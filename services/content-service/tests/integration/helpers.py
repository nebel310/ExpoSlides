import json
import os
from uuid import uuid4

from aiokafka.admin import AIOKafkaAdminClient, NewTopic


KAFKA_BOOTSTRAP = os.getenv("E2E_KAFKA_BOOTSTRAP", "localhost:9093")
FILE_SERVICE_HOST = os.getenv("E2E_FILE_SERVICE_HOST", "127.0.0.1")
FILE_SERVICE_PORT = int(os.getenv("E2E_FILE_SERVICE_PORT", "50051"))
PIPELINE_TIMEOUT = float(os.getenv("E2E_PIPELINE_TIMEOUT", "30"))

VALID_STRUCTURE = {
    "slide_width": 9144000,
    "slide_height": 6858000,
    "slides": [
        {
            "index": 1,
            "layout_type": "title",
            "layout_name": "Title Slide",
            "elements": [
                {
                    "type": "text",
                    "placeholder_type": "TITLE",
                    "placeholder_idx": 0,
                    "placeholder_name": "Title 1",
                    "text": {"full_text": "Старый заголовок"},
                }
            ],
        }
    ],
    "layouts": [],
    "theme": {},
}

VALID_SCRIPT = "Это исходный текст презентации про новый продукт компании."

STUB_CONTENT = {
    "1": {"placeholders": {"0": "Сгенерированный заголовок"}, "notes": None},
}


async def create_topics(names: list[str]) -> None:
    """Создать топики в Kafka, если их ещё нет"""
    admin = AIOKafkaAdminClient(bootstrap_servers=KAFKA_BOOTSTRAP)
    await admin.start()
    try:
        existing = set(await admin.list_topics())
        to_create = [
            NewTopic(name=name, num_partitions=1, replication_factor=1)
            for name in names
            if name not in existing
        ]
        if to_create:
            await admin.create_topics(to_create)
    finally:
        await admin.close()


async def upload_inputs(file_client, task_id: str) -> dict[str, str]:
    """Загрузить structure.json, script.txt и заглушку template в file-service"""
    structure_file_id = await file_client.upload_file(
        filename="structure.json",
        content=json.dumps(VALID_STRUCTURE, ensure_ascii=False).encode("utf-8"),
        content_type="application/json",
        task_id=task_id,
    )
    script_file_id = await file_client.upload_file(
        filename="script.txt",
        content=VALID_SCRIPT.encode("utf-8"),
        content_type="text/plain",
        task_id=task_id,
    )
    template_file_id = await file_client.upload_file(
        filename="template.txt",
        content=b"placeholder template",
        content_type="text/plain",
        task_id=task_id,
    )
    return {
        "structure_file_id": structure_file_id,
        "script_file_id": script_file_id,
        "template_file_id": template_file_id,
    }


def make_parsed_envelope(task_id: str, ids: dict[str, str]) -> dict:
    """Собрать конверт task.parsed для публикации"""
    return {
        "task_id": task_id,
        "attempt": 1,
        "payload": {
            "structure_file_id": ids["structure_file_id"],
            "template_file_id": ids["template_file_id"],
            "script_file_id": ids["script_file_id"],
        },
        "error": None,
    }


def new_suffix() -> str:
    """Сгенерировать короткий уникальный суффикс для имён"""
    return uuid4().hex[:10]