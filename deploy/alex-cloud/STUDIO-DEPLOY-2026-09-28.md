# Публикация студии — 28 сентября 2026

Адрес: https://exposlides.158-160-217-249.sslip.io/

Опубликован проверенный снимок рабочей копии с тремя экранами и новым оформлением.
Исходники содержат незакоммиченные изменения; это не публикация одного Git-коммита.

- Релиз: `/home/alex/exposlides/releases/20260928-studio-editorial-01`.
- Предыдущий: `/home/alex/exposlides/releases/20260925-dev-12f4fb1`.
- `current` переключён на новый релиз.
- Служба `exposlides` запускает `python -m exposlides.studio --port 8765`.
- Постоянные данные: `/home/alex/exposlides/shared/studio`.
- Изменение запуска: `/etc/systemd/system/exposlides.service.d/10-studio.conf`.
- Резервная копия старой службы и временной рабочей папки:
  `/home/alex/exposlides/shared/deploy-backups/20260928-studio-editorial-01`.
- Caddy, Basic Auth и настройки модели сохранены. Play Regular/Bold установлены
  в `/home/alex/.local/share/fonts/Play` для корректного предпросмотра шаблонов.

В момент переключения старая библиотека содержала ноль шаблонов и результатов,
дочерних процессов генерации не было. Её временная папка дополнительно сохранена.

## Проверки

На сервере в каталоге нового релиза:

```bash
uv sync --locked
uv lock --check
uv run pytest --tb=short
uv run ruff check .
```

Итог: 1366 passed за 41,96 с, одно существующее предупреждение Starlette/httpx;
Ruff — успешно. Первый ограниченный архив не включал часть ресурсов, поэтому
первые проверки завершались ошибками. До переключения добавлены скрипты,
`agents/designer.toml`, реестр `config/*.toml`, `prompts/designer/*.md`, старая
статика и JS-сценарии тестов. Служебные `._*`-метаданные macOS удалены из нового
релиза. Итоговые проверки выполнены после этих исправлений.

Кандидат проверен на loopback-порту 8766 с отдельной папкой данных и существующей
конфигурацией модели. Реальная генерация Hugging Face создала три варианта по три
слайда; каждый PPTX повторно открыт, изображения предпросмотра доступны.
После публикации временная служба остановлена.

На основном порту 8765 проверены HTTP 200 и SHA-256 опубликованных HTML/JS/CSS,
доступность модели, создание презентации в extractive-режиме, предпросмотр,
скачивание и повторное открытие PPTX. Затем при отсутствии активных работ выполнен
перезапуск: прежний результат и скачивание остались доступны той же сессии.
Сессионные данные использовались только в памяти проверяющего процесса.

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://exposlides.158-160-217-249.sslip.io/
systemctl show exposlides -p ActiveState -p SubState -p NRestarts
systemctl is-active caddy
```

Результат: HTTPS 401 без авторизации (ожидаемая защита), служба active/running,
NRestarts=0, Caddy active. Внешний вход с паролем не проверен: автоматический
контроль отклонил чтение реквизитов и сохранение сессионного файла. Вместо этого
проверены публичный HTTPS без входа и полный сценарий через loopback.

## Откат

Перед откатом дождаться завершения активных генераций. На сервере:

```bash
sudo mv /etc/systemd/system/exposlides.service.d/10-studio.conf \
  /home/alex/exposlides/shared/deploy-backups/20260928-studio-editorial-01/10-studio.conf
ln -s /home/alex/exposlides/releases/20260925-dev-12f4fb1 \
  /home/alex/exposlides/current-rollback-20260928
mv -Tf /home/alex/exposlides/current-rollback-20260928 /home/alex/exposlides/current
sudo systemctl daemon-reload
sudo systemctl restart exposlides
```

Новая история остаётся в `shared/studio`; старый интерфейс не показывает её,
но повторное включение студии возвращает доступ. Ключи, пароли, история браузера
и пользовательские презентации в релизный архив не включались.
