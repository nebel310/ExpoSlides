# ExpoSlides на Alex cloud

Схема развертывания личного демо; успешность запуска проверяется командами ниже.
Покупать домен для этого адреса не требуется:
[https://exposlides.158-160-217-249.sslip.io](https://exposlides.158-160-217-249.sslip.io).
Адрес зависит от IP сервера и DNS-сервиса sslip.io.

| Что | Где |
| --- | --- |
| SSH | `ssh alex-cloud-1` → `alex@158.160.217.249` |
| Первый снимок рабочего дерева, включая незакоммиченный код | `/home/alex/exposlides/releases/20260922-01` |
| Активная версия | `/home/alex/exposlides/current` — ссылка на каталог версии |
| Предыдущий релиз с OpenRouter | `/home/alex/exposlides/releases/20260922-openrouter-01` |
| Релиз с Hugging Face от 2026-09-22 | `/home/alex/exposlides/releases/20260922-huggingface-01` |
| Исправление тайм-аута от 2026-09-23 | `/home/alex/exposlides/releases/20260923-timeout-01` |
| Системная служба | `/etc/systemd/system/exposlides.service`, пользователь `alex` |
| Внутренний HTTP | `127.0.0.1:8765` |
| Конфигурация сайта | `/etc/caddy/exposlides.caddy`, импорт из `/etc/caddy/Caddyfile` |
| Настройки LLM | `/home/alex/exposlides/shared/content.env` |
| Пароль веб-доступа | `/home/alex/exposlides/shared/web-password`, права `600` |
| Каталог постоянной библиотеки в шаблоне systemd | `/home/alex/exposlides/shared/library/library.json` |
| Адрес file-service в шаблоне systemd | `127.0.0.1:50051` |

Caddy предоставляет HTTPS и Basic Auth с именем `alex`. Реквизиты первого доступа
сохранены локально в `/private/tmp/exposlides-cloud-deploy/access.md`; это временный
файл вне репозитория. Шаблон [Caddyfile](Caddyfile) содержит заглушку хеша пароля:
его нельзя устанавливать поверх рабочей конфигурации без замены заглушки.
Caddy проверяет внешний Origin и передаёт допустимые Host/Origin локальному серверу.
Тело загрузки буферизуется в пределах 36 МБ: это позволяет локальному HTTP-серверу
получать полную длину запроса и принимать загрузки HTTP/2 без Content-Length.
Перед отправкой PPTX интерфейс обновляет токен сессии, в том числе после перезапуска
сервера. После обновления приложения перезагрузите уже открытую вкладку.

## Окружение и ограничения

В каждой версии используется Python 3.12 и собственная `.venv`, созданная через
`uv sync --locked`. Для предпросмотра на Ubuntu нужны:

```bash
sudo apt install libreoffice-impress poppler-utils fonts-liberation fonts-dejavu-core
```

[exposlides.service](exposlides.service) запускает из `current` команду
`.venv/bin/python -m exposlides.web --port 8765`. Порт 8765 слушает только loopback;
внешние подключения проходят через Caddy на портах 80/443.

Это общая библиотека на один процесс: одна сборка одновременно. Нет отдельных учётных
записей и изоляции данных между людьми с веб-паролем.
Лимиты входа: PPTX до 25 МиБ и 250 слайдов, исходный текст до 100 000 символов.

## Подключение постоянной библиотеки

Шаблон systemd включает `EXPOSLIDES_FILE_SERVICE=127.0.0.1:50051` и
`EXPOSLIDES_DATA_DIR=/home/alex/exposlides/shared/library`. Это конфигурация для
установки; её применение и запуск хранилища на сервере здесь не подтверждены.
Перед установкой шаблона нужен работающий `file-service` с доступными MinIO и
PostgreSQL. gRPC-порт должен быть доступен веб-серверу по loopback и закрыт извне.
Создайте каталог библиотеки под пользователем `alex`:

```bash
install -d -m 700 /home/alex/exposlides/shared/library
```

Оба параметра задаются вместе. В этом режиме загруженные шаблоны и завершённые
презентации сохраняются через `file-service`: PPTX — в MinIO, метаданные и версии —
в PostgreSQL. Локальный `shared/library/library.json` хранит каталог и ссылки
на конкретные версии файлов. После перезапуска они вновь доступны в интерфейсе;
PPTX загружаются при обращении к ним, предпросмотр строится заново.

Сохраняйте каталог `shared/library` при смене версии приложения и резервируйте
его вместе с данными MinIO и PostgreSQL. Одной копии MinIO недостаточно для
восстановления библиотеки. Используйте один процесс веб-сервера на этот каталог.
Незавершённая генерация после перезапуска не возобновляется; сохраняются только
готовые результаты. Промежуточные файлы, предпросмотр и журналы остаются временными.

Если постоянное хранилище ещё не подготовлено, удалите обе строки `EXPOSLIDES_*`
из устанавливаемого шаблона systemd: без них файлы сессии временные и результаты
нужно скачать до остановки, обновления или перезапуска. Уже загруженные файлы
временного сеанса автоматически в постоянную библиотеку не переносятся.

## Настройка генерации

Приложение использует Hugging Face Inference Providers с моделью
`Qwen/Qwen3.8-27B:deepinfra`. Нужен токен Hugging Face с разрешением
**Inference Providers**, созданный на [странице токенов](https://huggingface.co/settings/tokens).
API платный после исчерпания небольшого ежемесячного кредита; тарифы и ссылки есть в
[корневом README](../../README.md). Ключ OpenRouter для этого API не подходит.

Проверки нового релиза и путь отката: [HUGGINGFACE-DEPLOY.md](HUGGINGFACE-DEPLOY.md).
История предыдущей проверки: [OPENROUTER-DEPLOY.md](OPENROUTER-DEPLOY.md): ключ OpenRouter
принят, но бесплатная модель отвечала HTTP 429 со стороны провайдера ModelRun.
Интерфейс и предпросмотр работают без ключа; для генерации он необходим.

Для безопасного ввода токена выполните на своём компьютере:

```bash
ssh -t alex-cloud-1 'bash /home/alex/exposlides/current/deploy/alex-cloud/set-huggingface-key.sh'
```

Вставьте токен `hf_…` в появившийся запрос и нажмите Enter. Ввод скрыт.
Скрипт атомарно сохраняет настройки с правами `600`, устанавливает адрес Hugging Face
и модель для обоих режимов, сохраняет остальные параметры и перезапускает службу.
Токен не нужно включать в команду или отправлять в переписку.

При ручном редактировании `/home/alex/exposlides/shared/content.env` задайте
`LLM_API_KEY` токеном Hugging Face и используйте следующие настройки:

```dotenv
LLM_BASE_URL=https://router.huggingface.co/v1
LLM_MODEL=Qwen/Qwen3.8-27B:deepinfra
LLM_FAST_MODEL=Qwen/Qwen3.8-27B:deepinfra
LLM_FAST_REPAIR_MODEL=Qwen/Qwen3.8-27B:deepinfra
LLM_REASONING_EFFORT=none
LLM_FAST_API_TIMEOUT=180
```

Удалите старые `LLM_SCOPE` и `GIGACHAT_CA_BUNDLE_FILE`. Сохраните файл с правами `600`
и выполните `sudo systemctl restart exposlides`.
Не добавляйте ключ или веб-пароль в команды, Git, логи и переписку.
Служба принудительно задаёт `LOG_LEVEL=INFO`: DEBUG может раскрывать исходные тексты
и ответы модели.

## Проверка и обслуживание

Команды на сервере:

```bash
readlink -f /home/alex/exposlides/current
sudo systemctl is-active exposlides caddy
sudo systemctl status exposlides --no-pager
curl --fail --silent --output /dev/null --write-out '%{http_code}\n' http://127.0.0.1:8765/
sudo caddy validate --config /etc/caddy/Caddyfile
sudo journalctl -u exposlides -n 50 --no-pager
```

Проверка с локального компьютера: первый запрос должен вернуть `401`, второй
запросит пароль интерактивно и после успешного входа должен вернуть `200`.

```bash
curl --silent --output /dev/null --write-out '%{http_code}\n' https://exposlides.158-160-217-249.sslip.io/
curl --user alex --fail --silent --output /dev/null --write-out '%{http_code}\n' https://exposlides.158-160-217-249.sslip.io/
```

Проверьте в браузере загрузку примера и предпросмотр. Проверка полного сценария
включает генерацию, скачивание PPTX и повторное открытие презентации; один HTTP 200
не подтверждает работу Hugging Face или сборки. Для постоянной библиотеки также
перезапустите службу, вновь выберите сохранённый шаблон и скачайте готовый результат:
они должны остаться доступны. Не публикуйте журналы целиком.

## Обновление и откат

Подготовьте проверенный снимок исходников в новом каталоге `releases/<версия>`.
Для незакоммиченных изменений недостаточно `git archive HEAD`: в снимок должны войти
и нужные новые файлы. Исключите `.git`, `.venv`, `.env`, ключи, локальные артефакты,
кэши и логи. Не заменяйте содержимое работающего `current` и каталог `shared`.

После загрузки нового снимка на сервер задайте его уникальное имя и выполните:

```bash
release_id=20260922-02
cd /home/alex/exposlides/releases/"$release_id"
uv python install 3.12
uv sync --locked
uv lock --check
uv run pytest
uv run ruff check .
```

Переключайте версию только после успешных проверок и завершения текущей генерации.
Во временном режиме сначала скачайте результаты; в постоянном проверьте резервную
копию каталога библиотеки и данных хранилища.
Следующие команды выполняются на сервере в том же сеансе; сохраните значение
`previous_release` для возможного отката:

```bash
previous_release=$(readlink -f /home/alex/exposlides/current)
test -x "/home/alex/exposlides/releases/$release_id/.venv/bin/python" || exit 1
ln -s "/home/alex/exposlides/releases/$release_id" "/home/alex/exposlides/current-$release_id" || exit 1
mv -Tf "/home/alex/exposlides/current-$release_id" /home/alex/exposlides/current
sudo systemctl restart exposlides
```

Повторите проверки доступности. Если менялся шаблон systemd, отдельно установите
его в `/etc/systemd/system/exposlides.service`, выполните
`sudo systemctl daemon-reload` и перезапустите службу. Конфигурацию Caddy меняйте
через `sudoedit /etc/caddy/exposlides.caddy`; после успешной проверки
`sudo caddy validate --config /etc/caddy/Caddyfile` выполните
`sudo systemctl reload caddy`. Сохраняйте рабочий хеш пароля.

Откат приложения возможен только к существующей проверенной предыдущей версии.
При самом первом развертывании предыдущей версии нет. Для последующих обновлений
в том же сеансе, где сохранён `previous_release`:

```bash
test -n "$previous_release" && test -d "$previous_release" && test -x "$previous_release/.venv/bin/python" || exit 1
ln -s "$previous_release" /home/alex/exposlides/current-rollback || exit 1
mv -Tf /home/alex/exposlides/current-rollback /home/alex/exposlides/current
sudo systemctl restart exposlides
```

Для отмены публикации остановите ExpoSlides и удалите только импорт
`/etc/caddy/exposlides.caddy` из основного Caddyfile, затем проверьте и перезагрузите
Caddy. Восстановление резервной копии основного Caddyfile допустимо лишь после
проверки, что после установки в него не внесены другие изменения; иначе сохраните
их и удалите только импорт ExpoSlides. Остальные сайты и службы не затрагивайте.
