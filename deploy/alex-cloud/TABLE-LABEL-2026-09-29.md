# Подпись таблиц Excel/CSV

Релиз: `20260929-table-label-01`, основа и откат: `20260929-workflow-02`.
Изменена подпись на «Добавить таблицы Excel/CSV», добавлена подсказка сохранять
таблицы Excel в CSV (UTF-8). Принимаемые форматы остались CSV/TSV.

Файлы: `frontend/src/DatasetInput.tsx`, `frontend/README.md`, пересобранные
`exposlides/studio_static/app.js`, `app.css`, `index.html`,
`deploy/alex-cloud/README.md` и этот отчёт. На сервер перенесён только компонент,
интерфейс собран из действующей серверной версии; автопереход игры сохранён.

До и после изменения: `npm --prefix frontend test` — 50/50,
`uv run pytest -q` и `uv run ruff check .` — успешно.
`npm --prefix frontend run build` — успешно.
На сервере из frontend: `npm test` — 50/50, `npm run build` — успешно.
Перед переключением проверены текущий релиз и отсутствие активных заданий.
После публикации HTML/JS/CSS отвечают HTTP 200 и совпадают с файлами релиза,
в bundle присутствует Excel/CSV; служба active. Браузерная проверка не выполнялась.

Предыдущая версия сохранена в `TABLE_LABEL_PREVIOUS_RELEASE` нового релиза.
Для отката при отсутствии активных заданий атомарно вернуть current на
`/home/alex/exposlides/releases/20260929-workflow-02` и перезапустить exposlides.
Секреты и пользовательские данные не менялись.
