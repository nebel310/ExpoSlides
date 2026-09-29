# Повторы макетов и фотографий — 29 сентября 2026

Релиз: `20260929-repetition-01`. База/откат: `20260929-text-shape-01`.

Причины на задании 6b23b64773cf419a91d3fd9d729d9af7:

- Картинка p:pic внутри OBJECT-placeholder имела shape_type=PLACEHOLDER и
  не попадала в фотообласти; исходная иллюстрация оставалась на пяти слайдах.
- Один image_path копировался во все фотообласти слайда.
- Глобальная квота семейств макетов иногда предпочитала соседний повтор.

Исправления и файлы:

- `services/parsing-service/app/parsers/pptx/shapes.py` распознаёт p:pic независимо
  от placeholder type; используется существующая модель image, формат не меняется.
- `exposlides/design_native_image.py`, `exposlides/design_saved_audit.py` поддерживают
  замену и проверку таких фото с сохранением геометрии/маски.
- `exposlides/design_pipeline.py` повторно разбирает сохранённый шаблон, запрашивает
  отдельную иллюстрацию на каждую нужную фотообласть с отдельными seed и фокусом;
  сверяет пути, SHA, source_ids и пиксели. Лимит — 50 фотообластей на сборку.
- `exposlides/design_layout.py` принимает несколько картинок слайда и назначает
  разные файлы фотообластям. Старое одиночное назначение на несколько областей
  отклоняется понятной ошибкой, а не дублируется.
- `exposlides/design_repetition.py` проверяет содержательные фото в готовом PPTX
  (включая группы и layout). Логотипы/фон не сравниваются. Одинаковые пиксели при
  разных PNG-метаданных — повтор. Pipeline не публикует такую колоду.
- `exposlides/template_layout.py` предпочитает пригодного другого соседа до квот
  семейств. Проверки вместимости и читаемости заголовка сохранены.
- `tests/test_design_repetition.py` — 6 регрессий; `tests/test_design_integration.py`
  учитывает повторный локальный разбор. README.md и evals/README.md описывают поведение.

Проверки:

- `uv run pytest tests/test_design_repetition.py tests/test_pptx_parser.py tests/test_generation_evals.py -q` — успешно.
- `uv run pytest -o addopts= -q` — 1662 passed, 8 warnings.
- `uv run ruff check .` локально: baseline 4 ошибки в artifacts/.../extract-icons.py;
  к концу работы там также появился чужой merge-services.py, всего 31 ошибка.
  Эти артефакты не менялись и на сервер не переносились.
- Целевой `uv run ruff check` всех изменённых Python-файлов — успешно.
- `git diff --check` затронутых отслеживаемых файлов — успешно.
- На сервере `uv run --no-sync --offline pytest -o addopts= -q -o tmp_path_retention_policy=failed --basetemp=/tmp/exposlides-repetition-tests` — 1630 passed, 1 warning.
- На сервере `uv run --no-sync --offline ruff check .` — All checks passed.

Офлайн-сравнение на том же задании:
`/home/alex/exposlides/validation/repetition-20260929-01/comparison.json`.
Соседние повторы story/evidence/cards: 3/2/2 → 0/0/1; последний повтор между
первыми двумя слайдами, поскольку альтернативы хуже вмещают заголовок.
Повторы старых картинок: обнаружены 5/5/6. Фигура 7 теперь входит в фотообласти.
Старые экспорты и пользовательский текст сохранены. Новые картинки через API в
проверке не заказывались; отдельные фотообласти проверены с fake image API и
реальными PPTX. Проверка пикселей не гарантирует смыслового разнообразия сцен.

Серверный релиз создан копированием фактически активной версии и применением
только diff этой задачи. Секреты, серверные настройки и shared не изменяются.
Перед переключением проверяются отсутствие queued/running/cancelling заданий и
неизменность current. При неуспешном запуске — автоматический возврат предыдущей
ссылки и запуск прежней службы. Для ручного отката после проверки current
атомарно вернуть ссылку на /home/alex/exposlides/releases/20260929-text-shape-01
и выполнить `sudo systemctl restart exposlides`.

Публикация подтверждена: current → `20260929-repetition-01`, exposlides active.
HTTP `/` и `/api/session` — 200; внешний HTTPS без пароля — ожидаемый 401.
Все 91 файла метаданных job/profile/variants побайтно неизменны после перезапуска;
контрольные суммы сохранены в validation/repetition-20260929-01/metadata-before.json.
Исправление применяется к следующим сборкам; прежние экспорты не перезаписывались.
