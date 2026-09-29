# Ошибка текстовой фигуры 7 — 29 сентября 2026

Подготовленный релиз: `20260929-text-shape-01`.
База и версия для отката: `20260929-story-fallback-01`.

Причина: старый profile.json записал p:pic с placeholder type=OBJECT как
текстовый слот. В сохранённом template.json уже стоит has_text_frame=false,
и текущий анализатор правильно исключает картинку. Повторная сборка раньше
продолжала пользоваться старым профилем. Теперь DesignPipeline.build пересчитывает
его до проверки истории и выбора макетов. Проверяется SHA-256 рабочего PPTX;
при несовпадении сборка останавливается без перезаписи профиля.

Изменения задачи: exposlides/design_pipeline.py, tests/test_stale_template_profile.py,
README.md, этот отчёт и ссылка в deploy/alex-cloud/README.md.
Остальные локальные изменения сохранены. На сервер переносится только точечная
вставка в pipeline, новый тест и документация поверх действующего релиза.

Проверки локально:

- `uv run pytest tests/test_stale_template_profile.py -q` — 2 passed.
- `uv run pytest tests/test_stale_template_profile.py tests/test_design_workflow.py tests/test_design_integration.py tests/test_pptx_builder.py tests/test_template_catalog.py -q` — успешно.
- `uv run pytest -q` — успешно до и после изменения.
- `uv run ruff check .` — одинаковые 4 baseline-ошибки в постороннем
  artifacts/lct-presentation-20260929/.build/extract-icons.py; файл не изменялся.
- `uv run ruff check exposlides/design_pipeline.py tests/test_stale_template_profile.py` — успешно.
- `git diff --check -- exposlides/design_pipeline.py tests/test_stale_template_profile.py` — успешно.

Сбойное задание 6b23b64773cf419a91d3fd9d729d9af7 воспроизведено без API-вызовов.
В изолированном /home/alex/exposlides/validation/text-shape-20260929-01
с сохранёнными текстом и иллюстрациями созданы три PPTX по 12 слайдов, PDF,
HTML и превью. Все PPTX повторно открыты; audit_saved_pptx.ok=True у всех трёх.
Это проверка повторной сборки, а не нового ответа LLM.

Для отката приложения после проверки текущей версии: атомарно вернуть current
на /home/alex/exposlides/releases/20260929-story-fallback-01 и перезапустить
exposlides. Каталог shared, ключи и прочие пользовательские задания не менять.

Серверные проверки из нового релиза:

- `uv run --no-sync --offline pytest -o addopts= -q -o tmp_path_retention_policy=failed --basetemp=/tmp/exposlides-text-shape-tests` — 1624 passed, 1 warning.
- `uv run --no-sync --offline ruff check .` — All checks passed.

Публикация: current переключён на `20260929-text-shape-01`, служба active,
внутренний HTTP `/` — 200. Сбойное задание восстановлено как completed с тремя
вариантами в прежней истории. Резервные метаданные и первоначальный пустой каталог
вариантов: `/home/alex/exposlides/shared/backups/text-shape-20260929-01`.
Текст, изображения, ключи и остальные задания не менялись.
