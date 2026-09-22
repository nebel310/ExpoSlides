# ExpoSlides

Создаёт редактируемую презентацию из PPTX-шаблона и текста с помощью GigaChat.

## Установка

Нужны Git, [uv](https://docs.astral.sh/uv/getting-started/installation/) и доступ к GigaChat API.
Команды для macOS и Linux:

```bash
git clone --branch dev https://github.com/nebel310/ExpoSlides.git
cd ExpoSlides
uv python install 3.12
uv sync --locked
cp -n .env.example services/content-service/.env
```

В `services/content-service/.env` замените `LLM_API_KEY=your-api-key` своим
[ключом авторизации GigaChat (Authorization key)](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/post-token).
`LLM_SCOPE` по умолчанию — `GIGACHAT_API_PERS`; для другого типа доступа укажите свой scope.

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

Другой порт: `uv run python -m exposlides.web --port 8766`.
Остановка — `Ctrl+C`. Скачайте результат до остановки: файлы сессии временные.
После изменения `.env` или установки программ для просмотра перезапустите сервер.

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
