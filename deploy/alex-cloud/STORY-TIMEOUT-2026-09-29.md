# Тайм-аут первого ответа планировщика — 29 сентября 2026

## Причина

Задание `f993d34843234e489f30e59a736afe34`: 12 слайдов, 7361 символ исходника.
INFO-журнал: HTTP 200 от провайдера через две секунды, затем остановка первого
потокового запроса ровно через 220 секунд. План ещё не был получен; повторные
редакторские попытки не начинались. Исходное задание сохранено без изменений.

## Изменения

- `services/content-service/app/design_main.py`: один запрос — до 480 секунд.
- `agents/designer.toml`: версия 1.2.1, вся роль story — до 600 секунд.
- `services/content-service/app/design_config.py`: допустимый предел story — 600 секунд.
- `exposlides/design_pipeline.py`: общий предел по умолчанию — 900 секунд.
- `exposlides/studio.py`: тот же предел для студии с вычетом уже затраченного времени.
- `tests/test_design_agent_config.py`: пределы и запас на исправление/экспорт.
- `tests/test_studio_generate.py`: сборка после 480 секунд планирования получает
  оставшиеся 420 секунд; прежний общий предел больше не прерывает её.
- `README.md`: текущие пределы студии.

Отмена, число попыток, проверки содержания и обработка ошибок сохранены.
Это увеличение допустимого ожидания, а не ускорение внешней модели.

## Офлайн-проверки

Локально до исправления: полный pytest успешен; Ruff — 31 существующая ошибка
в двух untracked-скриптах `artifacts/lct-presentation-20260929/.build/`.
Эти пользовательские файлы не изменялись и не публиковались.

После исправления:

```bash
uv run pytest -q
# 1664 теста, exit 0; предупреждения Starlette и forkpty
uv run pytest tests/test_design_agent_config.py tests/test_design_generation.py tests/test_studio_generate.py -q -o addopts=''
# 60 passed, 1 warning
uv run ruff check . --output-format concise
# те же 31 baseline-ошибка только в artifacts/
uv run ruff check . --exclude artifacts
# All checks passed!
git diff --check
# exit 0
```

В отдельном серверном релизе:

```bash
cd /home/alex/exposlides/releases/20260929-story-timeout-02
uv run --no-sync --offline pytest -q
# 1632 теста, exit 0; предупреждение Starlette
uv run --no-sync --offline ruff check .
# All checks passed!
```

Серверный релиз основан на полной копии действовавшего
`20260929-repo-cleanup-01`; применён только patch текущего исправления.
Существующие серверные отличия тестов сохранены. Установленное окружение
используется по прежней ссылке, зависимости не менялись.

## Реальная проверка и публикация

Исправление загружено в `dev` и включено в `main` коммитом `765bc21`.
Рабочие файлы подготовленного релиза совпадают с этим коммитом; серверные
отличия сохранены.

Переключение не выполнено: при проверке в shared/studio оставалось одно
задание со статусом running, а на диске сервера было свободно только 509 МиБ
(99% занято). Перед переключением нужно дождаться завершения задания,
обеспечить место для резервной копии и проверить опубликованный результат.
Реальный LLM-прогон в этой задаче не запускался; результат проверки, начатой
в другой задаче, здесь не подтверждён. Активным остался `20260929-repo-cleanup-01`.

## Откат

Предыдущий релиз: `/home/alex/exposlides/releases/20260929-repo-cleanup-01`.
Каталог shared, секреты, пользовательские файлы и прежнее окружение сохранены.
При необходимости:

```bash
ln -s /home/alex/exposlides/releases/20260929-repo-cleanup-01 /home/alex/exposlides/current-story-timeout-rollback
mv -Tf /home/alex/exposlides/current-story-timeout-rollback /home/alex/exposlides/current
sudo systemctl restart exposlides
```
