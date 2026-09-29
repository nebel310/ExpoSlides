# Автопереход палитры — 29 сентября 2026

Опубликован `/home/alex/exposlides/releases/20260929-palette-auto-01`.
Основа и предыдущий активный релиз: `/home/alex/exposlides/releases/20260929-workflow-01`.
Серверные исходники сохранены, поверх перенесены только компонент игры, его CSS и тест.
Сборка выполнена из серверных исходников. Секреты и пользовательские данные не менялись.

Собранные карточки обводятся зелёной рамкой. Через 650 мс появляется следующая
перемешанная палитра. Кнопка перехода удалена; таймер очищается при закрытии игры.

Изменённые локальные файлы:
- `frontend/src/SlideGame.tsx`
- `frontend/src/slide-game.css`
- `frontend/tests/slide-game.test.tsx`
- `frontend/README.md`
- `exposlides/studio_static/app.js`, `app.css`, `index.html` — локальная сборка
- `deploy/alex-cloud/README.md` и этот отчёт

Проверки до изменения: `npm --prefix frontend test`, `uv run pytest`,
`uv run ruff check .` — успешно.
После изменения локально: `npm --prefix frontend test` — 50/50;
`npm --prefix frontend run build`, `uv run pytest -q`, `uv run ruff check .` — успешно.
В тесте обновлено ожидание завершения презентации под интервал опроса статуса 1500 мс.
На сервере из frontend: `npm test` — 50/50, `npm run build` — успешно;
из корня: `uv run --no-sync --offline pytest -q`,
`uv run --no-sync --offline ruff check .` — успешно.
Проверен diff затронутых отслеживаемых файлов; новые исходники игры просмотрены отдельно.

Перед переключением проверено отсутствие активных заданий и неизменность current.
После переключения служба active; `/`, `/app.js`, `/app.css` отвечают HTTP 200
на loopback и побайтово совпадают с релизом. В опубликованном bundle нет кнопки
перехода, CSS содержит зелёную рамку. Публичный HTTPS без пароля отвечает 401.
Визуальная проверка в браузере не выполнялась.

Откат: предыдущая версия сохранена, её путь записан в
`PALETTE_AUTO_PREVIOUS_RELEASE` нового релиза. При отсутствии активной генерации
атомарно вернуть current на `/home/alex/exposlides/releases/20260929-workflow-01`,
перезапустить `sudo systemctl restart exposlides` и проверить HTTP.
