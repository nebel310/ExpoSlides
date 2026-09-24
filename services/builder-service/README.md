# Builder service

Собирает PPTX из исходного шаблона, Presentation JSON (v1/v2) и JSON content-service.
Сохраняет стили и порядок выбранных слайдов. Повторное использование одного слайда
шаблона не поддерживается. Сохранённый PPTX повторно открывается и проверяется.

## Файловый CLI

Из корня проекта:

```bash
uv run python -m exposlides --template template.pptx --script script.txt --output result.pptx
```

Для отдельной сборки запустите из `services/builder-service`:

```bash
uv run python -m app.main --template-pptx template.pptx --template-json template.json --content-json generated_content.json --output-pptx result.pptx
```

## Сетевой worker

Точка входа: `uv run python -m app.network` из каталога сервиса.
Dockerfile и сервис `builder-service` в корневом Compose запускают именно её.
Нужны доступные Kafka и file-service с его хранилищем; отдельного HTTP/gRPC-порта
у builder нет. Сгенерируйте grpc-модули для локального запуска (из корня):

```bash
uv run python -m grpc_tools.protoc -Iproto --python_out=services/builder-service --grpc_python_out=services/builder-service proto/file_service.proto
```

Переменные окружения:

| Переменная | По умолчанию |
| --- | --- |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` |
| `KAFKA_GROUP_ID` | `builder-service` |
| `KAFKA_TOPIC_TASK_CONTENT_READY` | `task.content_ready` |
| `KAFKA_TOPIC_TASK_BUILT` | `task.built` |
| `KAFKA_TOPIC_TASK_FAILED` | `task.failed` |
| `FILE_SERVICE_GRPC_HOST` | `file-service` |
| `FILE_SERVICE_GRPC_PORT` | `50051` |
| `FILE_SERVICE_TIMEOUT` | `60` секунд на RPC |
| `LOG_LEVEL` | `INFO` |

Вход `task.content_ready`:

```json
{
  "task_id": "UUID",
  "attempt": 1,
  "payload": {
    "template_file_id": "UUID",
    "structure_file_id": "UUID",
    "content_file_id": "UUID",
    "script_file_id": "UUID"
  },
  "error": null
}
```

Worker скачивает template, structure и content, собирает PPTX во временном каталоге,
загружает `result.pptx` и публикует `task.built`. Конверт сохраняет `task_id` и
`attempt`; payload содержит исходные четыре ссылки и новый `result_file_id`.
Gateway уже обрабатывает это событие, переводит задачу в `done` и сохраняет ссылку
на результат. Формат content.json: `content`, `validation_report`, `error`.

Ошибки входных файлов, сборки и file-service приводят к `task.failed` с
`payload.stage="builder"`. Конверт без корректного task_id/attempt отбрасывается
с предупреждением. Offset фиксируется только после подтверждения выходного
события Kafka. При сбое публикации worker завершается без commit; Compose
перезапускает его. Доставка at-least-once: после сбоя между upload/publish/commit
возможны повторные файлы и события, гарантии exactly-once нет. При SIGTERM/SIGINT
соединения закрываются; незавершённое сообщение может быть обработано повторно.

Офлайн-проверка: `uv run pytest tests/test_builder_network.py tests/test_pptx_builder.py`.
Тест создаёт настоящий PPTX, разбирает его parser v2, собирает результат, проверяет
порядок/текст/стиль после повторного открытия и передаёт событие обработчику gateway.
File-service/Kafka подменены, Redis — fakeredis. Отдельные тесты проверяют ошибки,
порядок publish/commit, RPC и закрытие ресурсов. Это не проверка живого Compose.
