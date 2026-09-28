# Исправление ошибки загрузки — 22 сентября 2026

Пользователь сообщил о сообщении «Нет связи с приложением» после загрузки PPTX
в Safari по обычному HTTPS-адресу. Процесс сервера работал, перезапусков из-за
ошибок не было. Сам Safari в автоматизированной проверке не использовался.

## Воспроизведение и изменение

Открытая страница сохраняла токен старого процесса после перезапуска сервера.
При POST сервер проверял токен до чтения тела, отвечал 403 и закрывал соединение,
пока клиент ещё отправлял большой файл. Регрессионный тест через socketpair
с телом 1 МиБ воспроизвёл BrokenPipeError до исправления.

Теперь интерфейс обновляет сессию после чтения файла, прямо перед POST;
при 403 сбрасывает сохранённый токен. Автоматических повторов запросов записи
при потере связи нет. Сервер сначала проверяет Host/Origin, читает ограниченное
по размеру тело и затем проверяет токен до любых изменений состояния.

Дополнительно запрос HTTP/2 без Content-Length получал 400, потому что локальный
сервер не принимает chunked-запросы. В Caddy добавлено `request_buffers 36MB`
при существующем `max_size 36MB`. Буферизация до отправки в приложение позволяет
нормализовать длину таких загрузок; стоимость — до 36 МБ буфера на запрос.
См. [официальное описание request_buffers](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#streaming).

## Проверки

Из корня локального проекта:

```bash
UV_CACHE_DIR=/private/tmp/exposlides-uv-cache uv run --no-sync --offline pytest tests/test_web.py tests/test_web_ui.py
UV_CACHE_DIR=/private/tmp/exposlides-uv-cache uv run --no-sync --offline pytest
UV_CACHE_DIR=/private/tmp/exposlides-uv-cache uv run --no-sync --offline ruff check exposlides/web.py tests/test_web.py tests/test_web_ui.py
UV_CACHE_DIR=/private/tmp/exposlides-uv-cache uv run --no-sync --offline ruff check . --statistics
git diff --check
```

- Целевые тесты: **83 passed** (baseline: 77).
- Полный pytest: **834 passed**, 12,58 с (baseline: 828).
- Ruff изменённого Python-кода: **All checks passed**.
- Полный Ruff: прежние **49 замечаний**, новых нет.
- Проверка diff: без замечаний.

На сервере из `/home/alex/exposlides/current`:

```bash
uv run --offline pytest
uv run --offline ruff check exposlides/web.py tests/test_web.py tests/test_web_ui.py
sudo caddy validate --config /etc/caddy/Caddyfile
systemctl is-active exposlides caddy
```

Результат: **805 passed**, 20,56 с; Ruff прошёл; Caddy **Valid configuration**;
обе службы **active**. В серверном снимке меньше тестов, чем в текущем локальном
дереве: параллельная разработка Streamlit не переносилась в рамках исправления.

Публичная проверка через HTTP/2 выполнена командой:

```bash
UV_CACHE_DIR=/private/tmp/exposlides-uv-cache uv run --no-sync --offline python /private/tmp/exposlides-upload-debug/probe.py
curl --http2 --silent --show-error --max-time 30 \
  --config /private/tmp/exposlides-upload-debug/curl-valid.conf \
  --header 'Content-Length:' \
  --data-binary @/private/tmp/exposlides-upload-debug/upload-1048576.json \
  --output /private/tmp/exposlides-upload-debug/response-no-length-fixed.json \
  --write-out 'status=%{http_code} uploaded=%{size_upload}\n' \
  https://exposlides.158-160-217-249.sslip.io/api/templates
```

Тестовые PPTX созданы программно; пользовательские презентации не использовались.

| Запрос | До исправления | После |
| --- | --- | --- |
| Валидная сессия, PPTX с 1/8 МиБ тестовых данных | 201 | 201 |
| Старая сессия, тело 1 444 670 байт | 403 после ~130 КБ отправки | 403 после всех 1 444 670 байт |
| Старая сессия, тело 11 231 382 байта | 403 после ~130 КБ отправки | 403 после всех 11 231 382 байт |
| HTTP/2 без Content-Length, тело 1 444 670 байт | 400 после ~130 КБ отправки | 201 после всех 1 444 670 байт |

Пароль и LLM-конфигурация сохранены; вызовов GigaChat не было.

## Изменённые файлы и откат

- `exposlides/web.py`
- `exposlides/web_static/app.js`
- `tests/test_web.py`
- `tests/test_web_ui.py`
- `tests/web_ui_scenarios.js`
- `deploy/alex-cloud/Caddyfile`
- `deploy/alex-cloud/README.md`
- `deploy/alex-cloud/UPLOAD-FIX.md`

Исправление установлено поверх проверенного релиза `20260922-01` после сверки
хешей исходного серверного кода. Исходные файлы сохранены в
`/home/alex/exposlides/hotfixes/20260922-upload-session/backup`, исходный фрагмент
Caddy — рядом в `exposlides.caddy.before`. Для отката восстановите только эти
файлы, проверьте конфигурацию Caddy, перезагрузите Caddy и перезапустите ExpoSlides.
Не заменяйте настройки другими локальными незакоммиченными изменениями.
