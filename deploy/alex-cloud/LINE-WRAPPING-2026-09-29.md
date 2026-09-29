# Исправление переносов строк — 29 сентября 2026

Исправлены отступы продолжений обычных абзацев. В исходном шаблоне маркер списка
отключён (buNone), но сохранялся отрицательный indent. Теперь продолжения находятся
на вертикали первой строки. Настоящие маркированные и нумерованные списки, центрирование
и положительные абзацные отступы сохраняются; layout/master не изменяются.

Для новой генерации короткий заголовок по возможности помещается в одну строку:
используется разрешённое уменьшение кегля до 20%, затем приоритет подходящего широкого
макета. Если это невозможно, сохраняется допустимый перенос. Оценка ширины приблизительная.

Сохранённая презентация 057cc584cea54ef7bc36ad9e56f67f4f пересобрана в revision 4
для story/evidence/cards. Её исходные композиции, иллюстрации, тексты и notes сохранены.
В cards, слайд 9, кегль «Создание агента» изменён с 36 до 28.8 pt: одна строка
подтверждена просмотром итогового PNG. Старые revision 1/2/3 сохранены.

Изменённые файлы:
- exposlides/design_native_text.py — чтение наследования абзацев и выравнивание продолжений.
- exposlides/design_saved_audit.py — проверка разрешённого изменения отступа.
- exposlides/template_layout.py — приоритет одной строки короткого заголовка.
- tests/test_plain_text_wrapping.py — 11 регрессий, включая наследование и настоящие списки.
- tests/test_title_wrapping.py — 9 регрессий заголовков и повторное открытие PPTX.
- README.md — описание нового поведения.
- deploy/alex-cloud/LINE-WRAPPING-2026-09-29.md — этот отчёт.

Проверки:
- Baseline: uv run --offline pytest -o addopts='' -q — 1565 passed, 8 прежних warnings.
- uv run --offline pytest tests/test_plain_text_wrapping.py tests/test_design_native_text.py tests/test_pptx_builder.py -o addopts='' -q — 37 passed.
- uv run --no-sync pytest tests/test_title_wrapping.py tests/test_template_layout.py tests/test_native_compositions.py tests/test_template_design.py — 49 passed.
- uv run --offline pytest -o addopts='' -q — 1585 passed, 8 прежних warnings.
- uv run --offline ruff check . — All checks passed.
- git diff --check для затронутых файлов — успешно.
- Сервер: .venv/bin/python -m pytest -o addopts="" -q --basetemp=/home/alex/exposlides/shared/verification/line-wrap-tests — 1516 passed, 1 прежний warning.
- Сервер: .venv/bin/ruff check . — All checks passed.
- Созданы и повторно открыты три PPTX по 12 слайдов, экспортированы PDF/HTML и 36 PNG.
- Аудиты итоговых файлов без замечаний; просмотрены контактные листы всех 36 слайдов
  и проблемный слайд в полном размере. Попарные отличия вариантов: 11/11, 11/11, 9/11.
- После публикации через работающий API проверены все 9 экспортов и 36 PNG,
  побайтное совпадение с диском, revision 4, сохранность notes и предыдущих ревизий.

Серверный релиз: releases/20260929-line-wrapping-02.
Он подготовлен поверх актуального releases/20260929-navigation-reset-01, чтобы
сохранить параллельно опубликованное исправление навигации. Перенесена только разница
данной задачи, а не всё локальное рабочее дерево. Внешние LLM/image API не вызывались.

Откат: при отсутствии активных генераций остановить exposlides, восстановить job.json
и variants.json из shared/deploy-backups/20260929-line-wrapping-02, вернуть current на
releases/20260929-navigation-reset-01 и запустить службу. Файлы старых и новых ревизий
не удалять. Код публикации автоматически выполняет этот откат при ошибке проверки.
