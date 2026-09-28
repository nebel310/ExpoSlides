# Перенос нового workflow в dev — 29 сентября 2026

Перенесена версия `codex/vk-tech-completion` на коммите `2b3cc74` вместе с
незакоммиченными исходниками её рабочей копии. Исходная рабочая копия сохранена
без изменений. Ветки имеют независимые корни; итоговый merge сохраняет обе истории.
До переноса исходники текущей dev сохранены коммитом `18a0ba8`.

Перенесены новый дизайнер, React/TypeScript-студия и её сборка, parser v2,
сетевые сервисы, роли `agents/designer.toml`, навыки `config/skills.toml`, внешние
промпты, manifest, документация и тесты. Сохранены более новые изображения
Z-Image-Turbo и прежний CLI/web из dev. Добавлена совместимость их палитры с
Presentation JSON v2 и проверка обоих форматов с повторным открытием PPTX.
Описание прежнего развёртывания сохранено в `deploy/alex-cloud/LEGACY-WEB.md`.

Секреты, существующие `.env`, локальные презентации, кэши и результаты генерации
не переносились и не добавлялись в коммиты. Не выполнялись push, деплой или
живые вызовы LLM/image API. Каталоги локальных артефактов оставлены на месте.

## Проверки

Исходная dev: 1043 теста прошли, Ruff — 45 ошибок.
Исходная рабочая копия нового workflow: 1370 тестов прошли, Ruff прошёл.
Для обеих исходных копий использовались `uv run --no-sync --offline pytest
-p no:cacheprovider` и `uv run --no-sync --offline ruff check --no-cache .`.

Проверки объединённой dev:

| Команда | Результат |
| --- | --- |
| `uv sync --locked --offline` | Успешно, окружение синхронизировано с перенесённым lock-файлом |
| `uv lock --check --offline` | Успешно, 109 пакетов |
| `uv run --no-sync --offline pytest -p no:cacheprovider` | 1412 passed |
| `uv run --no-sync --offline ruff check --no-cache .` | All checks passed |
| `uv run --no-sync --offline python scripts/test_services.py` | parser: 218 passed; content: 89 passed; gateway: 93 passed |
| `npm ci --offline --ignore-scripts --no-audit --no-fund` (frontend) | Успешно |
| `npm test` (frontend) | 31 passed |
| `npm run build` (frontend) | TypeScript и production-сборка прошли |

До полного запуска целевые проверки прошли: 266 passed.

```bash
uv run --no-sync --offline pytest -p no:cacheprovider tests/test_design_agent_config.py tests/test_design_generation.py tests/test_design_contextual_audit.py tests/test_design_integration.py tests/test_pptx_parser.py tests/test_pptx_builder.py tests/test_cli.py tests/test_end_to_end.py tests/test_images.py tests/test_web.py tests/test_generation_pipeline.py tests/test_generation_evals.py
```

Scorer запущен на синтетическом результате из 15 исходных разделов кейса
`fast-product-review-15`: score 100, fact_recall 1, message_recall 1. Это проверка
scorer, не измерение качества модели. Временный fixture находится вне репозитория:

```bash
uv run --no-sync --offline python evals/score.py fast-product-review-15 /var/folders/tt/8vx04p8j1vz6j2dfb2g5bh6c0000gn/T/exposlides-dev-integration-t0eo6e0b/eval-source-preservation.json
```

Остались предупреждения зависимостей Starlette/httpx и forkpty, а также предупреждение
`coroutine serve was never awaited` в service-level тестах content. Ошибок тестов нет.
Проверки file-service с живой инфраструктурой не запускались. Офлайн-тесты создания
и повторного открытия PPTX прошли; визуальный аудит реального LLM-прогона не выполнялся.

## Файлы merge-коммита

Список относительно корня проекта; предшествующая локальная работа отдельно
зафиксирована в `18a0ba8`.

- `.env.example`
- `.github/workflows/checks.yml`
- `.gitignore`
- `ARCHITECTURE.md`
- `AUDIT.md`
- `DEMO.md`
- `GENERATION_RECOVERY.md`
- `IMPLEMENTATION_STATUS.md`
- `MODELS.md`
- `README.md`
- `VALIDATION_2026-09-27.md`
- `agents/designer.toml`
- `config/models.toml`
- `config/run.example.toml`
- `config/skills.toml`
- `deploy/alex-cloud/LEGACY-WEB.md`
- `deploy/alex-cloud/README.md`
- `deploy/alex-cloud/STUDIO-DEPLOY-2026-09-28.md`
- `deploy/alex-cloud/TEMPLATE-RECOVERY-2026-09-28.md`
- `deploy/alex-cloud/run-local-studio.py`
- `docker-compose.yaml`
- `evals/README.md`
- `evals/generation_cases.json`
- `evals/score.py`
- `exposlides/cli.py`
- `exposlides/design_audit.py`
- `exposlides/design_builder.py`
- `exposlides/design_cli.py`
- `exposlides/design_content.py`
- `exposlides/design_export.py`
- `exposlides/design_geometry.py`
- `exposlides/design_layout.py`
- `exposlides/design_models.py`
- `exposlides/design_native_text.py`
- `exposlides/design_pipeline.py`
- `exposlides/design_pptx_parts.py`
- `exposlides/design_saved_audit.py`
- `exposlides/design_smartart.py`
- `exposlides/images.py`
- `exposlides/preview.py`
- `exposlides/run_config.py`
- `exposlides/studio.py`
- `exposlides/studio_static/app.css`
- `exposlides/studio_static/app.js`
- `exposlides/studio_static/index.html`
- `exposlides/template_layout.py`
- `exposlides/template_profile.py`
- `exposlides/web.py`
- `frontend/DESIGN_UPDATE.md`
- `frontend/README.md`
- `frontend/build.mjs`
- `frontend/index.html`
- `frontend/package-lock.json`
- `frontend/package.json`
- `frontend/src/App.tsx`
- `frontend/src/ResultViewer.tsx`
- `frontend/src/api.ts`
- `frontend/src/components.tsx`
- `frontend/src/jobs.ts`
- `frontend/src/main.tsx`
- `frontend/src/model.ts`
- `frontend/src/styles.css`
- `frontend/src/types.ts`
- `frontend/test.mjs`
- `frontend/tests/studio.test.tsx`
- `frontend/tsconfig.json`
- `prompts/designer/audit.md`
- `prompts/designer/image.md`
- `prompts/designer/story.md`
- `pyproject.toml`
- `scripts/README.md`
- `scripts/benchmark_designer.py`
- `scripts/test_services.py`
- `services/builder-service/Dockerfile`
- `services/builder-service/README.md`
- `services/builder-service/app/file_client.py`
- `services/builder-service/app/models/presentation.py`
- `services/builder-service/app/network.py`
- `services/content-service/README.md`
- `services/content-service/app/config.py`
- `services/content-service/app/design_audit.py`
- `services/content-service/app/design_capabilities.py`
- `services/content-service/app/design_config.py`
- `services/content-service/app/design_image.py`
- `services/content-service/app/design_main.py`
- `services/content-service/app/domain/contract.py`
- `services/content-service/app/domain/generate.py`
- `services/content-service/app/errors.py`
- `services/content-service/app/graph/fast.py`
- `services/content-service/app/graph/nodes.py`
- `services/content-service/app/grpc/file_service_client.py`
- `services/content-service/app/kafka/consumer.py`
- `services/content-service/app/kafka/producer.py`
- `services/content-service/app/models/graph_state.py`
- `services/content-service/app/services/content_pipeline.py`
- `services/content-service/app/utils/fact_grounding.py`
- `services/content-service/app/utils/presentation_parser.py`
- `services/content-service/app/utils/validation.py`
- `services/content-service/tests/integration/conftest.py`
- `services/content-service/tests/integration/helpers.py`
- `services/content-service/tests/integration/test_pipeline_with_file_service.py`
- `services/content-service/tests/test_config.py`
- `services/content-service/tests/test_consumer.py`
- `services/content-service/tests/test_content_pipeline.py`
- `services/content-service/tests/test_domain_generate.py`
- `services/content-service/tests/test_file_service_client.py`
- `services/content-service/tests/test_grpc_server.py`
- `services/content-service/tests/test_messages.py`
- `services/content-service/tests/test_producer.py`
- `services/file-service/README.md`
- `services/file-service/app/config.py`
- `services/file-service/app/database.py`
- `services/file-service/app/models/__init__.py`
- `services/file-service/app/models/file.py`
- `services/file-service/app/service.py`
- `services/file-service/app/validators.py`
- `services/file-service/tests/test_file_service.py`
- `services/gateway-service/Dockerfile`
- `services/gateway-service/README.md`
- `services/gateway-service/app/config.py`
- `services/gateway-service/app/database.py`
- `services/gateway-service/app/errors.py`
- `services/gateway-service/app/main.py`
- `services/gateway-service/app/repositories/files.py`
- `services/gateway-service/app/repositories/sessions.py`
- `services/gateway-service/app/repositories/tasks.py`
- `services/gateway-service/app/router/files.py`
- `services/gateway-service/app/router/session.py`
- `services/gateway-service/app/router/tasks.py`
- `services/gateway-service/app/router/ws.py`
- `services/gateway-service/app/schemas/base.py`
- `services/gateway-service/app/schemas/events.py`
- `services/gateway-service/app/schemas/files.py`
- `services/gateway-service/app/schemas/session.py`
- `services/gateway-service/app/schemas/task.py`
- `services/gateway-service/app/services/file_client.py`
- `services/gateway-service/app/services/kafka_consumer.py`
- `services/gateway-service/app/services/kafka_producer.py`
- `services/gateway-service/app/services/sio_server.py`
- `services/gateway-service/app/services/task_service.py`
- `services/gateway-service/app/services/ws_hub.py`
- `services/gateway-service/app/utils/cookies.py`
- `services/gateway-service/conftest.py`
- `services/gateway-service/pytest.ini`
- `services/gateway-service/tests/conftest.py`
- `services/gateway-service/tests/unit/test_config.py`
- `services/gateway-service/tests/unit/test_cookies.py`
- `services/gateway-service/tests/unit/test_errors.py`
- `services/gateway-service/tests/unit/test_event_reliability.py`
- `services/gateway-service/tests/unit/test_file_client.py`
- `services/gateway-service/tests/unit/test_file_ownership.py`
- `services/gateway-service/tests/unit/test_kafka_consumer.py`
- `services/gateway-service/tests/unit/test_kafka_producer.py`
- `services/gateway-service/tests/unit/test_router_files.py`
- `services/gateway-service/tests/unit/test_router_session.py`
- `services/gateway-service/tests/unit/test_router_tasks.py`
- `services/gateway-service/tests/unit/test_schemas.py`
- `services/gateway-service/tests/unit/test_sessions_repository.py`
- `services/gateway-service/tests/unit/test_task_service.py`
- `services/gateway-service/tests/unit/test_tasks_repository.py`
- `services/gateway-service/tests/unit/test_ws_hub.py`
- `services/parsing-service/README.md`
- `services/parsing-service/app/grpc/file_service_client.py`
- `services/parsing-service/app/grpc/server.py`
- `services/parsing-service/app/kafka/consumer.py`
- `services/parsing-service/app/kafka/producer.py`
- `services/parsing-service/app/main.py`
- `services/parsing-service/app/models/legacy_presentation.py`
- `services/parsing-service/app/models/presentation.py`
- `services/parsing-service/app/parsers/pptx/__init__.py`
- `services/parsing-service/app/parsers/pptx/assets.py`
- `services/parsing-service/app/parsers/pptx/charts.py`
- `services/parsing-service/app/parsers/pptx/geometry.py`
- `services/parsing-service/app/parsers/pptx/helpers.py`
- `services/parsing-service/app/parsers/pptx/parser.py`
- `services/parsing-service/app/parsers/pptx/shapes.py`
- `services/parsing-service/app/parsers/pptx/smartart.py`
- `services/parsing-service/app/parsers/pptx/tables.py`
- `services/parsing-service/app/parsers/pptx/text.py`
- `services/parsing-service/app/parsers/pptx/tokens.py`
- `services/parsing-service/app/parsers/pptx_parser.py`
- `services/parsing-service/app/parsers/text_style.py`
- `services/parsing-service/app/services/parser_pipeline.py`
- `services/parsing-service/tests/conftest.py`
- `services/parsing-service/tests/e2e/conftest.py`
- `services/parsing-service/tests/e2e/helpers.py`
- `services/parsing-service/tests/e2e/test_parser_service_e2e.py`
- `services/parsing-service/tests/integration/conftest.py`
- `services/parsing-service/tests/integration/helpers.py`
- `services/parsing-service/tests/integration/test_pipeline_with_file_service.py`
- `services/parsing-service/tests/test_consumer.py`
- `services/parsing-service/tests/test_file_service_client.py`
- `services/parsing-service/tests/test_grpc_server.py`
- `services/parsing-service/tests/test_main.py`
- `services/parsing-service/tests/test_pipeline.py`
- `services/parsing-service/tests/test_pptx_assets.py`
- `services/parsing-service/tests/test_pptx_charts.py`
- `services/parsing-service/tests/test_pptx_parser.py`
- `services/parsing-service/tests/test_pptx_shapes.py`
- `services/parsing-service/tests/test_pptx_smartart.py`
- `services/parsing-service/tests/test_pptx_tables.py`
- `services/parsing-service/tests/test_pptx_template_geometry.py`
- `services/parsing-service/tests/test_pptx_text.py`
- `services/parsing-service/tests/test_pptx_tokens.py`
- `services/parsing-service/tests/test_producer.py`
- `services/parsing-service/tests/test_schemas.py`
- `tests/conftest.py`
- `tests/test_builder_network.py`
- `tests/test_builder_schema_compatibility.py`
- `tests/test_content_feedback.py`
- `tests/test_content_service_main.py`
- `tests/test_design_agent_config.py`
- `tests/test_design_benchmark.py`
- `tests/test_design_builder.py`
- `tests/test_design_capabilities.py`
- `tests/test_design_contextual_audit.py`
- `tests/test_design_export.py`
- `tests/test_design_generation.py`
- `tests/test_design_image.py`
- `tests/test_design_integration.py`
- `tests/test_design_native_text.py`
- `tests/test_design_queue.py`
- `tests/test_design_run_config.py`
- `tests/test_design_smartart.py`
- `tests/test_design_source_audit.py`
- `tests/test_design_workflow.py`
- `tests/test_end_to_end.py`
- `tests/test_fast_generation.py`
- `tests/test_generation_evals.py`
- `tests/test_generation_pipeline.py`
- `tests/test_images.py`
- `tests/test_local_studio_launcher.py`
- `tests/test_polarity_context.py`
- `tests/test_pptx_parser_v2.py`
- `tests/test_presentation_schema_compatibility.py`
- `tests/test_preview_fonts.py`
- `tests/test_semantic_fact_grounding.py`
- `tests/test_studio_generate.py`
- `tests/test_studio_model_errors.py`
- `tests/test_template_design.py`
- `tests/test_template_layout.py`
- `tests/test_template_profile_fidelity.py`
- `uv.lock`
- `INTEGRATION_DEV_2026-09-29.md`
