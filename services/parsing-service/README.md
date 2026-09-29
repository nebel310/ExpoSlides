# Parser Service

Разбирает PPTX-шаблон в структурированный JSON (`structure.json`) со всеми элементами дизайн-системы: слайды, макеты, темы, типографика, сетка, паттерны, компоненты, ассеты. Публикует результат в file-service и передаёт дальше по пайплайну через Kafka.

## Роль в системе

```
gateway ──task.created──▶ parser-service ──task.parsed──▶ content-service
                                │
                                ├──gRPC──▶ file-service (скачать pptx, загрузить structure.json + ассеты)
                                └──Kafka──▶ task.failed (при ошибке)
```

## Что делает

- Подписан на топик `task.created`
- Скачивает PPTX-шаблон из file-service по gRPC
- Разбирает шаблон в модель `Presentation` схемы v2.0.0
- Выгружает бинарные ассеты (картинки, фоны, OLE-объекты) отдельными файлами в file-service
- Вычисляет типографическую шкалу, сетку и композиционные паттерны
- Находит повторяющиеся компоненты и дедуплицирует ассеты по SHA-256
- Проставляет `content_hash` слайдов для поиска дублей
- Публикует `structure.json` в file-service
- Отправляет `task.parsed` со ссылками на structure, template, script и список форматов результата
- При технической ошибке публикует `task.failed` со `stage="parser"`

## Запуск

Из корня проекта

```
docker compose up -d --build parser-service
```

Сервис публикует gRPC-порт `50052` для healthcheck, основной обмен идёт через Kafka.

### CLI-режим (ручная отладка)

```bash
cd services/parsing-service
uv run python -m app.main --input-pptx test.pptx --output-json output.json
```

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Адрес брокера |
| `KAFKA_GROUP_ID` | `parser-service` | Group id консьюмера |
| `KAFKA_TOPIC_TASK_CREATED` | `task.created` | Слушаем |
| `KAFKA_TOPIC_TASK_PARSED` | `task.parsed` | Публикуем |
| `KAFKA_TOPIC_TASK_FAILED` | `task.failed` | Публикуем при ошибке |
| `FILE_SERVICE_GRPC_HOST` | `file-service` | Адрес file-service |
| `FILE_SERVICE_GRPC_PORT` | `50051` | Порт file-service |
| `PARSER_SERVICE_PORT` | `50052` | Порт gRPC healthcheck |

## Входящий контракт

### `task.created`

```json
{
  "task_id": "UUID",
  "attempt": 1,
  "payload": {
    "template_file_id": "UUID",
    "script_file_id": "UUID",
    "formats": ["pptx", "pdf", "html"]
  },
  "error": null
}
```

Поля:

- `template_file_id` — `file_id` ранее загруженного `.pptx`-шаблона.
- `script_file_id` — `file_id` ранее загруженного `.txt`-сценария. Parser его не читает, только пробрасывает дальше.
- `formats` — необязательный список форматов результата. Дефолт `["pptx"]`. Parser **не интерпретирует** его, только пробрасывает в `task.parsed`.

## Исходящий контракт

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

`structure_file_id` — ссылка на загруженный `structure.json`. Content-service скачает его и будет планировать слайды по нему.

### `task.failed`

```json
{
  "task_id": "UUID",
  "attempt": 1,
  "payload": {
    "stage": "parser",
    "reason": "текстовое описание причины"
  },
  "error": "текстовое описание причины"
}
```

## Схема `structure.json`

Для неизвестных шаблонов парсер обходит макеты всех мастеров, разрешает тему
конкретного слайда и сохраняет её в `slides[].theme`, `layouts[].theme`, `masters[].theme`.
Глобальные `tokens.theme` сохраняют роль темы по умолчанию. Индексы макетов и мастеров
начинаются с 1. Композиционные паттерны учитывают расположение и размеры слотов,
включая обычные текстовые блоки макетов; это детерминированная геометрическая
эвристика, а не смысловая классификация дизайна.

У каждого элемента дополнительно доступны `shape_id`, `shape_name` и `shape_path`
(цепочка исходных shape IDs через вложенные группы). Поле `bbox` сохраняет исходную
локальную систему координат, а `slide_bbox` содержит ограничивающую рамку на слайде
в EMU с учётом масштаба, поворота и отражений групп. Полное дерево элементов макета
находится в `layouts[].elements`, дерево декора мастера — в `masters[].elements`.
`has_text_frame` и `default_text_style` сохраняют типографику пустых полей; цвет и
начертание текста разрешаются по цепочке paragraph → layout → master. Эти необязательные поля расширяют контракт v2
без изменения старых полей. Геометрическая рамка не доказывает отсутствие
переполнения текста: для этого нужен аудит результата верстки.




Схема версионирована полем `schema_version`. Текущая версия — **2.0.0**. Content, builder и audit должны проверять её перед работой и падать с понятной ошибкой на несовместимой версии.

```json
{
  "schema_version": "2.0.0",
  "file_type": "pptx",
  "slide_width": 12192000,
  "slide_height": 6858000,
  "tokens": {
    "theme": {
      "colors": {"dk1": "000000", "accent1": "5B9BD5"},
      "fonts": {"major": "Segoe UI Light", "minor": "Segoe UI"},
      "all_fonts": ["Segoe UI", "Segoe UI Light"]
    },
    "typography": {
      "entries": [
        {"size_pt": 48.0, "role": "display", "occurrences": 1},
        {"size_pt": 11.0, "role": "body", "occurrences": 90}
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
        {"kind": "title", "bbox": {...}, "idx": 0},
        {"kind": "content", "bbox": {...}, "idx": 10}
      ]
    }
  ],
  "components": [
    {
      "id": "component-1",
      "signature": "image|661940|661940|RECTANGLE||122f15f4",
      "element_template": {"id": "slide-9-shape-8", "type": "image"},
      "occurrences": [
        {"slide_index": 9, "element_id": "slide-9-shape-8"},
        {"slide_index": 9, "element_id": "slide-9-shape-7"}
      ]
    }
  ],
  "masters": [
    {"index": 1, "name": "", "layout_indices": [1, 2, 3]}
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
          "bbox": {"left": 838200, "top": 1164324, "width": 10515600, "height": 2387600},
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
                    "style": {"font_name": "Segoe UI Light", "size_pt": 48.0, "color_token": "bg1"}
                  }
                ]
              }
            ]
          },
          "hidden": false,
          "is_background": false
        }
      ],
      "background": {"kind": "neutral", "fill": {"type": "none", "gradient_stops": []}},
      "content_hash": "8174891c8903b15b"
    }
  ],
  "layouts": [
    {
      "name": "Титульный слайд",
      "index": 1,
      "layout_type": "title",
      "placeholders": [
        {"kind": "title", "name": "Заголовок 1", "idx": 0, "bbox": {...}}
      ],
      "background": {"kind": "neutral", "fill": {"type": "none", "gradient_stops": []}}
    }
  ],
  "assets": [
    {
      "asset_id": "200d8254e0739676",
      "content_type": "image/png",
      "size_bytes": 869797,
      "original_name": "image.png",
      "file_id": "UUID"
    }
  ]
}
```

### Что извлекается

**Слайды:**

- Элементы, `layout_index`, `pattern_id`
- `content_hash` — стабильный хэш содержимого для поиска дублей
- Флаг `hidden` — для элементов за пределами слайда
- Флаг `is_background` — для полноэкранных картинок

**Элементы:**

- Типы: `text`, `image`, `table`, `chart`, `smartart`, `group`, `connector`, `ole`, `shape`, `other`
- Текст с параграфами и runs: шрифт, кегль, bold/italic/underline, цвет в HEX и токен темы, выравнивание, интервал, маркеры, гиперссылки
- Таблицы с объединениями ячеек
- Картинки с `asset_id` и метаданными
- Диаграммы (`chart`): тип, серии, оси, легенда, подписи данных
- SmartArt: layout_name, style_name, color_name, дерево узлов
- Группы фигур (рекурсивно)
- Коннекторы: тип, координаты, стрелки
- OLE-объекты
- Автофигуры с геометрией
- Заливки: solid / gradient / pattern / picture
- Обводки, повороты

**Layout'ы:**

- Placeholder'ы и фон
- Без полного дерева элементов

**Тема:**

- Палитра цветов и шрифты major/minor
- Полный список шрифтов, встречающихся в runs

**Типографическая шкала:**

- Размеры шрифтов с ролями (`display`, `title`, `subtitle`, `heading`, `subheading`, `body`, `caption`, `small`)
- Минимум и максимум

**Сетка:**

- Поля слева/справа/сверху/снизу
- Позиции колонок и строк по placeholder'ам макетов

**Паттерны:**

- Группы макетов с одинаковой сигнатурой placeholder'ов

**Компоненты:**

- Элементы, повторяющиеся на 2+ слайдах

**Masters:**

- Список с привязкой к макетам

**Ассеты:**

- Дедуплицированные по SHA-256 байты картинок, фонов, OLE
- Загружаются в file-service отдельно, `file_id` заполняется в pipeline

## Как работает парсинг

1. Скачивает PPTX из file-service по gRPC.
2. Открывает через `python-pptx`.
3. Извлекает тему из `theme1.xml`.
4. Разбирает макеты: placeholder'ы, фон.
5. Строит паттерны по сигнатурам макетов.
6. Разбирает мастера.
7. Для каждого слайда:
   - Все элементы с типами и стилями.
   - Метаданные layout'а и pattern_id.
   - Фон.
   - Помечает `hidden` и `is_background`.
   - Считает `content_hash`.
8. Собирает все шрифты, типографическую шкалу, сетку.
9. Находит повторяющиеся компоненты.
10. Дедуплицирует ассеты по содержимому.
11. Загружает каждый ассет в file-service отдельным `UploadFile`, получает `file_id`, прописывает в `assets[].file_id`.
12. Сериализует `Presentation` в `structure.json`, грузит в file-service.
13. Публикует `task.parsed`.

## Дедупликация ассетов

Каждая картинка, фон и OLE-объект регистрируется по SHA-256 от байтов. Если один и тот же файл встречается на нескольких слайдах — в `assets` он будет один раз, а ссылки из слайдов пойдут на тот же `asset_id`.

## `content_hash` слайда

Стабильный хэш SHA-256 от комбинации типов и координат элементов, текстов, `asset_id`. Используется audit-сервисом для поиска дублей слайдов и проверки «слайд не изменился».

Хэш **не зависит** от порядка элементов внутри `elements[]` на уровне XML, но зависит от:
- типа каждого элемента,
- `bbox.left`, `bbox.top`,
- текста всех runs,
- `asset_id` картинок,
- рекурсивно — детей групп.

## Ошибки

- **Технический фейл** (шаблон не найден, PPTX битый, file-service недоступен) — публикует `task.failed` со `stage="parser"` и непустым `reason`, коммитит offset.
- **Невалидный конверт или payload** — логирует и коммитит offset без публикации. Ретраев нет.
- **Бизнес-провалов нет.** Парсинг либо отработал, либо упал технически.

## Идемпотентность

Не гарантируется. При повторной доставке одного и того же `task_id` сервис обработает задачу ещё раз и загрузит новую версию `structure.json`. Это безопасно: file-service поддерживает версионирование.

## Формат `task.created` при ретрае

Parser не публикует `task.content_retry`, но если такой топик появится в его группе — он его проигнорирует, потому что подписан только на `task.created`.

## Тесты

Из корня проекта:

```bash
uv run pytest services/parsing-service/tests -v \
    --ignore=services/parsing-service/tests/integration \
    --ignore=services/parsing-service/tests/e2e
```

Три группы:

**Юнит** (без инфраструктуры):

- `test_pptx_parser.py` — базовый парсинг
- `test_pptx_parser_v2.py` — контракт v2
- `test_pptx_text.py` — текст, runs, стили
- `test_pptx_shapes.py` — фигуры, группы, коннекторы
- `test_pptx_tables.py` — таблицы и объединения
- `test_pptx_charts.py` — диаграммы
- `test_pptx_smartart.py` — SmartArt
- `test_pptx_assets.py` — дедупликация ассетов
- `test_pptx_tokens.py` — тема, типографика, сетка
- `test_consumer.py`, `test_producer.py`, `test_schemas.py` — Kafka
- `test_main.py` — CLI
- `test_pipeline.py` — оркестрация

**Интеграционные** (нужны file-service, minio, postgres):

```bash
docker compose up -d file-service minio postgres
uv run pytest services/parsing-service/tests/integration -v
```

**E2E** (нужен полный стек):

```bash
docker compose up -d
uv run pytest services/parsing-service/tests/e2e -v
```

Если инфраструктура недоступна — тесты скипаются с понятным сообщением.

## Структура

```
services/parsing-service/
├── app/
│   ├── grpc/
│   │   ├── file_service_client.py
│   │   └── server.py             # healthcheck
│   ├── kafka/
│   │   ├── consumer.py
│   │   ├── producer.py
│   │   └── schemas.py            # Kafka-контракты
│   ├── models/
│   │   ├── legacy_presentation.py # контракт v1
│   │   └── presentation.py        # контракт v2
│   ├── parsers/
│   │   ├── pptx/
│   │   │   ├── assets.py          # дедупликация ассетов
│   │   │   ├── charts.py          # диаграммы
│   │   │   ├── helpers.py
│   │   │   ├── parser.py          # главный парсер v2
│   │   │   ├── shapes.py          # фигуры, группы, коннекторы
│   │   │   ├── smartart.py        # SmartArt
│   │   │   ├── tables.py          # таблицы
│   │   │   ├── text.py            # текст и runs
│   │   │   └── tokens.py          # тема, типографика, сетка, паттерны, компоненты
│   │   ├── base.py
│   │   ├── pptx_parser.py         # парсер v1 (legacy)
│   │   └── text_style.py          # наследуемые шрифты
│   ├── services/
│   │   └── parser_pipeline.py
│   ├── utils/
│   │   └── file_utils.py
│   ├── config.py
│   └── main.py                    # CLI + serve
├── tests/
│   ├── conftest.py
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── Dockerfile
└── README.md
```

## Ограничения

- **Схема v2.0.0 стабильна** — изменения ломают content, builder, audit.
- **Parser не читает содержимое ассетов** — только сохраняет байты.
- **Диаграммы и SmartArt читаются частично** — только для последующего анализа, не редактируются.
- **PPTX должен быть валидным ZIP с `[Content_Types].xml` и папкой `ppt/`** — иначе file-service отклонит загрузку.
- **Content-Type ассетов** определяется по magic bytes при загрузке в file-service.

## Что осталось за кадром

- **`formats` не влияет на парсинг** — поле только пробрасывается.
- **Пользовательская разметка** (`user_mapping`) в parser не поддерживается.
- **Инкрементального парсинга нет** — каждый запуск пересобирает всё заново.
- **Ретраев внутри parser нет** — упал, значит `task.failed`.