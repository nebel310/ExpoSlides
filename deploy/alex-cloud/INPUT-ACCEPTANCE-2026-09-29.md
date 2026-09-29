# Исправление приёма шаблонов и проверки плана — 29 сентября 2026

Опубликованный релиз: `20260929-input-acceptance-03`.
Основа и откат: `20260929-text-density-01`.
Публикация подтверждена: внутренний HTTP 200; внешняя защита HTTPS возвращает 401
без входа. После перезапуска живой API принял оба синтетических PPTX с HTTP 201.

## Причины и исправления

- Проверка отрицаний ошибочно противопоставляла «не представлять собой одну растровую
  картинку» и «а не растровая картинка». Теперь она учитывает связку и определители
  между отрицанием и именной частью. Настоящие изменения отрицания, чисел и фактов
  по-прежнему отклоняются.
- При отсутствии видимого тезиса компактное восстановление меняло только notes,
  поэтому не могло исправить план. Теперь этот случай направляется в частичную
  замену слайда; корректные соседние слайды сохраняются. Notes дополняются только
  при уже видимом тезисе и обязательных сообщениях.
- Native builder безусловно отклонял custom shows/sections. Теперь загрузка допускает
  такой PPTX, а новый результат очищается от исходных списков показов, разделов и
  переходов к удалённым показам. Настройка показа переключается на все новые слайды.
  Оригинал, стили, обычные ссылки и посторонние расширения сохраняются.
- Неизвестная дополнительная ссылка презентации на исходный слайд теперь обнаруживается
  до освобождения его rId: она не сможет незаметно начать указывать на новую копию.
  Старый builder-service не менялся.

## Изменённые файлы

- `exposlides/design_pptx_parts.py`
- `exposlides/template_compat.py` — локальное снятие дополнительного upload guard;
  действующая серверная версия уже принимала такую загрузку.
- `services/content-service/app/design_main.py`
- `services/content-service/app/utils/fact_grounding.py`
- `tests/test_design_presentation_metadata.py`
- `tests/test_template_compat.py`
- `tests/test_design_builder.py` — только прежний тест отказа.
- `tests/test_fact_grounding_nominal_negation.py`
- `tests/test_story_repair_selection.py`
- `README.md`, `evals/README.md`, этот отчёт и ссылка в deployment README.

В серверном `tests/test_design_generation.py` подменный ответ старого теста изменён
с EditorialRepairs на ContentPlan для случая отсутствующего видимого тезиса.
Локально эквивалентная правка уже присутствовала от другой работы и сохранена.

## Проверки

- Исходный локальный `uv run pytest`: **1599 passed**, 8 прежних предупреждений.
- Исходный локальный `uv run ruff check .`: passed.
- После исправлений локальный `uv run pytest`: **1636 passed**, 8 прежних предупреждений.
- После исправлений `uv run ruff check .`: passed.
- `uv run pytest tests/test_fact_grounding_nominal_negation.py tests/test_semantic_fact_grounding.py tests/test_generation_evals.py tests/test_design_source_audit.py tests/test_polarity_context.py tests/test_story_repair_selection.py`: **84 passed**.
- `uv run pytest tests/test_design_presentation_metadata.py tests/test_template_compat.py tests/test_design_builder.py`: **42 passed**.
- `uv run pytest tests/test_story_repair_selection.py tests/test_design_generation.py tests/test_design_concise_story.py tests/test_story_overflow_regression.py -q`: **51 passed**.
- `uv run python evals/score.py quarterly-results /tmp/exposlides-accept-input-20260929/grounded-eval.json`: **100/100**, все обязательные факты сохранены, semantic_issues пуст.
  Ответ для этого sanity-check извлечён из исходника фиксированного сценария, без LLM;
  это не оценка качества живой генерации.
- Исходный серверный релиз navigation-reset: `uv run --no-sync --offline pytest` —
  **1496 passed**; `uv run --no-sync --offline ruff check .` — passed.
- Кандидат поверх line-wrapping-02: **1536 passed**, полный Ruff passed после удаления
  лишней пустой строки в импортах. Повторный целевой набор: **54 passed**.
- Окончательный кандидат: `uv run --no-sync --offline pytest` — **1553 passed**,
  1 прежнее предупреждение; `uv run --no-sync --offline ruff check .` — passed.

Разница в количестве тестов обусловлена существовавшими локальными изменениями и
параллельными обновлениями проекта. В публикацию перенесены только целевые патчи;
обновления переносов и плотности текста сохранены. Первый прогон сервера выявил
устаревший fake-ответ теста и затем порядок импортов при переносе; оба исправлены.

На сервере синтетические шаблоны с заполненными custom shows, sections и диапазоном
показа собраны в порядок 3, 1, 3. Обе колоды повторно открыты, оригиналы побайтово
сохранены; LibreOffice/Poppler создали по три PNG, PDF и HTML.
Артефакты: `/home/alex/exposlides/shared/verification/input-acceptance-20260929`.

## Ограничения проверки

Реальные LLM-запросы не выполнялись. Исторические неудачные задания не переписывались
и не перезапускались. Автоматическая проверка доступа отклонила чтение исходного
содержимого одного приватного задания с неполным раскрытием source-7; причина
восстановления воспроизведена на искусственном примере. Полный повтор этого задания
не заявляется. Поддержка произвольных повреждённых PPTX не обещается.

## Публикация и откат

Кандидат создан поверх текущего релиза, настройки провайдеров и shared/studio
не заменяются. Перед переключением проверены активный релиз и отсутствие
незавершённых генераций: 0. Служба перезапущена, проверка доступности пройдена. Предыдущая версия записана в `.previous-release` кандидата.
При ошибке проверки доступности ссылка current возвращается на предыдущую версию.

Зависимости `.venv` и `frontend/node_modules` остаются существующими серверными
ссылками; их базовые каталоги удалять нельзя. Commit/push не выполнялись.

Для ручного отката (после проверки отсутствия выполняющихся генераций):

```bash
previous_release=/home/alex/exposlides/releases/20260929-text-density-01
test -x "$previous_release/.venv/bin/python" || exit 1
ln -s "$previous_release" /home/alex/exposlides/current-rollback-input
mv -Tf /home/alex/exposlides/current-rollback-input /home/alex/exposlides/current
sudo systemctl restart exposlides
```

Серверные настройки, секреты и исторические задания не изменялись. Два синтетических
upload-проверочных шаблона созданы в отдельной сессии; пользовательской истории они
не добавляют заданий. Обновление страницы и новая генерация используют исправление.
