# Проверка развертывания — 22 сентября 2026

Адрес: https://exposlides.158-160-217-249.sslip.io.
Релиз: `/home/alex/exposlides/releases/20260922-01`.
Это снимок рабочего дерева с незакоммиченными файлами, а не только Git HEAD.
Содержимое исходников приложения сверено с локальными файлами после установки:
изменений Python, JavaScript, CSS, HTML, моделей, lock-файла и сертификата не обнаружено.

Установлены Python-окружение через `uv sync --locked`, LibreOffice Impress,
Poppler и шрифты. Служба `exposlides` включена в автозапуск, работает от `alex`,
слушает только `127.0.0.1:8765`; Caddy предоставляет внешний HTTPS и Basic Auth.
После проверок служба перезапущена, тестовые загрузки удалены вместе с сеансом.
Проверено состояние `active/running`, `NRestarts=0`, `ExecMainStatus=0`.

## Команды и результаты

На локальном компьютере из корня проекта:

```bash
UV_CACHE_DIR=/private/tmp/exposlides-uv-cache uv run --offline pytest
UV_CACHE_DIR=/private/tmp/exposlides-uv-cache uv run --offline ruff check .
UV_CACHE_DIR=/private/tmp/exposlides-uv-cache uv lock --check --offline
```

- Pytest: **799 passed**, 10,51 с.
- Полный Ruff: **49 исходных замечаний** — 36 I001, 12 F401, 1 F541;
  они обнаружены до изменений развертывания. Массовое исправление не выполнялось.
- Lock-файл: проверка прошла, 74 пакета.

На Alex cloud из каталога релиза:

```bash
uv sync --locked
uv lock --check
uv run --offline pytest
uv run --offline ruff check exposlides tests evals \
  services/content-service/app/chains services/content-service/app/graph \
  services/content-service/app/utils services/content-service/app/models \
  services/content-service/app/config.py services/content-service/app/errors.py \
  services/content-service/app/main.py services/parsing-service/app/parsers \
  services/parsing-service/app/models services/parsing-service/app/main.py \
  services/builder-service/app
sudo systemd-analyze verify /etc/systemd/system/exposlides.service
sudo caddy validate --config /home/alex/exposlides/shared/Caddyfile.candidate --adapter caddyfile
systemctl is-enabled exposlides
systemctl is-active exposlides caddy
```

- Установка и lock: успешно.
- Pytest: **799 passed**, 21,72 с. Включает офлайн E2E с созданием и повторным
  открытием PPTX; LLM подменён тестовой реализацией.
- Ruff для перечисленного рабочего кода и корневых тестов: **All checks passed**.
  Перед итоговой проверкой удалены попавшие в архив служебные файлы macOS `._*`.
- Unit-файл проверен. systemd также вывел существующее замечание о старом пути
  PIDFile чужой службы `active-protection`; её конфигурация не менялась.
- Caddy: **Valid configuration**; предупреждение о форматировании существующего
  основного Caddyfile не препятствует проверке.
- Автозапуск: **enabled**. Обе службы: **active**.

Публичные HTTP-проверки выполнены с локального компьютера:

```bash
UV_CACHE_DIR=/private/tmp/exposlides-uv-cache uv run --offline python /private/tmp/exposlides-cloud-deploy/smoke.py
```

Проверены доверенный TLS-сертификат, перенаправление HTTP → HTTPS, отказ без пароля
и с неверным паролем (401), страница и статические файлы (200). Посторонние, пустые
и повторяющиеся Origin отклоняются (403). Запись без правильного CSRF-токена
отклоняется (403), корректный токен допускает проверку входных данных (400 для
пустого задания). Пример содержит пять слайдов; загрузка тестового PPTX вернула
201; все пять изображений предпросмотра получены и проверены как PNG.
Команда `curl --fail --silent http://127.0.0.1:8765/ -o /dev/null` после финального
перезапуска завершилась успешно.

## Подключение GigaChat

После явного разрешения владельца 22 сентября 2026 существующий локальный
`services/content-service/.env` передан по SSH в `shared/content.env` без вывода
содержимого. Права файла — `600`; `sudo systemctl restart exposlides` выполнен,
`systemctl is-active exposlides caddy` вернул два `active`.

Проверка окружения запущенного процесса подтвердила наличие непустого ключа
`LLM_API_KEY`, не равного стандартной заглушке, и `LOG_LEVEL=INFO`. Выведены только
результаты проверки, значение ключа не выводилось. Локальный HTTP после
перезапуска вернул 200. Реальные запросы к GigaChat не выполнялись; авторизация
у провайдера и полная генерация с реальным LLM пока не проверены.

По последнему указанию владельца Basic Auth оставлен включённым; пароль не менялся.
Публичная HTTPS-проверка после переноса конфигурации: `/` без авторизации — 401,
`/` и `/api/session` с прежним паролем — 200, `/.env` с паролем — 404.
В этом дополнении изменены только README и отчёт развертывания; исходники,
зависимости и конфигурация Caddy не менялись, полный pytest повторно не запускался.

## Файлы этой задачи

- `deploy/alex-cloud/Caddyfile` — шаблон HTTPS-прокси без настоящего хеша пароля.
- `deploy/alex-cloud/exposlides.service` — автозапуск и остановка приложения.
- `deploy/alex-cloud/README.md` — настройка, обновление и откат.
- `deploy/alex-cloud/VERIFICATION.md` — этот отчёт.

Исходный код приложения и чужие незакоммиченные изменения не менялись.
Резервная копия исходного прокси: `/etc/caddy/Caddyfile.pre-exposlides-20260922-01`.
Реквизиты доступа находятся вне Git; в шаблонах и отчёте секретов нет.
