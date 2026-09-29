> Отменено после сверки с исходным ТЗ: пункт 5 требует три визуально различимых варианта одного шаблона и контента. Режим одного результата нарушал это требование. Исправление переполнения сохранено.

# Одна презентация по шаблону — 29 сентября 2026

Релиз: `20260929-single-template-01`. Предыдущий: `20260929-text-overflow-01`.

Прежняя студия всегда публиковала три варианта. При сохранении одинаковых исходных
областей шаблона это давало три почти одинаковых результата. Теперь Studio выбирает
и публикует только `story` под именем «По шаблону»; иллюстрации запрашиваются только
для его выбранных областей. Вместимость проверяется для того же результата.
Низкоуровневый create_variants сохраняет прежний режим для benchmark и старых вызовов.

Интерфейс с одним результатом не предлагает сравнивать оформление. Кнопка сборки
называется «Собрать презентацию», статусы не обещают три результата. Исторические
задания с разными вариантами продолжают открываться. В последнем задании
`057cc584cea54ef7bc36ad9e56f67f4f` оставлена одна ссылка на story revision 2;
PPTX и исходный шаблон не менялись. Файлы всех прежних вариантов и ревизий сохранены.

Изменённые файлы: exposlides/design_layout.py, design_pipeline.py, docstring studio.py;
frontend/src/ResultViewer.tsx, components.tsx, jobs.ts; собранные studio_static/app.js,
app.css, index.html; tests/test_single_template_result.py, test_design_integration.py;
frontend/tests/studio.test.tsx, upload-form.test.tsx; README, frontend/README, evals/README.

## Проверки

- Baseline: `uv run --offline pytest -o addopts='' -q` — 1521 passed;
  `uv run --offline ruff check .` — успешно.
- `uv run --offline pytest tests/test_single_template_result.py tests/test_design_images_batch.py tests/test_design_workflow.py tests/test_story_overflow_regression.py -o addopts='' -q` — 34 passed.
- Финально `uv run --offline pytest -o addopts='' -q` — 1525 passed, 8 прежних предупреждений;
  `uv run --offline ruff check .` — успешно.
- `npm --prefix frontend test` — 51 passed; `npm --prefix frontend run build` — успешно.
  Тот же набор из 51 теста и сборка прошли на копии точных серверных исходников.
- Сервер: `uv run --no-sync --offline pytest -o addopts='' -q --basetemp=/tmp/exposlides-single-template-tests`
  — 1492 passed, 1 предупреждение; `uv run --no-sync --offline ruff check .` — успешно.

Новая регрессия строит настоящий PPTX, повторно открывает его, проверяет исходную
геометрию и saved audit; вызывается ровно одна публикация. Существующая интеграционная
проверка parser → fake LLM → builder → exports также подтверждает один результат.
Реальных LLM/image API-вызовов не выполнялось.

## Публикация и откат

Публикация точечным патчем к активному серверному снимку; посторонние локальные
изменения не переносились. Активных заданий перед переключением не было.
Резервные job.json/variants.json: `shared/deploy-backups/20260929-single-template-01`.
Предыдущий релиз записан в `SINGLE_TEMPLATE_PREVIOUS_RELEASE`.

Подтверждены через HTTP единственный результат, PPTX/PDF/HTML по байтам, 12 превью,
доступность PPTX revisions 1/2 всех трёх прежних вариантов и повторное открытие PPTX.
Исходная геометрия опубликованного PPTX сверена с новым одиночным планом.
Сборка UI с версионированным URL побайтно совпадает с опубликованной.

Для отката при отсутствии активных заданий остановить exposlides, вернуть current
на `/home/alex/exposlides/releases/20260929-text-overflow-01`, восстановить два файла
метаданных из резервной копии и запустить службу. Секреты и исходные загрузки не менялись.
