# HTML-экспорт — 29 сентября 2026

Опубликован `/home/alex/exposlides/releases/20260929-html-export-01`.
Предыдущий релиз: `/home/alex/exposlides/releases/20260929-palette-game-01`.
Новый релиз скопирован с фактического активного серверного релиза; поверх внесено
только добавление HTML в просмотрщик и соответствующие изменения тестов.

HTML уже создавался сервером, но был скрыт в простом просмотрщике. Теперь кнопка
HTML рядом с PPTX/PDF скачивает автономный файл выбранного варианта. Если экспорта
нет, кнопка отсутствует. Переключение оформления обновляет ссылку.

## Изменённые локальные файлы

- `frontend/src/ResultViewer.tsx` — кнопка HTML.
- `frontend/tests/studio.test.tsx` — наличие ссылки, переключение вариантов,
  отсутствие ссылки у варианта без HTML, частичный результат.
- `frontend/README.md` — описание скачивания.
- `exposlides/studio_static/app.js`, `app.css`, `index.html` — результат сборки
  текущего локального интерфейса; серверная сборка выполнена отдельно из серверных исходников.
- `deploy/alex-cloud/README.md` и этот отчёт — активный релиз и проверки.

## Проверки

До изменения: `uv run pytest -q`, `uv run ruff check .`,
`npm --prefix frontend test` — успешно.
После изменения локально: `uv run pytest -q`, `uv run ruff check .` — успешно;
`npm --prefix frontend test` — 49/49; `npm --prefix frontend run build` — успешно,
включая TypeScript.
В новом серверном релизе: `npm ci --no-audit --no-fund`, `npm test` (49/49),
`npm run build` из `frontend`; `uv run pytest -q` и `uv run ruff check .`
из корня — успешно. В Python есть предупреждения устаревших API, ошибок нет.

Отдельная серверная проверка без LLM и пользовательских данных: создан временный
PPTX с одним слайдом и повторно открыт через python-pptx; реальный LibreOffice и
Poppler создали PDF/SVG/HTML. Через TestClient приложения проверены HTTP 200,
Content-Type text/html, Content-Disposition attachment и встроенное SVG в HTML.
Временные файлы удалены автоматически.

Перед переключением проверено отсутствие активных генераций. После переключения:
`systemctl is-active exposlides` — active; GET `/` и `/app.js` на loopback — 200,
содержимое точно совпадает со сборкой релиза, ссылка HTML присутствует в bundle.
Публичный HTTPS без пароля — 401, как ожидается. Проверка в браузере не выполнялась.

Общий `git diff --check` выявил существующие пробелы в чужом
`story-stream-20260929.patch`; файл не изменялся этой задачей.

## Откат

Предыдущий релиз сохранён; его путь записан в `HTML_EXPORT_PREVIOUS_RELEASE`
нового релиза. При необходимости атомарно вернуть `current` на
`/home/alex/exposlides/releases/20260929-palette-game-01`, затем выполнить
`sudo systemctl restart exposlides` и проверить HTTP. Перед откатом убедиться,
что нет активной генерации. Секреты и постоянная история не изменялись.
