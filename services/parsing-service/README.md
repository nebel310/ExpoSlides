# Parser Service

Микросервис парсинга PPTX-шаблонов. Читает задачи из Kafka, разбирает шаблон и публикует структуру презентации обратно в Kafka. Общается с file-service по gRPC, отдаёт gRPC `HealthCheck`.

## Что делает

- Подписан на топик `task.created`, читает задачи на парсинг.
- Скачивает PPTX-шаблон из file-service по `template_file_id`.
- Разбирает шаблон и сохраняет структуру (`structure.json`) в file-service.
- Выгружает бинарные ассеты (картинки, фоны, OLE-объекты) отдельными файлами в file-service, ссылки на них попадают в `assets`.
- Вычисляет типографическую шкалу, сетку и композиционные паттерны из макетов.
- Находит повторяющиеся компоненты и дедуплицирует ассеты по содержимому.
- Проставляет `content_hash` слайдов для поиска дублей в аудите.
- Публикует `task.parsed` с `structure_file_id`, чтобы следующие сервисы пайплайна могли продолжить работу.
- При технической ошибке публикует `task.failed` со `stage = "parser"`.

## Схема данных

Результат парсинга версионирован полем `schema_version`. Текущая версия — **2.0.0**. Analyzer, Content Service, Composer и Audit должны проверять её перед работой и падать с понятной ошибкой на несовместимой версии. Схема описана в `app/models/presentation.py`.

## Взаимодействие по Kafka

Сервис не слушает порт для Kafka, только подключается к брокеру как клиент. Брокер: `kafka:9092` (KRaft). Сериализация — JSON.

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
- Загружает каждый ассет отдельным вызовом `UploadFile`, прописывает полученный `file_id` в `assets[].file_id`.
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
- `UploadFile(filename=<original_name>, content, content_type="image/png", task_id)` — залить каждый ассет. Имя файла и MIME берутся из метаданных картинки, `file_id` в ответе прописывается в `assets[].file_id`.
- `DeleteFile(file_id)` — используется только в тестах.

Между сервисами ходят только `file_id`, байты по Kafka не передаются.

## Формат structure.json

Результат парсинга — сериализованная модель `Presentation` схемы `2.0.0`:

```json
{
  "schema_version": "2.0.0",
  "file_type": "pptx",
  "slide_width": 12192000,
  "slide_height": 6858000,
  "tokens": {
    "theme": {
      "colors": { "dk1": "000000", "accent1": "5B9BD5" },
      "fonts": { "major": "Segoe UI Light", "minor": "Segoe UI" },
      "all_fonts": ["Segoe UI", "Segoe UI Light"]
    },
    "typography": {
      "entries": [
        { "size_pt": 48.0, "role": "display", "occurrences": 1 },
        { "size_pt": 11.0, "role": "body", "occurrences": 90 }
      ],
      "min_pt": 11.0,
      "max_pt": 48.0
    },
    "grid": {
      "margin_left": 521207,
      "margin_right": 543474,
      "column_positions": [502920, 4663440],
      "row_positions": [457200, 2560320]
    }
  },
  "patterns": [
    {
      "id": "pattern-1",
      "name": "content+date+footer+slide_number+title",
      "layout_indices": [2],
      "slots": [
        { "kind": "title", "bbox": { "left": 521207, "top": 448056, "width": 6877119, "height": 640080 }, "idx": 0 },
        { "kind": "content", "bbox": { "left": 539496, "top": 1435608, "width": 4416552, "height": 3977640 }, "idx": 10 }
      ]
    }
  ],
  "components": [
    {
      "id": "component-1",
      "signature": "image|661940|661940|RECTANGLE||122f15f4",
      "element_template": { "id": "slide-9-shape-8", "type": "image" },
      "occurrences": [
        { "slide_index": 9, "element_id": "slide-9-shape-8" },
        { "slide_index": 9, "element_id": "slide-9-shape-7" }
      ]
    }
  ],
  "masters": [
    { "index": 1, "name": "", "layout_indices": [1, 2, 3] }
  ],
  "slides": [
    {
      "index": 1,
      "layout_type": "title",
      "layout_name": "Титульный слайд",
      "layout_index": 1,
      "pattern_id": "pattern-1",
      "elements": [
        {
          "id": "slide-1-shape-2",
          "type": "text",
          "bbox": { "left": 838200, "top": 1164324, "width": 10515600, "height": 2387600 },
          "z_order": 2,
          "placeholder_kind": "title",
          "placeholder_idx": 0,
          "placeholder_name": "Заголовок 1",
          "text": {
            "paragraphs": [
              {
                "level": 0,
                "bullet": false,
                "runs": [
                  {
                    "text": "Добро пожаловать!",
                    "style": {
                      "font_name": "Segoe UI Light",
                      "size_pt": 48.0,
                      "color_token": "bg1"
                    }
                  }
                ]
              }
            ]
          },
          "hidden": false,
          "is_background": false
        }
      ],
      "background": { "kind": "neutral", "fill": { "type": "none", "gradient_stops": [] } },
      "content_hash": "8174891c8903b15b"
    }
  ],
  "layouts": [
    {
      "name": "Титульный слайд",
      "index": 1,
      "layout_type": "title",
      "placeholders": [
        { "kind": "title", "name": "Заголовок 1", "idx": 0, "bbox": { "left": 521208, "top": 448056, "width": 6876288, "height": 640080 } }
      ],
      "background": { "kind": "neutral", "fill": { "type": "none", "gradient_stops": [] } }
    }
  ],
  "assets": [
    {
      "asset_id": "200d8254e0739676",
      "content_type": "image/png",
      "size_bytes": 869797,
      "original_name": "image.png",
      "file_id": null
    }
  ]
}
```

Что извлекается:

- **Слайды** — элементы, `layout_index`, `pattern_id`, `content_hash` для поиска дублей, флаг `hidden` для элементов за пределами слайда, `is_background` для полноэкранных картинок.
- **Элементы** — текст с параграфами и runs (шрифт, кегль, bold/italic/underline, цвет в HEX и токен темы, выравнивание, интервал, маркеры, гиперссылки), таблицы с объединениями ячеек, картинки с `asset_id` и метаданными, диаграммы (`chart`), SmartArt (`smartart`), группы (`group`), коннекторы (`connector`), OLE-объекты, автофигуры с геометрией, заливки (solid/gradient/pattern/picture), обводки, повороты.
- **Layout'ы** — только placeholder'ы и фон, без полного дерева элементов.
- **Тема** — палитра цветов и шрифты major/minor.
- **Типографическая шкала** — вычисленные размеры шрифтов с ролями (`display`, `title`, `body` и т.д.).
- **Сетка** — вычисленные поля и позиции колонок по placeholder'ам макетов.
- **Паттерны** — группы макетов с одинаковой сигнатурой placeholder'ов.
- **Компоненты** — повторяющиеся элементы на 2+ слайдах.
- **Ассеты** — дедуплицированные по SHA-256 байты картинок, фонов, OLE-объектов. Загружаются в file-service отдельно, `file_id` заполняется пайплайном после загрузки.
- **Masters** — список с привязкой к макетам.

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

Для интеграционных и e2e-тестов значения по умолчанию уже подходят для локального запуска. При необходимости переопредели:

```
FILE_SERVICE_GRPC_HOST=localhost
FILE_SERVICE_GRPC_PORT=50051
PARSER_SERVICE_GRPC_HOST=localhost
PARSER_SERVICE_GRPC_PORT=50052
KAFKA_EXTERNAL_BOOTSTRAP=localhost:9093
KAFKA_TOPIC_TASK_CREATED=task.created
KAFKA_TOPIC_TASK_PARSED=task.parsed
KAFKA_TOPIC_TASK_FAILED=task.failed
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

Все тесты делятся на три группы.

**Юнит** — не требуют инфраструктуры:

```bash
uv run pytest services/parsing-service/tests -v --ignore=services/parsing-service/tests/integration --ignore=services/parsing-service/tests/e2e
```

**Интеграционные** — требуют `file-service`, `minio`, `postgres`:

```bash
docker compose up -d file-service minio postgres
uv run pytest services/parsing-service/tests/integration -v
```

**E2E** — требуют полный стек (`kafka`, `file-service`, `parser-service`, `minio`, `postgres`):

```bash
docker compose up -d
uv run pytest services/parsing-service/tests/e2e -v
```

Если инфраструктура недоступна, соответствующие тесты автоматически скипаются с понятным сообщением. Маркеры `integration` и `e2e` зарегистрированы в корневом `pyproject.toml`.

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

CLI-режим для ручной отладки парсинга без Kafka (запускать из `services/parsing-service`):

```bash
cd services/parsing-service
uv run python -m app.main --input-pptx test.pptx --output-json output.json
```