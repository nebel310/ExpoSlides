# ExpoSlides

Создаёт редактируемую презентацию из PPTX-шаблона и текста с помощью
[Qwen3.8 27B через Hugging Face](https://huggingface.co/inference/models?model=Qwen/Qwen3.8-27B).

## Установка

Нужны Git, [uv](https://docs.astral.sh/uv/getting-started/installation/) и токен Hugging Face.
Команды для macOS и Linux:

```bash
git clone --branch dev https://github.com/nebel310/ExpoSlides.git
cd ExpoSlides
uv python install 3.12
uv sync --locked
cp -n .env.example services/content-service/.env
```

Создайте [токен Hugging Face](https://huggingface.co/settings/tokens) с разрешением
**Inference Providers** и сохраните его в `services/content-service/.env` вместо
`LLM_API_KEY=your-hf-token`. Не присылайте токен в чат и не добавляйте его в Git.
Исходный текст и текстовая структура шаблона отправляются через Hugging Face
провайдеру DeepInfra для генерации Qwen.

Если `.env` уже настроен для GigaChat или OpenRouter, замените ключ и настройки модели и адреса:
`cp -n` сохраняет существующий файл, поэтому сам их не обновляет.

```dotenv
LLM_BASE_URL=https://router.huggingface.co/v1
LLM_MODEL=Qwen/Qwen3.8-27B:deepinfra
LLM_FAST_MODEL=Qwen/Qwen3.8-27B:deepinfra
LLM_FAST_REPAIR_MODEL=Qwen/Qwen3.8-27B:deepinfra
```

Удалите старые `LLM_SCOPE` и `GIGACHAT_CA_BUNDLE_FILE`: для Hugging Face они не используются.
Ключи GigaChat и OpenRouter не подходят. Модель одинакова для обычного и быстрого режимов;
суффикс `:deepinfra` явно выбирает провайдера. Реальная проверка 22 сентября 2026 года
создала PPTX за 96,5 секунды, но выявила пропуск части исходного текста и сохранение
номеров шаблона. Подробности: [проверка Hugging Face](deploy/alex-cloud/HUGGINGFACE-DEPLOY.md).
По умолчанию `LLM_REASONING_EFFORT=none` отключает дополнительные рассуждения модели
через HF/DeepInfra. При необходимости их можно включить значениями `low`, `medium`
или `xhigh`; это увеличивает объём работы и может привести к превышению времени ожидания.
Лимиты: 180 секунд на запрос и 240 секунд на весь быстрый режим.

На 22 сентября 2026 года [тариф Qwen3.8 27B у DeepInfra через Hugging Face](https://huggingface.co/inference/models?model=Qwen/Qwen3.8-27B)
составляет **$0.20 за 1 млн входных и $2.50 за 1 млн выходных токенов**.
Бесплатному аккаунту Hugging Face предоставляется небольшой кредит **$0.10 в месяц**;
это не безлимитная бесплатная генерация. Актуальные условия и оплата после исчерпания
кредита описаны в [тарифах Hugging Face](https://huggingface.co/docs/inference-providers/pricing).

Для просмотра слайдов с цветами и картинками установите LibreOffice и Poppler.

macOS с Homebrew:

```bash
brew install --cask libreoffice
brew install poppler
```

Ubuntu / Debian:

```bash
sudo apt update
sudo apt install libreoffice poppler-utils
```

Без них PPTX создаётся, но предпросмотр показывает только текст.

## Запуск

Из папки `ExpoSlides`:

```bash
uv run python -m exposlides.web
```

Откройте **[http://127.0.0.1:8765](http://127.0.0.1:8765)**. Загрузите шаблон,
добавьте текст и нажмите «Создать презентацию». После сборки скачайте PPTX.

Можно генерировать несколько презентаций одновременно: после запуска нажмите
«Создать ещё одну», измените материалы и запустите следующую. В списке «Ваши запуски»
можно вернуться к каждой презентации и скачать результат. Список сохраняется при
обновлении вкладки в пределах текущей серверной сессии.

Другой порт: `uv run python -m exposlides.web --port 8766`.
Остановка — `Ctrl+C`. По умолчанию файлы сессии временные: скачайте результат до остановки.
После изменения `.env` или установки программ для просмотра перезапустите сервер.

## Постоянное хранилище

Чтобы шаблоны и готовые презентации оставались в интерфейсе после перезапуска,
подключите уже работающий `file-service` с MinIO и PostgreSQL:

```bash
uv run python -m exposlides.web \
  --file-service 127.0.0.1:50051 \
  --data-dir "$HOME/.local/share/exposlides"
```

Оба параметра обязательны для этого режима. Их также можно задать переменными
окружения процесса `EXPOSLIDES_FILE_SERVICE` и `EXPOSLIDES_DATA_DIR`; файл
`services/content-service/.env` эти настройки веб-серверу не передаёт.

PPTX сохраняются через `file-service` в MinIO; PostgreSQL хранит метаданные и версии
файлов. Локальный `library.json` в каталоге `--data-dir` хранит библиотеку и ссылки
на конкретные версии. После перезапуска сохранённые шаблоны и результаты доступны
в интерфейсе, а файлы загружаются при обращении к ним. Сохраняйте и резервируйте
каталог `--data-dir` вместе с данными MinIO и PostgreSQL.

Библиотека общая для всех пользователей одного процесса; отдельных учётных записей
и изоляции данных нет. Незавершённая генерация после перезапуска не возобновляется.
Предпросмотр, промежуточные файлы и журналы остаются временными и удаляются
при штатной остановке. CLI без интерфейса по-прежнему пишет результат в `--output`.

## Шаблон

- Нужен `.pptx` с текстовыми заполнителями PowerPoint (placeholders).
- Оформление, изображения и таблицы сохраняются из шаблона; заменяется текст заполнителей.
- Новые слайды не создаются. Каждый слайд шаблона используется не больше одного раза.

## Запуск без интерфейса

```bash
uv run python -m exposlides \
  --template template.pptx \
  --script script.txt \
  --output result.pptx \
  --generation-mode fast \
  --max-slides 15
```

`script.txt` — текст в UTF-8. `--max-slides` задаёт верхний предел числа слайдов.
Все параметры: `uv run python -m exposlides --help`.

## Проверки

```bash
uv run pytest
uv run ruff check .
```

Тесты работают без LLM API. [Сценарии и замеры генерации](evals/README.md).
