# Builder Service

Собирает финальный `.pptx` из исходного шаблона, Presentation JSON (v1/v2) и `content.json` от content-service. Дополнительно умеет конвертировать результат в `.pdf` и `.html`. В сетевом режиме работает как Kafka-воркер: слушает `task.content_ready`, публикует `task.built` или `task.failed`.

## Роль в системе

```
content-service ──task.content_ready──▶ builder-service ──task.built──▶ gateway
                                              │
                                              ├──gRPC──▶ file-service (скачать 3, загрузить N)
                                              └──Kafka──▶ task.failed (при ошибке)
```

Парсит исходный PPTX через `python-pptx`, заменяет текст в placeholder'ах с сохранением стилей, удаляет ненужные слайды, переставляет нужные в порядке из content.json. Сохраняет pptx атомарно и повторно открывает для самопроверки. При запросе пользователя дополнительно конвертирует в PDF (LibreOffice) и HTML (ручной рендер).

## Два режима работы

**CLI** — файловая сборка для ручной отладки. На вход три файла, на выход один pptx.

**Network worker** — основной продовый режим. Kafka + gRPC. Docker и `docker compose` запускают именно его.

## Запуск

### Docker (рекомендуется)

Из корня проекта:

```bash
docker compose up -d --build builder-service
```

Сервис не публикует портов — общается только через Kafka и gRPC file-service.

### CLI

Из корня проекта (полный pipeline через `exposlides`):

```bash
uv run python -m exposlides --template template.pptx --script script.txt --output result.pptx
```

Только сборка (из `services/builder-service`):

```bash
uv run python -m app.main \
    --template-pptx template.pptx \
    --template-json template.json \
    --content-json generated_content.json \
    --output-pptx result.pptx
```

### Network worker вручную (из `services/builder-service`)

Сначала сгенерировать gRPC-модули (один раз):

```bash
uv run python -m grpc_tools.protoc \
    -I../../proto \
    --python_out=. \
    --grpc_python_out=. \
    ../../proto/file_service.proto
```

Потом:

```bash
uv run python -m app.network
```

## Переменные окружения

| Переменная | По умолчанию | Описание |
| --- | --- | --- |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Адрес брокера Kafka |
| `KAFKA_GROUP_ID` | `builder-service` | Group id консьюмера |
| `KAFKA_TOPIC_TASK_CONTENT_READY` | `task.content_ready` | Входящий топик |
| `KAFKA_TOPIC_TASK_BUILT` | `task.built` | Исходящий топик при успехе |
| `KAFKA_TOPIC_TASK_FAILED` | `task.failed` | Исходящий топик при ошибке |
| `FILE_SERVICE_GRPC_HOST` | `file-service` | Адрес file-service |
| `FILE_SERVICE_GRPC_PORT` | `50051` | Порт file-service |
| `FILE_SERVICE_TIMEOUT` | `60` | Таймаут gRPC-вызова, секунды |
| `PDF_CONVERT_TIMEOUT` | `120` | Таймаут LibreOffice на одну конвертацию, секунды |
| `LOG_LEVEL` | `INFO` | Уровень логирования |

## Входящий контракт

### `task.content_ready`

```json
{
  "task_id": "UUID",
  "attempt": 1,
  "payload": {
    "template_file_id": "UUID",
    "structure_file_id": "UUID",
    "content_file_id": "UUID",
    "script_file_id": "UUID",
    "formats": ["pptx", "pdf", "html"]
  },
  "error": null
}
```

Поля:

- `template_file_id` — исходный `.pptx` (шаблон дизайна).
- `structure_file_id` — `structure.json` от parser-service (v1 или v2).
- `content_file_id` — `content.json` от content-service.
- `script_file_id` — исходный текст доклада.
- `formats` — необязательный список желаемых форматов. Допустимые значения: `pptx`, `pdf`, `html`. Если не задан — `["pptx"]`. Неизвестные значения игнорируются. `pptx` создаётся всегда, даже если не указан.

### Формат `content.json`

Единый для CLI и сетевого pipeline:

```json
{
  "content": {
    "1": {"placeholders": {"0": "Заголовок слайда", "1": "Первая строка\nВторая строка"}},
    "2": {"placeholders": {"0": "Заголовок второго"}}
  },
  "validation_report": {"ok": true, "issues": []},
  "error": null
}
```

Ключи `content` — исходные 1-based индексы слайдов шаблона. Ключи `placeholders` — строковый `placeholder_idx` или имя placeholder. Порядок слайдов в `content` задаёт порядок в итоговом pptx.

Если `validation_report.ok = false` или `error` непустой — сборка отменяется, публикуется `task.failed`.

## Исходящий контракт

### `task.built`

```json
{
  "task_id": "UUID",
  "attempt": 1,
  "payload": {
    "template_file_id": "UUID",
    "structure_file_id": "UUID",
    "content_file_id": "UUID",
    "script_file_id": "UUID",
    "formats": ["pptx", "pdf", "html"],
    "result_file_id": "UUID",
    "extra_files": {
      "pdf": "UUID",
      "html": "UUID"
    }
  },
  "error": null
}
```

- `result_file_id` — всегда pptx.
- `extra_files` — карта «формат → file_id» для дополнительных форматов. Пустая, если запрошен только pptx.

### `task.failed`

```json
{
  "task_id": "UUID",
  "attempt": 1,
  "payload": {
    "stage": "builder",
    "reason": "Не удалось собрать или сохранить PPTX"
  },
  "error": "Не удалось собрать или сохранить PPTX"
}
```

Технические детали ошибки пишутся в лог, но не в `reason` — чтобы не раскрывать пути и структуру.

## Как работает сборка

1. Скачивает `template.pptx`, `structure.json`, `content.json` из file-service по gRPC.
2. Парсит структуру в модель `Presentation` (поддерживается v1 и v2 контракта).
3. Открывает pptx через `python-pptx`.
4. Проверяет согласованность template.json ↔ pptx:
   - совпадают размеры слайда,
   - совпадают индексы и layout_name всех слайдов,
   - совпадают ключи placeholder'ов.
5. Удаляет из pptx слайды, которых нет в `content`.
6. Переставляет оставшиеся слайды в порядке `content`.
7. Для каждого слайда заменяет текст в placeholder'ах. Стиль первого run и первого параграфа сохраняется. Многострочный текст превращается в отдельные параграфы (нужно для корректных маркеров списка).
8. Сохраняет результат во временный файл рядом с целевым и **повторно открывает его** для проверки числа слайдов.
9. Загружает `result.pptx` в file-service.
10. Если запрошен PDF — конвертирует через LibreOffice headless.
11. Если запрошен HTML — рендерит вручную из pptx.
12. Публикует `task.built` со всеми file_id.

## Дополнительные форматы

### PDF

Конвертация через `soffice --headless --convert-to pdf`. Требуется LibreOffice в образе. Уже стоит в Dockerfile вместе с базовыми шрифтами (`fonts-dejavu`, `fonts-liberation`, `fonts-noto-core`).

Каждый вызов использует изолированный `-env:UserInstallation`, поэтому параллельные сборки не мешают друг другу.

**Важно про шрифты.** Если шаблон использует кастомный шрифт (например, корпоративный), которого нет в образе, LibreOffice молча подменит его ближайшим доступным — PDF будет визуально отличаться от PPTX по ширине строк. Решение: добавить шрифт в образ (`COPY fonts/ /usr/share/fonts/truetype/custom/`) и выполнить `RUN fc-cache -f`.

### HTML

Собирается вручную из собранного PPTX: каждая фигура превращается в абсолютно позиционированный `<div>`, картинки встраиваются как base64, таблицы — как `<table>`, тексты сохраняют размер, жирность, курсив, выравнивание и цвет. Результат — **один самодостаточный `.html` файл**, открывается в любом браузере без интернета.

**Что не рендерится:** диаграммы, SmartArt, градиентные и паттерновые заливки, коннекторы, OLE-объекты. Они пропускаются, но не ломают остальную вёрстку. HTML не претендует на пиксель-в-пиксель копию — это «читабельный просмотр».

## Семантика доставки

- **At-least-once.** Kafka не даёт гарантий exactly-once. При сбое между upload результата и публикацией `task.built`, или между публикацией и commit offset — после перезапуска сообщение обработается повторно. В file-service это создаст новую версию файла, в Kafka — новое событие. Gateway получает `task.built` с новым `result_file_id`.
- **Commit только после публикации.** Offset входного топика фиксируется после успешной отправки `task.built`. Если публикация в Kafka упала — worker завершается без commit, `docker compose` перезапускает контейнер (`restart: on-failure`).
- **Невалидный конверт.** Если `task_id` не парсится — сообщение пропускается с предупреждением в лог, offset коммитится.
- **SIGTERM/SIGINT.** Все соединения закрываются через `AsyncExitStack`. Незавершённое сообщение может быть обработано повторно при перезапуске.

## Ограничения

- **Повторное использование одного слайда шаблона в одной презентации не поддерживается.** Если content.json ссылается на один `template_slide_index` больше одного раза — сборка падает с `SlideReuseNotSupportedError`. Причина: клонирование слайда требует полного переноса relationships, это пока не реализовано.
- **Удаление слайдов с custom shows или sections запрещено.** Если исходный pptx содержит `custShowLst` или `sectionLst`, ссылающиеся на удаляемые слайды, сборка падает с понятной ошибкой. Это защита от поломки структуры pptx.
- **HTML не 1:1.** Сложные объекты (графики, SmartArt, градиенты) пропускаются.
- **PDF требует шрифтов шаблона в образе.** Иначе тихая подмена.
- **Формат `pptx` создаётся всегда**, даже если не указан в `formats`.

## Тесты

Юнит-тесты лежат в `services/builder-service/tests/unit/`.

```bash
cd services/builder-service
uv run pytest tests/unit -v --asyncio-mode=auto
```

Покрытие:

- `errors.py` — иерархия, сообщения.
- `models/content.py` — `GeneratedContent`, `SlideContent`.
- `models/presentation.py` — v1/v2 совместимость, восстановление полей.
- `utils/text.py` — замена текста, сохранение стилей, многострочность.
- `utils/clone.py` — отклонение клонирования.
- `builder.py` — валидации шаблона, плейсхолдеров, сборка, порядок слайдов, атомарная запись.
- `file_client.py` — gRPC upload/download, отсутствие старта.
- `main.py` — CLI-путь, ошибки входов.
- `network.py` — модели сообщений, `_normalize_formats`, обработка ошибок.
- `export/pdf.py` — конвертация, таймаут, ошибки процесс-менеджмента.
- `export/html.py` — рендер текстов, картинок, таблиц, экранирование, множественные слайды.

Реальный `soffice` в тестах не запускается — только мок `asyncio.create_subprocess_exec`. HTML-тесты используют настоящие pptx, сгенерированные через `python-pptx`.

## Структура

```
services/builder-service/
├── app/
│   ├── models/
│   │   ├── content.py          # GeneratedContent, SlideContent
│   │   └── presentation.py     # Presentation v1/v2
│   ├── utils/
│   │   ├── clone.py            # отклонение клонирования слайдов
│   │   └── text.py             # замена текста placeholder'ов
│   ├── export/
│   │   ├── pdf.py              # LibreOffice headless
│   │   └── html.py             # ручной рендер в HTML
│   ├── builder.py              # ядро сборки PPTX
│   ├── errors.py
│   ├── file_client.py          # gRPC file-service
│   ├── main.py                 # CLI-режим
│   └── network.py              # Kafka worker
├── tests/
│   ├── conftest.py
│   ├── helpers.py
│   └── unit/
├── Dockerfile
└── README.md
```

## Docker

Dockerfile ставит `python:3.11-slim`, зависимости через `uv`, LibreOffice, шрифты. Генерирует gRPC-модули из `proto/file_service.proto` при сборке. CMD — `python -m app.network`.

Кастомные шрифты, если нужны: `COPY fonts/ /usr/share/fonts/truetype/custom/` + `RUN fc-cache -f` в Dockerfile.

## Что осталось за кадром

- **Форматы пока не запрашиваются пользователем.** Gateway не прокидывает `formats` в `task.created`, parser и content не пробрасывают его дальше. Де-факто builder работает всегда с `["pptx"]`. Чтобы пользователь мог выбрать pdf/html, нужно 3 маленькие правки в других сервисах.
- **Gateway не отдаёт `extra_files`.** `task.built` доходит до gateway, но модель задачи в Redis содержит только `result_file_id`. Для скачивания PDF/HTML через UI нужна правка модели и WS-события.
- **Параллельная сборка.** `soffice` — процесс на ~150-300 МБ RAM. При 3 параллельных builder-service (через `--scale`) суммарно до 1 ГБ. Учитывай в лимитах контейнера.
- **Клонирование слайдов.** Реализация через копирование с переносом relationships — отдельная задача. Сейчас функция `clone_slide` явно отклоняет такие попытки.