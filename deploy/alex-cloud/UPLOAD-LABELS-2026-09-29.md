# Заголовки экрана загрузки без цифр

Опубликован релиз `20260929-upload-labels-01` на основе действовавшего
`20260929-table-label-01`. Удалены метки 01 и 02 у «Шаблон презентации»
и «Содержание», а также неиспользуемый стиль field-number.

Изменены `frontend/src/App.tsx`, `frontend/src/styles.css`, пересобраны
`exposlides/studio_static/app.js`, `app.css`, `index.html`.
Обновлены `deploy/alex-cloud/README.md` и этот отчёт.
На сервере те же точечные изменения применены к копии активного релиза;
остальные серверные изменения, секреты и пользовательские данные сохранены.

Проверки до и после изменения:
- `npm --prefix frontend test` — 50/50.
- `uv run pytest -q` — успешно; существующие предупреждения о deprecated API.
- `uv run ruff check .` — успешно.
- После правки `npm --prefix frontend run build` — успешно.
- На сервере из frontend: `npm run build` и `npm test` — успешно, 50/50.
- Точечный diff проверен: удалены только две метки и их CSS-правило.
- Общий `git diff --check` сообщает о прежних пробелах в
  `deploy/alex-cloud/story-stream-20260929.patch`; файл не менялся этой задачей.

Перед переключением проверены активный релиз и отсутствие queued/running/cancelling
заданий. После публикации HTML, JS и CSS получены по HTTP, побайтово совпадают
с релизом; field-number отсутствует в JS/CSS. Служба active.
Внешний HTTPS отвечает ожидаемым 401 без авторизации.
Браузерная визуальная проверка не выполнялась.

Откат: при отсутствии активных заданий атомарно вернуть current на
`/home/alex/exposlides/releases/20260929-table-label-01` и перезапустить
exposlides. Путь также сохранён в `UPLOAD_LABELS_PREVIOUS_RELEASE` нового релиза.
