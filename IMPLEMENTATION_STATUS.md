# Результат доработки по ТЗ VK Tech

Дата: 27 сентября 2026 года. Ветка: `codex/vk-tech-completion`.

Рабочее дерево: `/Users/aleksemanov/.codex/worktrees/vk-tech-completion/ExpoSlides`.
Основа — доступный локально `origin/dev`, коммит `12f4fb1`.
Исходный checkout `/Users/aleksemanov/projects/ExpoSlides` с незавершёнными изменениями
сохранён. Новый код находится в указанном отдельном рабочем дереве; запускать студию
нужно из него. Изменения не опубликованы и не развёрнуты на внешнем сервере.

Исходный подробный разбор сохранён в [VK_TECH_AUDIT_2026-09-27.md](VK_TECH_AUDIT_2026-09-27.md).
Это датированный снимок до реализации. Текущее поведение описывают README, ARCHITECTURE,
MODELS, AUDIT и этот документ; старые выводы аудита не следует считать текущим состоянием.

## Реализовано

| Часть | Полученный результат | Основные файлы |
| --- | --- | --- |
| Шаблон | Обычные текстовые поля и placeholders, группы и преобразования координат, несколько masters/layouts/themes, защищённые элементы и свободные области | `template_profile.py`, `design_geometry.py`, parser models и `parsers/pptx/` |
| История | Общий план до верстки, точное/максимальное число слайдов, источники, обязательные сообщения, проверка чисел, единиц, периодов, сущностей и отрицаний | `design_content.py`, `design_models.py`, `app/design_main.py`, `fact_grounding.py` |
| Три варианта | Разные композиции с одинаковыми исходными фактами; повторное использование одного образца; адаптация областей под объём текста | `design_layout.py` |
| PowerPoint | Независимые копии слайдов и зависимых частей, нативные текст/таблицы/графики со встроенной книгой, схемы/пиктограммы, SmartArt по совместимому образцу | `design_builder.py`, `design_pptx_parts.py`, `design_smartart.py` |
| Проверка | Геометрия, защищённые элементы, стили, данные, полнота; повторное открытие и проверка сохранённого PPTX; отдельный адаптер контекстуального аудита | `design_audit.py`, `design_saved_audit.py`, `app/design_audit.py` |
| Исправления | Выбор замечаний, ограниченное уменьшение кегля/расширение в свободную область, положение и палитра; повторный аудит и сохранение предыдущих версий | `design_audit.py`, `design_pipeline.py` |
| Экспорт | Настоящие PPTX, PDF, PNG и автономный HTML; SVG-представление при доступном pdftocairo | `design_export.py`, `preview.py` |
| Интерфейс | React/TypeScript, материалы TXT/CSV/JSON, редактирование плана, просмотр слайдов/замечаний, версии и загрузки, история и восстановление | `frontend/`, `exposlides/studio_static/`, `studio.py` |
| Управление работами | Ограниченная очередь, отмена, общий срок выполнения, сохранение готовой части при сбое, атомарная публикация версии | `studio.py`, `design_pipeline.py` |
| Модели | Версионируемые роли/промпты/реестр, ограничения лицензии и размера; отдельные текстовый, мультимодальный и необязательный image адаптеры | `agents/`, `prompts/`, `config/`, `app/design_*.py` |
| Воспроизводимость | Запуск из одного TOML, сохранённый запрос/план/профиль, manifest с хешами материалов и ресурсов, измеримый benchmark | `run_config.py`, `design_cli.py`, `scripts/benchmark_designer.py` |
| Сетевые сервисы | Исправления владения файлами, повторной доставки событий, переходов состояний, ожидания подписки, проверки загрузок | `services/gateway-service/`, `file-service/`, service consumers |
| Проверки | Изолированные офлайн suites, регрессии реальных ошибок, тесты интерфейса, конфигурация CI | `tests/`, service tests, `scripts/test_services.py`, `.github/workflows/checks.yml` |

Имена файлов без каталога в таблице относятся к `exposlides/`; `app/design_*.py` —
к `services/content-service/`. Старый placeholder pipeline сохранён отдельно.
Новый дизайнер не объявляется работающим внутри Kafka-контура.

## Что было проверено

Основной baseline перед работой: 1 072 проходящих корневых теста. Проверки
выполнялись под Python 3.12 из uv, без реальных LLM API. Ближайшие регрессии
запускались при каждом изменении; финальные команды и числа приведены ниже.

Реальная проверка конвертера использует LibreOffice и Poppler. Программно созданные
PPTX повторно открывались, проверялись текст, данные, стили и связи, создавались PDF
и изображения. Это больше, чем проверка успешного `save()`, но не замена PowerPoint.

В браузере проверен сценарий: пример → импорт CSV → общий план → нативный график →
три результата → выбранное исправление и новая версия → сохранение прежней версии →
перезагрузка и история. Проверка выявила и помогла исправить переполнение карточек,
слишком короткую подпись рядом с графиком, тесные подписи оси и выбор кегля заголовка
при исправлении. Для этих случаев добавлены регрессии.

Скачанный через кнопку интерфейса PPTX также открыт через python-pptx: пять слайдов,
нативный график, три исходные категории и значения 12/18/24 сохранены.

Отдельно выполнен реальный десятистраничный SVG-экспорт через pdftocairo:
HTML использует SVG, PDF содержит десять страниц. PNG fallback также проверен.

Полный архив синтетического benchmark, manifest и точных времён находится в
[VALIDATION_2026-09-27.md](VALIDATION_2026-09-27.md). Четыре синтетических шаблона
дают 12 комплектов PPTX/PDF/HTML и 138 изображений. Сравнение хешей трёх изображений
подтверждает различие композиций, но само по себе не оценивает их художественное качество.
Окончательный прогон: **4/4 passed**, **29.899 с** суммарно, **7.167–7.909 с**
на три варианта одного шаблона. Во всех 12 отчётах — ноль ошибок и предупреждений;
контекстуальная модельная проверка выключена (`not_run`). Во время прогона
50 зафиксированных хешей реализации не изменились.

## Внешняя приёмка, которая ещё нужна

Эти пункты нельзя честно закрыть количеством unit-тестов:

1. Три официальных конкурсных шаблона и официальный контент-пакет не предоставлены.
   Нужны девять реальных результатов и прогон на неизвестном шаблоне.
2. Живой инференс VK, включая мультимодальный режим, не проверен. Адаптеры проверены
   подменой ответов. Необходимы выданный endpoint/alias и локальная конфигурация;
   секреты не следует передавать в чат или репозиторий.
3. Качество формулировок и фактов реальной модели, задержка и визуальный аудит
   должны оцениваться на официальных материалах. Время extractive-прогона
   не является временем LLM-генерации.
4. Нужна проверка PowerPoint: редактирование нативных объектов, корпоративные шрифты,
   совместимый SmartArt и отсутствие предупреждений восстановления. LibreOffice
   и синтетические OOXML fixtures не доказывают поведение всех версий Office.
5. Полная матрица актуальной/предыдущей версии Chrome, Firefox, Safari и Яндекс Браузера
   на целевых ОС не пройдена. Проверка выполнена в браузере приложения Codex на macOS.
6. Изолированные сетевые тесты не поднимают настоящий Kafka/Redis/MinIO/PostgreSQL-контур.
   Его интеграционная приёмка и внешний deploy остаются отдельной работой.

Ограничения реализации: профиль неизвестного шаблона строится эвристически;
вместимость текста приближённая; SmartArt требует совместимого образца;
автоматические исправления доступны только для ограниченного набора правил.
Защищённые объекты сохраняются, но presentation-level custom shows/sections
отклоняются, а анимации с клонируемых слайдов удаляются. Не каждый графический объект
шаблона может быть переосмыслен автоматически. Подробные границы — в [AUDIT.md](AUDIT.md).

## Как открыть результат

```bash
cd /Users/aleksemanov/.codex/worktrees/vk-tech-completion/ExpoSlides
uv sync --locked
uv run python -m exposlides.studio
```

Открыть `http://127.0.0.1:8765`. Для локальной демонстрации без внешних вызовов:
«Открыть пример» → «Проверочный · без модели» → «Создать план истории» →
«Собрать три варианта». Конвертеры должны быть установлены согласно [README](README.md).

Данные студии хранятся вне Git; локальная cookie связывает работы с браузером.
Это не многопользовательская система учётных записей. Ничьи существующие `.env`
не копировались в новое рабочее дерево, реальные ключи не добавлялись.

Порядок финальной защиты и внешней приёмки: [DEMO.md](DEMO.md).

## Финальные команды

| Рабочий каталог | Команда | Результат |
| --- | --- | --- |
| Корень нового рабочего дерева | `uv run --offline pytest --tb=short` | **1 230 passed**, 23.47 с; одно предупреждение Starlette об устаревающем test client |
| Корень | `uv run --offline ruff check .` | Все проверки пройдены |
| Корень | `uv lock --check` | Lock согласован, 109 пакетов |
| Корень | `git diff --check` | Ошибок пробелов/patch нет |
| Корень | `uv run --offline python scripts/test_services.py` | Parser **218**, content **89**, gateway **93** passed |
| `frontend/` | `npm test` | **24 passed** |
| `frontend/` | `npm run typecheck` | Успешно |
| `frontend/` | `npm run build` | Успешно; bundled assets обновлены |

Точная финальная команда benchmark из корня:

```bash
UV_CACHE_DIR=/tmp/exposlides-audit-uv-cache uv run --no-sync python -m scripts.benchmark_designer --output-dir /tmp/exposlides-designer-benchmark-20260927-accepted-final
```

Код завершения 0; полный JSON-отчёт и четыре manifest встроены в VALIDATION.

Service suites дополнительно выдавали предупреждения старых тестов о невыжданной
корутине `serve` и cookie API HTTPX. Падений нет; предупреждения не скрывались.
CI добавлен, но прогон GitHub Actions не запускался и не заявляется выполненным.

Дополнительные новые проверки охватывают переполнение карточек/подписи графика,
происхождение ответа модели без ключей и URL, конкурирующие запросы последнего места
в очереди, отмену ожидающей сборки/исправления и сохранность предыдущей версии.

## Полный список изменённых и новых файлов

Пути относительно этого рабочего дерева; 180 файлов.

```text
.env.example
.github/workflows/checks.yml
.gitignore
ARCHITECTURE.md
AUDIT.md
DEMO.md
IMPLEMENTATION_STATUS.md
MODELS.md
README.md
VALIDATION_2026-09-27.md
VK_TECH_AUDIT_2026-09-27.md
agents/designer.toml
config/models.toml
config/run.example.toml
config/skills.toml
docker-compose.yaml
evals/README.md
evals/generation_cases.json
evals/score.py
exposlides/design_audit.py
exposlides/design_builder.py
exposlides/design_cli.py
exposlides/design_content.py
exposlides/design_export.py
exposlides/design_geometry.py
exposlides/design_layout.py
exposlides/design_models.py
exposlides/design_pipeline.py
exposlides/design_pptx_parts.py
exposlides/design_saved_audit.py
exposlides/design_smartart.py
exposlides/preview.py
exposlides/run_config.py
exposlides/studio.py
exposlides/studio_static/app.css
exposlides/studio_static/app.js
exposlides/studio_static/index.html
exposlides/template_profile.py
exposlides/web.py
frontend/README.md
frontend/build.mjs
frontend/index.html
frontend/package-lock.json
frontend/package.json
frontend/src/App.tsx
frontend/src/api.ts
frontend/src/components.tsx
frontend/src/jobs.ts
frontend/src/main.tsx
frontend/src/model.ts
frontend/src/styles.css
frontend/src/types.ts
frontend/test.mjs
frontend/tests/studio.test.tsx
frontend/tsconfig.json
prompts/designer/audit.md
prompts/designer/image.md
prompts/designer/story.md
pyproject.toml
scripts/README.md
scripts/benchmark_designer.py
scripts/test_services.py
services/builder-service/app/network.py
services/content-service/app/config.py
services/content-service/app/design_audit.py
services/content-service/app/design_capabilities.py
services/content-service/app/design_config.py
services/content-service/app/design_image.py
services/content-service/app/design_main.py
services/content-service/app/grpc/file_service_client.py
services/content-service/app/kafka/consumer.py
services/content-service/app/kafka/producer.py
services/content-service/app/utils/fact_grounding.py
services/content-service/app/utils/validation.py
services/content-service/tests/integration/conftest.py
services/content-service/tests/integration/helpers.py
services/content-service/tests/integration/test_pipeline_with_file_service.py
services/content-service/tests/test_config.py
services/content-service/tests/test_consumer.py
services/content-service/tests/test_content_pipeline.py
services/content-service/tests/test_domain_generate.py
services/content-service/tests/test_file_service_client.py
services/content-service/tests/test_grpc_server.py
services/content-service/tests/test_messages.py
services/content-service/tests/test_producer.py
services/file-service/app/config.py
services/file-service/app/database.py
services/file-service/app/models/__init__.py
services/file-service/app/models/file.py
services/file-service/app/service.py
services/file-service/app/validators.py
services/file-service/tests/test_file_service.py
services/gateway-service/README.md
services/gateway-service/app/config.py
services/gateway-service/app/database.py
services/gateway-service/app/main.py
services/gateway-service/app/repositories/files.py
services/gateway-service/app/repositories/sessions.py
services/gateway-service/app/repositories/tasks.py
services/gateway-service/app/router/files.py
services/gateway-service/app/router/session.py
services/gateway-service/app/router/tasks.py
services/gateway-service/app/router/ws.py
services/gateway-service/app/schemas/task.py
services/gateway-service/app/services/file_client.py
services/gateway-service/app/services/kafka_consumer.py
services/gateway-service/app/services/kafka_producer.py
services/gateway-service/app/services/sio_server.py
services/gateway-service/app/services/task_service.py
services/gateway-service/app/services/ws_hub.py
services/gateway-service/app/utils/cookies.py
services/gateway-service/pytest.ini
services/gateway-service/tests/conftest.py
services/gateway-service/tests/unit/test_config.py
services/gateway-service/tests/unit/test_cookies.py
services/gateway-service/tests/unit/test_event_reliability.py
services/gateway-service/tests/unit/test_file_client.py
services/gateway-service/tests/unit/test_file_ownership.py
services/gateway-service/tests/unit/test_kafka_producer.py
services/gateway-service/tests/unit/test_router_files.py
services/gateway-service/tests/unit/test_router_tasks.py
services/gateway-service/tests/unit/test_schemas.py
services/gateway-service/tests/unit/test_task_service.py
services/gateway-service/tests/unit/test_ws_hub.py
services/parsing-service/README.md
services/parsing-service/app/grpc/file_service_client.py
services/parsing-service/app/grpc/server.py
services/parsing-service/app/kafka/consumer.py
services/parsing-service/app/kafka/producer.py
services/parsing-service/app/models/presentation.py
services/parsing-service/app/parsers/pptx/charts.py
services/parsing-service/app/parsers/pptx/geometry.py
services/parsing-service/app/parsers/pptx/parser.py
services/parsing-service/app/parsers/pptx/shapes.py
services/parsing-service/app/parsers/pptx/smartart.py
services/parsing-service/app/parsers/pptx/tables.py
services/parsing-service/app/parsers/pptx/text.py
services/parsing-service/app/parsers/pptx/tokens.py
services/parsing-service/app/parsers/text_style.py
services/parsing-service/app/services/parser_pipeline.py
services/parsing-service/tests/conftest.py
services/parsing-service/tests/e2e/conftest.py
services/parsing-service/tests/e2e/helpers.py
services/parsing-service/tests/e2e/test_parser_service_e2e.py
services/parsing-service/tests/integration/conftest.py
services/parsing-service/tests/integration/helpers.py
services/parsing-service/tests/integration/test_pipeline_with_file_service.py
services/parsing-service/tests/test_consumer.py
services/parsing-service/tests/test_file_service_client.py
services/parsing-service/tests/test_grpc_server.py
services/parsing-service/tests/test_main.py
services/parsing-service/tests/test_pipeline.py
services/parsing-service/tests/test_pptx_assets.py
services/parsing-service/tests/test_pptx_charts.py
services/parsing-service/tests/test_pptx_parser.py
services/parsing-service/tests/test_pptx_shapes.py
services/parsing-service/tests/test_pptx_smartart.py
services/parsing-service/tests/test_pptx_tables.py
services/parsing-service/tests/test_pptx_template_geometry.py
services/parsing-service/tests/test_pptx_text.py
services/parsing-service/tests/test_pptx_tokens.py
services/parsing-service/tests/test_producer.py
services/parsing-service/tests/test_schemas.py
tests/test_builder_network.py
tests/test_design_agent_config.py
tests/test_design_benchmark.py
tests/test_design_builder.py
tests/test_design_capabilities.py
tests/test_design_contextual_audit.py
tests/test_design_export.py
tests/test_design_generation.py
tests/test_design_image.py
tests/test_design_integration.py
tests/test_design_queue.py
tests/test_design_run_config.py
tests/test_design_smartart.py
tests/test_design_workflow.py
tests/test_generation_evals.py
tests/test_semantic_fact_grounding.py
tests/test_template_design.py
```
