# Hugging Face: развёртывание 22 сентября 2026

## Конфигурация

- Новый релиз: `/home/alex/exposlides/releases/20260922-huggingface-01`.
- Предыдущий релиз: `/home/alex/exposlides/releases/20260922-openrouter-01`.
- API: `https://router.huggingface.co/v1`.
- Модель во всех трёх профилях: `Qwen/Qwen3.8-27B:deepinfra`.
- Глубина рассуждений по умолчанию: `LLM_REASONING_EFFORT=low`.
- Для генерации нужен отдельный токен Hugging Face с разрешением Inference Providers.

Старый ключ OpenRouter не передаётся в Hugging Face. При переключении серверные
настройки сохраняются в закрытой резервной копии, активный ключ очищается до ввода
HF-токена. Локальный `services/content-service/.env` не читается и не переносится.

## Ввод токена

```bash
ssh -t alex-cloud-1 'bash /home/alex/exposlides/current/deploy/alex-cloud/set-huggingface-key.sh'
```

Токен создаётся на [странице Hugging Face](https://huggingface.co/settings/tokens).
Ввод скрыт; значение не нужно писать в команду или переписку.
Готовый API платный после исчерпания ежемесячного кредита.

## Проверки

Релиз активирован. `exposlides` и `caddy` работают; у `exposlides` `NRestarts=0`.
Настройки проверены в окружении запущенного процесса: HF URL, все три модели DeepInfra,
при первичной активации ключ был пуст. Затем пользователь ввёл HF-токен; реальная
генерация успешно завершилась, подробности ниже. Значение токена не выводилось.

| Проверка | Результат |
| --- | --- |
| Полный локальный pytest после финального изменения | 991 passed, 13.51 s |
| Полный pytest в новом релизе на сервере | 991 passed, 25.53 s |
| Закреплённые зависимости и lock на сервере | успешно, 73 packages resolved |
| Ruff изменённых Python-файлов на сервере | All checks passed |
| Полный локальный Ruff | прежние 45 замечаний; пути, строки и коды совпали с baseline |
| HTTPS без авторизации | HTTP 401 |
| Страница с авторизацией | HTTP 200, интерфейс Qwen |
| Загрузка синтетического PPTX | HTTP 201, 1 слайд |
| Предпросмотр | ready, PNG HTTP 200 |
| API библиотеки | HTTP 200 |

Эта таблица описывает первоначальную проверку сайта без вызова модели.

### Реальная проверка после ввода токена

Задание `6a889436fe674d97b6f57603d8c49a9f` прошло полный путь через публичный HTTPS:
встроенный пример → разбор шаблона → HF/DeepInfra → сборка → скачивание PPTX.
Генерация завершилась за **96,5 секунды**, создано **3 слайда** при `max_slides=5`.
PPTX размером 31 972 байта повторно открыт через `python-pptx`; число слайдов и текст
проверены. Предпросмотр готов, все три PNG получены и визуально просмотрены; явного
переполнения или обрезки текста не найдено.

Редакторская проверка: изложенные факты подтверждены исходником, вымышленных метрик
нет. Однако полностью пропущены планы следующего квартала и итоговый принцип выбора
изменений по клиентской обратной связи. Статические номера шаблона остались
`01 / 05`, `03 / 05`, `05 / 05` вместо последовательной нумерации трёх слайдов.
Подключение и сборка работают; полнота содержания и номера требуют отдельного исправления.

Артефакты на сервере:
`/home/alex/exposlides/shared/verification/huggingface-20260922/6a889436fe674d97b6f57603d8c49a9f/`.
В каталоге сохранены `result.pptx`, `summary.json` и `slide-1.png`…`slide-3.png`.
Локальная копия: `/private/tmp/exposlides-huggingface-live-check/6a889436fe674d97b6f57603d8c49a9f/`.

Команда проверки:

```bash
ssh alex-cloud-1 'cd /home/alex/exposlides/current && uv run --no-sync python -' < /private/tmp/exposlides-huggingface-live-check/check.py
```

Это один реальный запуск на встроенном примере; точная стоимость ответа не замерялась,
устойчивость на других текстах и шаблонах этим запуском не подтверждается.

Локальные команды:

```bash
UV_CACHE_DIR=/private/tmp/exposlides-uv-cache uv run --offline pytest
UV_CACHE_DIR=/private/tmp/exposlides-uv-cache uv run --offline ruff check . --output-format json > /private/tmp/exposlides-huggingface-ruff-final.json
git diff --check
```

Первый запуск целевых PTY-тестов внутри песочницы не имел доступа к `/dev/tty`.
Полный набор повторно выполнен с разрешённым доступом к терминалу и прошёл.
Все ключи в тестах фиктивные; внешние LLM-вызовы замоканы.

Команды проверки в каталоге нового релиза на сервере:

```bash
uv sync --locked
uv lock --check
uv run pytest
uv run --offline ruff check services/content-service/app/chains/llm.py services/content-service/app/chains/chat_completions.py services/content-service/app/chains/openrouter.py services/content-service/app/config.py services/content-service/app/errors.py exposlides/web.py tests/test_openrouter_generation.py tests/test_openrouter_transport.py tests/test_fast_llm.py tests/test_generation_pipeline.py tests/test_fast_client_cleanup.py tests/test_fast_alternatives.py tests/test_fast_repair.py tests/test_web.py tests/test_huggingface_key_setup.py tests/test_content_errors.py
```

Активация и проверка сайта с локального компьютера:

```bash
ssh alex-cloud-1 'bash -s' < /private/tmp/exposlides-huggingface-deploy/activate.sh
ssh alex-cloud-1 'cd /home/alex/exposlides/current && uv run --no-sync python -' < /private/tmp/exposlides-huggingface-deploy/smoke.py
```

Последняя команда читает веб-пароль только на сервере, использует его для авторизации
и выводит только безопасные статусы. Генерацию LLM не запускает.

## Изменённые файлы

- `services/content-service/app/chains/chat_completions.py`: общий HTTP-транспорт;
  HF-токен проверяется до создания HTTP-клиента, старый OR-ключ в HF не отправляется.
- `services/content-service/app/chains/openrouter.py`: совместимые aliases старых имён.
- `services/content-service/app/chains/llm.py`: общий клиент, параметры выбранного API,
  нейтральные ошибки и логи; validation и ограниченные повторы сохранены.
- `services/content-service/app/config.py`: HF/DeepInfra по умолчанию, reasoning effort.
- `services/content-service/app/errors.py`: безопасная типизированная ошибка ключа.
- `deploy/alex-cloud/set-huggingface-key.sh`: скрытый ввод, атомарный файл mode 600,
  настройка HF и перезапуск; прежний OpenRouter helper сохранён.
- `scripts/set-llm-key.sh`: подсказка для локального HF-токена.
- `exposlides/web.py`, `exposlides/web_static/app.js`,
  `exposlides/web_static/index.html`: Qwen в интерфейсе и совместимый парсер логов.
- `.env.example`, `README.md`, `evals/README.md`, `deploy/alex-cloud/README.md`,
  `deploy/alex-cloud/HUGGINGFACE-DEPLOY.md`: конфигурация, тарифы, ограничения и проверки.
- `tests/test_openrouter_transport.py`, `tests/test_openrouter_generation.py`,
  `tests/test_content_errors.py`, `tests/test_huggingface_key_setup.py`,
  `tests/test_fast_llm.py`, `tests/test_generation_pipeline.py`,
  `tests/test_fast_client_cleanup.py`, `tests/test_fast_alternatives.py`,
  `tests/test_fast_repair.py`, `tests/test_web.py`: проверки HF, ошибок и совместимости.

Зависимости в этой миграции не менялись. В релиз вошёл проверенный снимок рабочего
дерева из 179 явно выбранных файлов без `.env`, `.git`, `.venv`, ключей и локальных
артефактов. Предыдущая версия сохранена.

## Откат

Перед активацией сохраняются прежний `content.env`, путь версии и временные файлы
сессии в `/home/alex/exposlides/shared/deploy-backups/20260922-huggingface-01`.
Если после переключения сайт не стартует, скрипт активации автоматически возвращает
прежние настройки и версию.

Для ручного отката после успешного развёртывания под пользователем `alex`:

```bash
cp -p /home/alex/exposlides/shared/deploy-backups/20260922-huggingface-01/content.env /home/alex/exposlides/shared/content.env
ln -s /home/alex/exposlides/releases/20260922-openrouter-01 /home/alex/exposlides/rollback-huggingface
mv -Tf /home/alex/exposlides/rollback-huggingface /home/alex/exposlides/current
sudo systemctl restart exposlides
sudo systemctl is-active exposlides
```

Возврат версии не восстанавливает временную сессию автоматически; её файлы остаются
в резервной копии. В бесплатном OpenRouter остаётся ранее обнаруженное ограничение
HTTP 429 у ModelRun.
