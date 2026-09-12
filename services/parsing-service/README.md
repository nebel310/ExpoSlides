# Parser Service

Микросервис парсинга PPTX-шаблонов. Читает `task.created` из Kafka, скачивает PPTX из file-service, разбирает структуру и публикует `task.parsed` со ссылкой на `structure.json`. При технической ошибке публикует `task.failed` со `stage = "parser"`.

## Что делает

- Слушает топик `task.created`, валидирует конверт и payload через Pydantic.
- Скачивает PPTX-шаблон из file-service по gRPC (`DownloadFile`, `version = 0`).
- Прогоняет PPTX через `PPTXParser` и получает модель `Presentation`.
- Загружает `structure.json` обратно в file-service (`UploadFile`) и получает `structure_file_id`.
- Публикует `task.parsed` с payload `{ structure_file_id, template_file_id, script_file_id }`.
- При технической ошибке (файл не найден, парсинг упал) публикует `task.failed` и коммитит offset.
- Отдаёт gRPC `HealthCheck` для проверки живости.

## Kafka

Брокер: `kafka:9092` (KRaft). Сериализация — JSON.

Общий конверт сообщения:

```json
{
  "task_id": "uuid",
  "attempt": 1,
  "payload": { ... },
  "error": null
}
```

### Топики

| Топик | Роль | Payload |
|---|---|---|
| `task.created` | consumer | `{ "template_file_id", "script_file_id" }` |
| `task.parsed` | producer | `{ "structure_file_id", "template_file_id", "script_file_id" }` |
| `task.failed` | producer | `{ "stage": "parser", "reason": "..." }` |

### Логика обработки

1. Прочитать сообщение, распарсить в `MessageEnvelope` → `TaskCreatedPayload`.
2. Если конверт или payload невалидны — залогировать, коммитнуть offset, не публиковать ничего.
3. Вызвать `ParserPipeline.process(task_id, payload)`.
4. Успех — публикация в `task.parsed`, коммит offset.
5. Технический фейл — публикация в `task.failed` со `stage = "parser"`, коммит offset.

Бизнес-ретраев у сервиса нет — ретраи живут на стороне evaluation/content.

## gRPC API

Порт: `50052`. Контракт: `proto/parser_service.proto`.

### HealthCheck

Проверка живости сервиса. Возвращает `status = "ok"`.

## Взаимодействие с file-service

Сервис использует gRPC-клиент `FileServiceClient` (см. `proto/file_service.proto` в корне проекта).

- `DownloadFile(file_id, version=0)` — скачать PPTX-шаблон.
- `UploadFile(filename, content, content_type, task_id, file_id?)` — залить `structure.json`.
- `DeleteFile(file_id)` — используется в интеграционных/e2e тестах для очистки.

Между сервисами передаются только `file_id`, байты по Kafka не ходят.

## Правила обработки PPTX

Парсер `PPTXParser` (на базе `python-pptx` + `lxml`) извлекает:

- слайды, layout'ы, тему (цвета и шрифты);
- текстовые элементы, параграфы, runs и их стили;
- таблицы, изображения, placeholder'ы;
- z-order, фон, заметки к слайдам.

На выходе — модель `Presentation` (см. `app/models/presentation.py`), которая сериализуется в `structure.json` со схемой:

```
{
  "source_path": "...",
  "file_type": "pptx",
  "slide_width": ...,
  "slide_height": ...,
  "slides": [...],
  "layouts": [...],
  "theme": {...}
}
```

## Переменные окружения

```
KAFKA_BOOTSTRAP_SERVERS=kafka:9092
KAFKA_GROUP_ID=parser-service
KAFKA_TOPIC_TASK_CREATED=task.created
KAFKA_TOPIC_TASK_PARSED=task.parsed
KAFKA_TOPIC_TASK_FAILED=task.failed
FILE_SERVICE_GRPC_HOST=file-service
FILE_SERVICE_GRPC_PORT=50051
PARSER_SERVICE_PORT=50052
```

Для e2e-тестов дополнительно (значения по умолчанию подходят для локального запуска):

```
E2E_FILE_SERVICE_HOST=127.0.0.1
E2E_FILE_SERVICE_PORT=50051
E2E_PARSER_SERVICE_HOST=127.0.0.1
E2E_PARSER_SERVICE_PORT=50052
E2E_KAFKA_BOOTSTRAP=localhost:9093
E2E_TOPIC_TASK_PARSED=task.parsed
E2E_TOPIC_TASK_FAILED=task.failed
```

## Запуск

Из корня проекта:

```bash
docker compose up -d --build
```

Сервис доступен на `localhost:50052` (gRPC healthcheck). Kafka — `localhost:9093` (EXTERNAL listener).

## Генерация gRPC-кода

При изменении `proto/parser_service.proto` или `proto/file_service.proto` (нужен для клиента file-service):

```bash
uv run python -m grpc_tools.protoc \
  -Iproto \
  --python_out=services/parsing-service \
  --grpc_python_out=services/parsing-service \
  proto/parser_service.proto \
  proto/file_service.proto
```

В Docker-образе генерация выполняется автоматически при сборке.

## Тесты

```bash
uv run pytest services/parsing-service/tests -v
```

Требуют запущенных контейнеров `kafka`, `file-service`, `minio`, `postgres` для integration/e2e. Unit-тесты проходят без инфраструктуры.

- `tests/test_schemas.py` — Pydantic-модели Kafka-конверта.
- `tests/test_file_service_client.py` — gRPC-клиент file-service (моки).
- `tests/test_producer.py` — Kafka producer (мок `AIOKafkaProducer`).
- `tests/test_pipeline.py` — пайплайн download → parse → upload (моки file-client).
- `tests/test_consumer.py` — обработка сообщений `task.created` (моки pipeline/producer).
- `tests/test_grpc_server.py` — gRPC healthcheck и lifecycle.
- `tests/test_main.py` — CLI-режим парсинга.
- `tests/integration/` — реальный file-service, реальный PPTX → валидный `structure.json`.
- `tests/e2e/` — полный путь через Kafka: `task.created` → `task.parsed` / `task.failed`.

## Пример использования (Python)

Публикация задачи в `task.created`:

```python
import asyncio
import json
from aiokafka import AIOKafkaProducer

async def main():
    producer = AIOKafkaProducer(bootstrap_servers="localhost:9093")
    await producer.start()
    try:
        message = {
            "task_id": "task-123",
            "attempt": 1,
            "payload": {
                "template_file_id": "<file_id pptx>",
                "script_file_id": "<file_id txt>",
            },
            "error": None,
        }
        await producer.send_and_wait("task.created", json.dumps(message).encode())
    finally:
        await producer.stop()

asyncio.run(main())
```

Healthcheck parser-service:

```python
import grpc
from google.protobuf import empty_pb2
import parser_service_pb2, parser_service_pb2_grpc

channel = grpc.insecure_channel("localhost:50052")
stub = parser_service_pb2_grpc.ParserServiceStub(channel)
print(stub.HealthCheck(empty_pb2.Empty()).status)
```

CLI-режим для ручного парсинга файла:

```bash
uv run python -m app.main --input-pptx test.pptx --output-json output.json
```