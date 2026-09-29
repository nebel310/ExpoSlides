# Упрощённая загрузка данных

Опубликовано 29 сентября 2026 поверх 20260929-palette-game-01.
CSV/TSV добавляются сразу, доступен выбор нескольких файлов. Название и источник
берутся из имени файла; единицы не запрашиваются и могут быть указаны в заголовках.
Убран максимум строк в CSV, JSON-импорте и общей серверной модели Dataset.
Предпросмотр содержит первые 30 строк, запрос — весь набор.
Сохраняются ограничения 400 КБ на файл, 20 таблиц, 20 столбцов.

Изменены frontend/src/DatasetInput.tsx, frontend/src/model.ts,
frontend/tests/datasets.test.tsx, frontend/tests/studio.test.tsx,
exposlides/design_models.py, tests/test_dataset_row_count.py, README.md, frontend/README.md,
exposlides/studio_static/app.js и index.html.
При публикации также передан неизменившийся app.css.
На сервере в design_models.py применена только точечная замена лимита, чтобы сохранить
остальной код текущего релиза.

Проверки:
- baseline uv run pytest — 1490 passed; Ruff и 49 тестов интерфейса прошли.
- npm --prefix frontend test — 49 passed; интеграционный тест формы загружает несколько
  файлов и проверяет передачу 1001 строки без обрезки.
- npm --prefix frontend run build — успешно, включая TypeScript.
- uv run pytest tests/test_dataset_row_count.py tests/test_design_builder.py tests/test_design_workflow.py — 44 passed.
- uv run pytest — 1494 passed, 8 предупреждений зависимостей.
- uv run ruff check . — All checks passed.
- uv lock --check — успешно, 109 пакетов.
- Сервер: .venv/bin/python -m pytest tests/test_dataset_row_count.py -q — 4 passed.
- Публичные HTML/JS/CSS — HTTP 200, байты совпадают с релизом.
- OpenAPI работающей службы: Dataset.rows не содержит maxItems.

Перед перезапуском активных генераций не было. История и секреты не изменялись.
Резервная копия: /home/alex/exposlides/shared/deploy-backups/20260929-simple-data-01.
Откат: при отсутствии активных генераций восстановить файлы previous согласно
manifest.json и перезапустить exposlides; сначала проверить последующие изменения.
Реальные LLM-вызовы не запускались.
