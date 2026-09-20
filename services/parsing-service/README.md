# Parser Service

Микросервис парсинга PPTX-шаблонов. Читает задачи из Kafka, разбирает шаблон и публикует структуру презентации обратно в Kafka. Общается с file-service по gRPC, отдаёт gRPC `HealthCheck`.

## Что делает

- Подписан на топик `task.created`, читает задачи на парсинг.
- Скачивает PPTX-шаблон из file-service по `template_file_id`.
- Разбирает шаблон и сохраняет структуру (`structure.json`) в file-service.
- Публикует `task.parsed` с `structure_file_id`, чтобы следующие сервисы пайплайна могли продолжить работу.
- При технической ошибке публикует `task.failed` со `stage = "parser"`.

## Kafka API

Порт не используется. Брокер: `kafka:9092` (KRaft). Сериализация — JSON.

### Общий конверт сообщения

Все сообщения в пайплайне ходят в едином конверте:

```json
{
  "task_id": "uuid",
  "attempt": 1,
  "payload": { ... },
  "error": null
}
```

### Топики

| Топик | Роль сервиса | Payload |
|---|---|---|
| `task.created` | consumer | `{ "template_file_id": "uuid", "script_file_id": "uuid" }` |
| `task.parsed` | producer | `{ "structure_file_id": "uuid", "template_file_id": "uuid", "script_file_id": "uuid" }` |
| `task.failed` | producer | `{ "stage": "parser", "reason": "..." }` |

### Поведение

- Читает `task.created`, валидирует конверт и payload.
- Скачивает PPTX-шаблон (`template_file_id`, последняя версия) из file-service.
- Разбирает шаблон, загружает `structure.json` в file-service (`content_type = "application/json"`, `task_id` пробрасывается).
- Публикует `task.parsed` с `structure_file_id`, `template_file_id`, `script_file_id`.
- `attempt` из входящего конверта пробрасывается в исходящий без изменений.
- Коммитит offset после публикации результата (или после `task.failed`).

### Ошибки

- **Технический фейл** (шаблон не найден, PPTX битый, file-service недоступен) — публикует `task.failed` со `stage = "parser"` и непустым `reason`, затем коммитит offset.
- **Невалидный конверт или payload** — логирует и коммитит offset без публикации. Ретраев нет.
- **Бизнес-провалов нет.** Парсинг либо отработал, либо упал технически.

### Идемпотентность

Не гарантируется. При повторной доставке одного и того же `task_id` сервис обработает задачу ещё раз и загрузит новую версию `structure.json`. Это безопасно: file-service поддерживает версионирование.

## gRPC API

Порт: `50052`. Контракт: `proto/parser_service.proto`.

### HealthCheck

Проверка живости сервиса. Возвращает `status = "ok"`.

## Взаимодействие с file-service

Сервис — gRPC-клиент file-service (контракт `proto/file_service.proto` в корне проекта). Использует:

- `DownloadFile(file_id, version=0)` — скачать PPTX-шаблон.
- `UploadFile(filename="structure.json", content, content_type="application/json", task_id, file_id=None)` — залить структуру.

Между сервисами ходят только `file_id`, байты по Kafka не передаются.

## Формат structure.json

Результат парсинга — сериализованная модель `Presentation`:

```
{
  "source_path": "...",
  "file_type": "pptx",
  "slide_width": 9144000,
  "slide_height": 6858000,
  "slides": [
    {
      "index": 1,
      "layout_type": "title",
      "layout_name": "Title Slide",
      "layout_index": 1,
      "placeholder_type": "TITLE",
      "elements": [
        {
          "id": "slide-1-shape-2",
          "type": "text",
          "bbox": { "left": 0, "top": 0, "width": 0, "height": 0 },
          "z_order": 1,
          "placeholder_type": "TITLE",
          "placeholder_idx": 0,
          "placeholder_name": "Title 1",
          "text": {
            "paragraphs": [...],
            "full_text": "..."
          }
        }
      ],
      "background": { "fill_type": "1", "color_hex": "FFFFFF" },
      "notes": null
    }
  ],
  "layouts": [...],
  "theme": { "colors": {...}, "fonts": {...} }
}
```

Извлекаются: слайды, layout'ы, тема (цвета и шрифты), текстовые элементы с параграфами/runs и стилями, таблицы, изображения, placeholder'ы, z-order, фон, заметки.

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

Сервис доступен на `localhost:50052` (gRPC healthcheck). Kafka — `localhost:9093` (EXTERNAL listener для подключения с хоста).

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

## Пример использования (Python)

Публикация задачи на парсинг:

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

Подписка на результат:

```python
import asyncio
import json
from aiokafka import AIOKafkaConsumer

async def main():
    consumer = AIOKafkaConsumer(
        "task.parsed",
        "task.failed",
        bootstrap_servers="localhost:9093",
        group_id="my-service",
        auto_offset_reset="latest",
    )
    await consumer.start()
    try:
        async for message in consumer:
            data = json.loads(message.value.decode())
            if data["task_id"] == "task-123":
                print(message.topic, data["payload"])
                break
    finally:
        await consumer.stop()

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

CLI-режим для ручной отладки парсинга без Kafka (только внутри контейнера/локально):

```bash
uv run python -m app.main --input-pptx test.pptx --output-json output.json
```