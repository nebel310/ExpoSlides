# Content Service

Генерирует контент презентации из `structure.json` и текста сценария. Пишет результат в `content.json`, кладёт его в file-service, публикует `task.content_ready` в Kafka. Поддерживает внешний feedback через `task.content_retry`.

## Роль в системе

```
parser-service ──task.parsed──▶ content-service ──task.content_ready──▶ builder-service
                                       │
                                       ├──gRPC──▶ file-service (скачать structure/script, загрузить content.json)
                                       ├──HTTP──▶ LLM provider (HuggingFace / OpenRouter / GigaChat)
                                       └──Kafka──▶ task.failed (при ошибке)
```

## Что делает

- Подписана на топики `task.parsed` и `task.content_retry`
- Скачивает из file-service `structure.json` (результат парсинга шаблона) и `script.txt` (текст доклада)
- Прогоняет граф LangGraph: анализ скрипта → планирование слайдов → генерация текста → валидация
- Публикует `content.json` в file-service
- Отправляет `task.content_ready` со ссылками на structure, content, template, script и список форматов результата
- При ошибке публикует `task.failed` со `stage="content"`
- Сохраняет единый формат `content.json` для CLI и сетевого режима

## Запуск

Из корня проекта

```
docker compose up -d --build content-service
```

Сервис публикует gRPC-порт `50053` для healthcheck, но основной обмен идёт через Kafka.

### CLI-режим (ручная отладка)

```bash
cd services/content-service
uv run python -m app.main --cli \
    --template-json template.json \
    --script script.txt \
    --output-json generated_content.json \
    --generation-mode fast
```

Доступные флаги:

- `--language ru` — язык результата
- `--tone professional` — тон
- `--complexity medium` — сложность формулировок
- `--max-slides N` — ограничить число слайдов
- `--generation-mode standard|fast` — режим
- `--user-mapping path.json` — пользовательская разметка placeholder'ов

### Сетевой режим

```
uv run python -m app.main
```

Запускает gRPC-сервер и Kafka consumer в одном asyncio-loop.

## Переменные окружения

### LLM

| Переменная | По умолчанию | Описание |
|---|---|---|
| `LLM_API_KEY` | пусто | Токен провайдера. Для HuggingFace должен начинаться на `hf_` |
| `LLM_BASE_URL` | `https://router.huggingface.co/v1` | Base URL Chat Completions API |
| `LLM_MODEL` | `Qwen/Qwen3.8-27B:deepinfra` | Модель для standard-режима |
| `LLM_FAST_MODEL` | `Qwen/Qwen3.8-27B:deepinfra` | Модель для fast-режима |
| `LLM_FAST_REPAIR_MODEL` | `Qwen/Qwen3.8-27B:deepinfra` | Модель для короткого исправления |
| `LLM_API_TIMEOUT` | `180` | Таймаут запроса, секунды |
| `LLM_FAST_API_TIMEOUT` | `180` | Таймаут быстрого запроса |
| `FAST_GENERATION_TIMEOUT` | `240` | Общий бюджет fast-режима (30..270) |
| `LLM_TEMPERATURE` | `0.2` | Температура |
| `LLM_REASONING_EFFORT` | `none` | `none`, `low`, `medium`, `xhigh` |
| `LLM_MAX_TOKENS` | `8192` | Максимум токенов в ответе |
| `LLM_RESPONSE_RETRIES` | `2` | Повторы при невалидном JSON |
| `CONTENT_VALIDATION_RETRIES` | `2` | Повторы при ошибке валидации |

### Kafka

| Переменная | По умолчанию | Описание |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Адрес брокера |
| `KAFKA_GROUP_ID` | `content-service` | Group id консьюмера |
| `KAFKA_TOPIC_TASK_PARSED` | `task.parsed` | Слушаем |
| `KAFKA_TOPIC_TASK_CONTENT_READY` | `task.content_ready` | Публикуем |
| `KAFKA_TOPIC_TASK_CONTENT_RETRY` | `task.content_retry` | Слушаем |
| `KAFKA_TOPIC_TASK_FAILED` | `task.failed` | Публикуем при ошибке |

### Прочее

| Переменная | По умолчанию | Описание |
|---|---|---|
| `FILE_SERVICE_GRPC_HOST` | `file-service` | Адрес file-service |
| `FILE_SERVICE_GRPC_PORT` | `50051` | Порт file-service |
| `CONTENT_SERVICE_PORT` | `50053` | Порт gRPC healthcheck |
| `LOG_LEVEL` | `INFO` | Уровень логирования |
| `LOG_FILE` | `content_service.log` | Путь лог-файла |

## Входящий контракт

### `task.parsed`

```json
{
  "task_id": "UUID",
  "attempt": 1,
  "payload": {
    "structure_file_id": "UUID",
    "template_file_id": "UUID",
    "script_file_id": "UUID",
    "formats": ["pptx", "pdf", "html"]
  },
  "error": null
}
```

### `task.content_retry`

```json
{
  "task_id": "UUID",
  "attempt": 2,
  "payload": {
    "structure_file_id": "UUID",
    "script_file_id": "UUID",
    "template_file_id": "UUID",
    "feedback_file_id": "UUID",
    "attempt": 2,
    "formats": ["pptx", "pdf"]
  },
  "error": null
}
```

Поле `formats` опциональное, дефолт `["pptx"]`. Content-service не интерпретирует его, только пробрасывает дальше в `task.content_ready`.

## Исходящий контракт

### `task.content_ready`

```json
{
  "task_id": "UUID",
  "attempt": 1,
  "payload": {
    "structure_file_id": "UUID",
    "content_file_id": "UUID",
    "template_file_id": "UUID",
    "script_file_id": "UUID",
    "formats": ["pptx", "pdf", "html"]
  },
  "error": null
}
```

### `task.failed`

```json
{
  "task_id": "UUID",
  "attempt": 1,
  "payload": {
    "stage": "content",
    "reason": "текстовое описание причины"
  },
  "error": "текстовое описание причины"
}
```

## Формат `content.json`

Единый для CLI и сетевого pipeline:

```json
{
  "content": {
    "1": {"placeholders": {"0": "Заголовок", "1": "Первый пункт\nВторой пункт"}, "notes": null},
    "2": {"placeholders": {"0": "Второй заголовок"}, "notes": null}
  },
  "validation_report": {"ok": true, "issues": []},
  "error": null
}
```

Поля:

- `content` — словарь «индекс слайда шаблона → контент слайда». Индексы 1-based, соответствуют `slides[].index` в `structure.json`.
- `placeholders` — словарь «ключ placeholder → текст». Ключ — строковый `placeholder_idx` (или `name`, если индекса нет).
- `notes` — заметки к слайду, обычно `null`.
- `validation_report` — отчёт валидации. `{"ok": true, "issues": []}` при успехе, иначе `{"ok": false, "issues": [...]}`.
- `error` — текстовое описание ошибки, обычно `null`.

**Порядок слайдов в `content` задаёт порядок в итоговой презентации.** Builder удалит слайды, которых нет в `content`, и переставит оставшиеся.

## Feedback

При внешнем retry content-service скачивает UTF-8 feedback по `feedback_file_id`. Домен сохраняет его в `ContentGraphState.feedback`: замечания передаются в планирование и генерацию текста, включая повторные запросы после ошибок валидации.

Ключевые правила:

- Исходный `script` остаётся неизменным; анализ и grounding используют только его.
- Числа и другие утверждения из feedback **не становятся подтверждёнными фактами**.
- Противоречащие источнику замечания не разрешают отключить проверки.

При отсутствии feedback прежние промпты не меняются. Сетевой домен по умолчанию использует standard-режим. Внешний retry строит новую презентацию — предыдущий сгенерированный файл в его контракте не передаётся.

## Как работает генерация

### Standard-режим

Три последовательных узла LangGraph:

1. **`analyze_script`** — LLM разбирает исходный текст в `ScriptAnalysis`: topic, audience, objective, blocks с фактами, key_messages.
2. **`plan_slides`** — LLM строит `SlidePlan`: для каждого слайда выбирает `template_slide_index` и `source_block_indices`, формулирует `title`, `purpose`, `content`, `key_message`.
3. **`generate_content`** — для каждого слайда LLM заполняет placeholder'ы.
4. **`validate_content`** — программная валидация: длины, факты, маркеры списка. При ошибке — retry до `CONTENT_VALIDATION_RETRIES`.

### Fast-режим

Один большой пакетный запрос на анализ + план, потом пакетный запрос на текст всех полей, потом ограниченное исправление. Укладывается в `FAST_GENERATION_TIMEOUT` секунд. Включён в веб-интерфейсе и при `--generation-mode fast`.

### Что проверяет валидация

- Числа из `script` есть в `content` и наоборот — нет лишних.
- Нет неподтверждённых оценок («вдвое», «на 30%») без источника.
- Тексты слайдов связаны с исходным материалом (пересечение значимых слов).
- Placeholder'ы заполнены.
- Длины не превышают `max_length`.
- Списки без ручных маркеров и пустых строк.
- Нет служебных подписей и выдуманных имён.

## Ограничения

- **Генерация графиков, таблиц, диаграмм, SmartArt, картинок не поддерживается.** Только текст в существующих текстовых placeholder'ах.
- **Новые слайды не создаются.** Используются только слайды, уже присутствующие в шаблоне.
- **Повторное использование одного слайда шаблона не поддерживается.** Один `template_slide_index` — один слайд в результате.
- **LLM работает только с открытыми моделями** до 35B по лицензии Apache 2.0 / MIT.
- **Формат `pdf`/`html` не интерпретируется content-service** — это ответственность builder-service.

## Тесты

Из корня проекта:

```bash
uv run pytest tests/test_content_service_main.py tests/test_content_feedback.py tests/test_fast_generation.py -v
```

Основные группы:

- **Единый формат `content.json`.** CLI и сетевой pipeline пишут одинаковую структуру, читаемую `GeneratedContent` в builder.
- **Feedback.** `task.content_retry` с UTF-8 feedback применяется к планированию и генерации; числа из feedback не становятся фактами.
- **Fast-режим.** Укладывается в таймаут, отвечает корректным JSON, восстанавливается после ошибок валидации.
- **Grounding.** Числа из источника сохраняются, лишние — отбрасываются, неподтверждённые оценки не пропускаются.

## Структура

```
services/content-service/
├── app/
│   ├── certificates/           # корневой CA для GigaChat
│   ├── chains/
│   │   ├── chat_completions.py # HTTP-транспорт Chat Completions API
│   │   ├── llm.py              # структурированный вывод с retry
│   │   ├── openrouter.py       # совместимые имена
│   │   └── prompts.py          # промпты анализа, плана и генерации
│   ├── domain/
│   │   ├── contract.py         # ContentGenerationRequest/Result
│   │   └── generate.py         # вход из pipeline в граф
│   ├── graph/
│   │   ├── builder.py          # сборка LangGraph
│   │   ├── fast.py             # пакетный fast-режим
│   │   ├── nodes.py            # узлы графа
│   │   └── state.py
│   ├── grpc/
│   │   ├── file_service_client.py
│   │   └── server.py           # healthcheck
│   ├── kafka/
│   │   ├── consumer.py
│   │   └── producer.py
│   ├── models/
│   │   ├── graph_state.py
│   │   ├── messages.py         # Kafka-контракты
│   │   ├── presentation.py
│   │   ├── request.py
│   │   └── response.py
│   ├── services/
│   │   └── content_pipeline.py # оркестрация I/O
│   ├── utils/                  # grounding, validation, formatting
│   ├── config.py
│   ├── errors.py
│   └── main.py                 # CLI + serve
├── Dockerfile
└── README.md
```

## Что осталось за кадром

- **`formats` не влияет на генерацию контента** — поле только пробрасывается до builder.
- **Пользовательская разметка** (`user_mapping`) работает в CLI, в сетевом режиме не используется.
- **`schema_version`** структуры проверяется неявно через `PresentationParser` — при несовместимой версии будет явная ошибка.
- **Retry-бюджет.** `content_validation_retries` ограничивает число перегенераций внутри одного сообщения. Внешний retry приходит отдельным событием `task.content_retry`.