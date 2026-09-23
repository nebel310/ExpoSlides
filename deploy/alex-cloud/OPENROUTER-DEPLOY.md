# OpenRouter: развёртывание 22 сентября 2026

Установлен `/home/alex/exposlides/releases/20260922-openrouter-01`.
Ссылка `/home/alex/exposlides/current` переключена на него; службы `exposlides`
и `caddy` активны, `NRestarts=0` после проверки. Конфигурация Caddy и systemd
не заменялась. Постоянное хранилище этим развёртыванием не включалось.

Новый релиз содержит текущий проверенный снимок приложения, включая незакоммиченные
исходники. Секреты, `.git`, локальная `.venv`, журналы, пользовательские PPTX и
локальные артефакты в снимок не включались. Зависимости установлены через
`uv sync --locked` в отдельную `.venv` нового релиза.

`shared/content.env` обновлён для OpenRouter и `qwen/qwen3.8-27b:free` во всех трёх
настройках модели. На момент развёртывания `LLM_API_KEY` оставлен пустым до ввода нового ключа.
Остальные настройки сохранены; права файла — `600`. Локальный
`services/content-service/.env` не читался и не изменялся.

## Ввод ключа

```bash
ssh -t alex-cloud-1 'bash /home/alex/exposlides/current/deploy/alex-cloud/set-openrouter-key.sh'
```

Скрипт запрашивает ключ без отображения, записывает его атомарно с правами `600`,
перезапускает ExpoSlides и проверяет активность службы. Реальный запрос к Qwen
в ходе развёртывания не выполнялся. Для проверки генерации после ввода ключа
нужно создать презентацию на сайте.

## Проверки

Из каталога нового релиза на сервере выполнены:

```bash
uv sync --locked
uv lock --check
uv run --offline pytest
uv run --offline ruff check services/content-service/app/chains/llm.py services/content-service/app/chains/openrouter.py services/content-service/app/config.py services/content-service/app/errors.py exposlides/web.py tests/test_openrouter_generation.py tests/test_openrouter_transport.py tests/test_openrouter_key_setup.py
bash -n deploy/alex-cloud/set-openrouter-key.sh
```

Установка и проверка lock-файла успешны. Финальный pytest: **957 passed in 23.32s**.
Целевой Ruff и синтаксис скрипта — успешно. Общий Ruff не является чистым baseline:
предыдущая локальная проверка обнаружила 45 существующих замечаний вне миграции.

После переключения выполнены `systemctl show exposlides -p ActiveState -p SubState
-p NRestarts`, `systemctl is-active caddy` и проверка сайта через HTTPS с существующей
авторизацией. Пароль использован только внутри серверного проверочного процесса.

| Проверка | Результат |
| --- | --- |
| Публичный запрос без пароля | HTTP 401 |
| Страница с авторизацией | HTTP 200, интерфейс OpenRouter |
| Загрузка искусственного PPTX с одним слайдом | HTTP 201 |
| Предпросмотр | `ready`, PNG — HTTP 200 |
| API библиотеки | HTTP 200 |
| Служба приложения | `active`, `running`, `NRestarts=0` |

Проверочный PPTX создан программно; пользовательские материалы не использовались.
Это проверка сайта и обработки PPTX, а не реальная генерация через OpenRouter.

## Реальная проверка после ввода ключа

22 сентября 2026 по запросу владельца запущена генерация встроенного квартального
примера на пять слайдов через публичный HTTPS API сайта. Создание задачи вернуло
HTTP 202, парсинг прошёл. Через 3,8 секунды задача завершилась ошибкой `auth`
на этапе генерации контента; итоговый PPTX не создан.

В работающем процессе ключ присутствует, адрес API и все модели соответствуют
OpenRouter/Qwen. Значение ключа не выводилось. Дополнительный прямой запрос
`GET https://openrouter.ai/api/v1/key` с тем же ключом вернул **HTTP 401**;
безопасная категория ответа — `missing_authentication`. Ключ не принят OpenRouter.
Формат настроенного значения не имеет префикса `sk-or-`.

Сайт остаётся активным, локальный HTTP отвечает 200, `NRestarts=0`.
Для продолжения нужно повторно выполнить команду из раздела «Ввод ключа» с
действующим API-ключом OpenRouter. Код приложения в ходе этой проверки не менялся.
Идентификатор проверочной задачи: `14a1babeb956455b9de9d64fa4a10bbb`.
На сервере сохранён только несекретный итог проверки:
`/home/alex/exposlides/shared/verification/openrouter-20260922/summary.json`.

### Повторная проверка с новым ключом

После обновления ключа повторена генерация того же встроенного примера.
Теперь `GET /api/v1/key` возвращает **HTTP 200**: ключ принят, дневной счётчик
бесплатных запросов на момент проверки — 0 из 50. Менять ключ больше не требуется.

Задача `89e6e578d1484c56972bbbe68f11e144` прошла парсинг, но завершилась через
7,1 секунды на этапе контента с кодом `network`. В журнале зафиксированы HTTP 429
после ограниченных повторов. Отдельный минимальный запрос к той же модели с
JSON Schema и лимитом 32 токена также получил HTTP 429 от провайдера **ModelRun**.
Причина провайдера: бесплатная `qwen/qwen3.8-27b:free` временно ограничена
на стороне upstream; заголовок `Retry-After` отсутствовал.

Итоговый PPTX не создан из-за ограничения провайдера. Приложение остаётся активным,
`NRestarts=0`; модель и конфигурация не менялись. Повторять проверку следует после
восстановления доступности модели. Результат задачи сохранён в
`/home/alex/exposlides/shared/verification/openrouter-20260922/89e6e578d1484c56972bbbe68f11e144/summary.json`.

## Резервная копия и откат

До переключения сохранены прежние настройки и файлы временного сеанса:
`/home/alex/exposlides/shared/deploy-backups/20260922-openrouter-01` (права `700`).
Результаты прошлого временного сеанса не переносятся в новый интерфейс;
они сохранены в этой копии. Предыдущий релиз — `20260922-01` — оставлен на месте.

Для возврата прежнего приложения и прежних LLM-настроек на сервере:

```bash
cp -p /home/alex/exposlides/shared/deploy-backups/20260922-openrouter-01/content.env /home/alex/exposlides/shared/content.env
ln -s /home/alex/exposlides/releases/20260922-01 /home/alex/exposlides/current-openrouter-rollback
mv -Tf /home/alex/exposlides/current-openrouter-rollback /home/alex/exposlides/current
sudo systemctl restart exposlides
```

Этот откат восстанавливает ключ и настройки GigaChat из резервной копии.
Если после развёртывания в `content.env` появились другие нужные изменения,
сохраните их перед восстановлением файла.

## Файлы, добавленные или обновлённые для развёртывания

- `deploy/alex-cloud/set-openrouter-key.sh` — безопасный интерактивный ввод ключа.
- `tests/test_openrouter_key_setup.py` — восемь офлайн-проверок скрипта.
- `deploy/alex-cloud/README.md` — команда настройки и установленный релиз.
- `deploy/alex-cloud/OPENROUTER-DEPLOY.md` — этот отчёт.

Локально также выполнены `git diff --check`, `bash -n deploy/alex-cloud/set-openrouter-key.sh`
и `UV_CACHE_DIR=/private/tmp/exposlides-uv-cache uv run ruff check tests/test_openrouter_key_setup.py`;
проверки успешны.
