# ExpoSlides

ExpoSlides превращает PPTX-шаблон и текстовый сценарий в новую редактируемую презентацию.
Локальный pipeline последовательно разбирает шаблон, генерирует проверенный контент через
GigaChat и собирает итоговый PPTX.

## Быстрый старт

Требуются `uv`, Python 3.11–3.13 и доступ к GigaChat API.

```bash
uv sync --locked
cp -n .env.example services/content-service/.env
```

Укажите реальный `LLM_API_KEY` только в локальном
`services/content-service/.env`; этот файл исключён из Git.

Запуск из корня репозитория:

```bash
uv run python -m exposlides \
  --template /path/to/template.pptx \
  --script /path/to/script.txt \
  --output /path/to/result.pptx \
  --max-slides 5
```

Команда выполняет три этапа в отдельных процессах:

1. `parsing-service`: PPTX → `template.json`;
2. `content-service`: template JSON + script → `generated_content.json`;
3. `builder-service`: template PPTX + generated content → проверенный итоговый PPTX.

Результат публикуется атомарно только после проверки ZIP-структуры, повторного открытия через
`python-pptx` и сверки количества слайдов. Существующий output не перезаписывается без
`--force`.

Чтобы сохранить промежуточные JSON и лог конкретного запуска:

```bash
uv run python -m exposlides \
  --template template.pptx \
  --script script.txt \
  --output result.pptx \
  --artifacts-dir artifacts
```

Каждый запуск получает отдельный каталог `artifacts/exposlides-*`. Без этого флага временные
файлы удаляются автоматически. Все параметры доступны через:

```bash
uv run python -m exposlides --help
```

## Требования к шаблону

- Формат — `.pptx`.
- Для генерации нужны существующие текстовые placeholders.
- Каждый выбранный слайд шаблона используется не более одного раза.
- Итоговый порядок соответствует плану content-service, а не исходному порядку шаблона.
- Если исключаемые слайды входят в PowerPoint custom show или section, builder завершится
  понятной ошибкой: безопасное обновление этих presentation-level ссылок пока не реализовано.

Builder сохраняет геометрию и оформление выбранных слайдов, заменяя текст placeholders.
Строки многострочного list-контента записываются отдельными PowerPoint-абзацами и получают
маркеры из шаблона; ручные дефисы, bullets, нумерация и пустые пункты в LLM-ответе
отправляются на retry.
Новые слайды, повторное клонирование одного образца, обычные text boxes, изображения и таблицы
как генерируемые слоты пока не поддерживаются.

## Прямой запуск этапов

У каждого сервиса есть CLI с явными путями:

```bash
cd services/parsing-service
uv run python -m app.main --help

cd ../content-service
uv run python -m app.main --help

cd ../builder-service
uv run python -m app.main --help
```

Обычный пользовательский сценарий должен идти через корневую команду `python -m exposlides`.

## Проверки разработки

```bash
uv lock --check
uv run ruff check .
uv run pytest
```

Тесты полностью офлайн: LLM подменяется детерминированными реализациями. E2E-тест создаёт
PPTX программно, проводит его через parser, настоящий LangGraph с fake LLM и builder, затем
повторно открывает результат и проверяет порядок, текст и стили.

## Сравнение качества генерации

Фиксированные сценарии и scorer находятся в `evals`. Пример оценки сохранённого ответа:

```bash
uv run python evals/score.py quarterly-results generated_content.json
```

Метрики и правила сопоставимого сравнения версий описаны в
[`evals/README.md`](evals/README.md). Scorer не заменяет редакторскую и визуальную проверку.

## Статус проекта

Рабочий локальный MVP замыкает файловую цепочку `PPTX → JSON → LLM → PPTX`. API gateway,
Kafka, protobuf, Docker/Compose и автоматическая визуальная evaluation остаются roadmap.
Датированный разбор архитектурных ограничений находится в
[`PROJECT_REVIEW.md`](PROJECT_REVIEW.md).
