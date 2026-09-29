# Выдача презентации после неудачных исправлений — 29 сентября 2026

Релиз: `20260929-story-fallback-01`. Предыдущая версия: `20260929-tz-audit-02`.

Последнее задание отклонялось из-за неподтверждённых чисел. После исчерпания
трёх попыток студия теперь собирает доступный структурно корректный план.
Проверки фактов, полноты, числа слайдов и размещения сохраняются; их замечания
публикуются в аудите каждого варианта и включают видимое предупреждение в UI.
Неизвестные ссылки на источники/таблицы и отсутствие корректного плана остаются
ошибками. Локальный extractive-режим остаётся строгим.

При восстановлении выявлены и исправлены ещё две ошибки этого шаблона:
нетекстовый content-placeholder больше не считается текстовым слотом;
аудит штатного действия PowerPoint с пустым `r:id` не падает.

## Изменённые файлы

- `services/content-service/app/design_main.py`: сохранение доступного плана после retries.
- `exposlides/design_content.py`, `exposlides/design_pipeline.py`, `exposlides/studio.py`:
  разделение ошибок ссылок и замечаний качества, сохранение замечаний в аудите.
- `exposlides/template_profile.py`, `exposlides/design_saved_audit.py`: исправления шаблона.
- `frontend/src/ResultViewer.tsx`, `exposlides/studio_static/{app.js,app.css,index.html}`:
  предупреждение и пересобранный интерфейс.
- `tests/test_design_generation.py`, `tests/test_design_integration.py`,
  `tests/test_design_workflow.py`, `tests/test_studio_generate.py`,
  `tests/test_story_overflow_regression.py`, `tests/test_template_catalog.py`,
  `tests/test_template_layout.py`, `frontend/tests/studio.test.tsx`: регрессии.
- `README.md`, `deploy/alex-cloud/README.md`, этот отчёт.

На сервер переносилась только разница этой задачи с активным релизом; прочие
незакоммиченные локальные изменения не публиковались. Новые серверные Python-регрессии
собраны в `tests/test_story_fallback.py` с использованием существующих fixtures.

## Проверки

- Baseline: `uv run pytest -q` и `uv run ruff check .` — успешно.
- Финальный `uv run pytest -q` — успешно, 1654 теста.
- `uv run pytest -q tests/test_design_generation.py tests/test_design_integration.py tests/test_story_repair_selection.py` — успешно.
- `uv run pytest -q tests/test_design_workflow.py tests/test_studio_generate.py` — успешно.
- `uv run pytest -q tests/test_template_layout.py tests/test_pptx_parser.py tests/test_design_integration.py` — успешно.
- `uv run pytest -q tests/test_design_integration.py tests/test_pptx_builder.py` — успешно.
- `uv run ruff check` по всем изменённым Python-файлам — успешно.
- Повторный общий `uv run ruff check .` выявил 4 ошибки только в стороннем
  `artifacts/lct-presentation-20260929/.build/extract-icons.py`, появившемся во время работы.
  Этот файл не менялся и не публиковался.
- `cd frontend && npm test && npm run build` — успешно, 71 тест, TypeScript и сборка.
- Сервер: `uv run --no-sync pytest -q`, `uv run --no-sync ruff check .` — успешно.
- Восстановление последнего задания без LLM: три настоящих PPTX по 10 слайдов,
  экспорт и аудит выполнены; все три файла повторно открыты через python-pptx.

## Публикация и откат

Резервная копия задания `df0f10734dcd4d3281bfc93c04822789` и метаданных публикации:
`shared/deploy-backups/20260929-story-fallback-01`.
Перед переключением проверяются отсутствие активных заданий и неизменность `current`.
Секреты, настройки службы и остальные задания не изменяются.

Для отката при отсутствии активных заданий остановить службу, переключить `current`
на `/home/alex/exposlides/releases/20260929-tz-audit-02` и запустить службу.
Восстановленное задание можно оставить: контракт его результатов совместим.
Если требуется откат его метаданных, сначала убедиться, что пользователь не создал
новую версию, затем восстановить `job.json` и `profile.json` из резервной копии.
Новые файлы презентаций не удалять.


Публикация завершена: `current` указывает на `20260929-story-fallback-01`,
`exposlides` и `caddy` — active. Внутренний HTTP — 200; внешний HTTPS без
авторизации — ожидаемый 401. Хеш выдаваемого app.js совпадает с релизом.
Восстановленное задание имеет статус completed, три варианта по 10 слайдов;
все пути предпросмотра и экспорта существуют, в каждом варианте сохранены
замечания story_validation. Хеши остальных 33 job.json не изменились.
Серверный frontend: 71 тест, TypeScript и сборка — успешно.
