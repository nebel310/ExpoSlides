# Gateway Service

API-шлюз ExpoSlides. Единственная точка входа для фронтенда. Принимает файлы, создаёт задачи на генерацию презентации, слушает события пайплайна через Kafka и транслирует статусы во фронт через WebSocket.

## Роль в системе

Стоит между фронтом (Streamlit) и внутренними сервисами (parser, content, builder). Фронт общается только с gateway. Внутри gateway по gRPC ходит в file-service, по Kafka продюсит `task.created` и слушает остальные топики.

```
Streamlit ──HTTP──▶ Gateway ──gRPC──▶ file-service (MinIO + Postgres)
                      │
                      ├──Kafka produce──▶ task.created
                      │
                      └──Kafka consume──◀ task.parsed
                                        task.content_ready
                                        task.built
                                        task.failed
```

## Что делает

- Хранит анонимные сессии в Redis, идентифицирует пользователя по cookie `exposlides_sid`
- Проксирует загрузку и скачивание файлов в `file-service` по gRPC
- Публикует `task.created` в Kafka
- Слушает `task.parsed`, `task.content_ready`, `task.built`, `task.failed`
- Обновляет статус задачи в Redis и пушит событие в комнату сессии через Socket.IO
- Позволяет пережить F5: cookie сохраняется в браузере, список задач восстанавливается через `GET /api/tasks`

## Запуск

Из корня проекта

```
docker compose up -d --build redis gateway-service
```

Сервис доступен на `http://localhost:1000`.

Проверка живости

```
curl http://localhost:1000/health
```

Ответ

```json
{"status": "ok"}
```

## Переменные окружения

| Переменная | Значение по умолчанию | Описание |
|---|---|---|
| `GATEWAY_SERVICE_PORT` | `1000` | Порт, который публикует docker-compose |
| `GATEWAY_PORT` | `1000` | Порт внутри сервиса |
| `REDIS_URL` | `redis://redis:6379/0` | Адрес Redis |
| `REDIS_SESSION_TTL` | `2592000` | TTL сессии в секундах (30 дней) |
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Адрес брокера |
| `GATEWAY_KAFKA_GROUP_ID` | `gateway-service` | Group id консьюмера |
| `KAFKA_TOPIC_TASK_CREATED` | `task.created` | Топик для продюсинга |
| `KAFKA_TOPIC_TASK_PARSED` | `task.parsed` | Слушаем |
| `KAFKA_TOPIC_TASK_CONTENT_READY` | `task.content_ready` | Слушаем |
| `KAFKA_TOPIC_TASK_BUILT` | `task.built` | Слушаем |
| `KAFKA_TOPIC_TASK_FAILED` | `task.failed` | Слушаем |
| `FILE_SERVICE_GRPC_HOST` | `file-service` | Адрес file-service |
| `FILE_SERVICE_GRPC_PORT` | `50051` | Порт file-service |
| `MAX_UPLOAD_SIZE` | `52428800` | Максимальный размер файла (50 МБ) |
| `COOKIE_NAME` | `exposlides_sid` | Имя cookie сессии |
| `COOKIE_MAX_AGE` | `2592000` | Время жизни cookie в секундах |
| `LOG_LEVEL` | `INFO` | Уровень логирования |

## Модель сессии

Авторизации нет. Идентификация — по анонимной cookie.

1. Фронт один раз при старте вызывает `POST /api/session/bootstrap`
2. Если cookie нет — сервер создаёт новый `sid`, ставит cookie `exposlides_sid` (HttpOnly, SameSite=Lax)
3. Если cookie есть и валидна — сервер возвращает тот же `sid`, обновляет TTL
4. Все дальнейшие HTTP-запросы от браузера автоматически идут с cookie
5. Для WebSocket `sid` передаётся явно в `auth`, потому что Socket.IO не отправляет cookies автоматически в некоторых сценариях

При F5:

- Cookie остаётся в браузере
- Фронт повторно вызывает `POST /api/session/bootstrap` (получает тот же `sid`)
- Фронт вызывает `GET /api/tasks` — получает все задачи пользователя со статусами
- Фронт подключает WebSocket и продолжает получать события

## Статусы задачи

| Статус | Когда наступает |
|---|---|
| `queued` | Сразу после `POST /api/tasks` |
| `generating_content` | Пришло событие `task.parsed` |
| `building` | Пришло событие `task.content_ready` |
| `done` | Пришло событие `task.built` |
| `failed` | Пришло событие `task.failed` |

`task.built` появляется только когда builder-service готов (в текущей версии продюсинга может не быть, статус остановится на `building`).

## HTTP API

Базовый URL: `http://localhost:1000`

Все ответы — JSON. Ошибки — `{"detail": "..."}`.

### POST /api/session/bootstrap

Создаёт или обновляет сессию. Устанавливает cookie `exposlides_sid`.

Тело: пустое.

Успех `200`:

```json
{"sid": "a75dff6b-6107-46b0-b61d-9a070da0070c"}
```

Заголовок ответа: `Set-Cookie: exposlides_sid=...; HttpOnly; SameSite=Lax; Max-Age=2592000; Path=/`.

### GET /api/session/me

Возвращает текущий `sid` из cookie.

Требует: cookie.

Успех `200`:

```json
{"sid": "a75dff6b-6107-46b0-b61d-9a070da0070c"}
```

Ошибки:

- `401` — cookie нет или сессия истекла

### POST /api/files/upload

Загружает файл в file-service. Принимает `multipart/form-data` с полем `file`.

Требует: cookie.

Ограничения:

- Размер ≤ `MAX_UPLOAD_SIZE` (50 МБ)
- Допустимые типы (проверяются по содержимому, не по расширению): `pptx`, `pdf`, `json`, `txt`, `png`, `jpg`, `gif`, `bmp`, `tiff`, `emf`, `wmf`, `svg`, `webp`

Пример:

```bash
curl -X POST http://localhost:1000/api/files/upload \
  -H "Cookie: exposlides_sid=a75dff6b-..." \
  -F "file=@template.pptx"
```

Успех `200`:

```json
{
  "file_id": "7b3c...",
  "filename": "template.pptx",
  "size": 245891,
  "content_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "version": 1
}
```

Ошибки:

- `401` — нет сессии
- `413` — файл слишком большой
- `502` — file-service вернул ошибку (неверный тип, MinIO недоступен)

### GET /api/files/{file_id}

Скачивает файл из file-service. Возвращает байты с `Content-Type` из file-service.

Требует: cookie.

Пример:

```bash
curl -OJ http://localhost:1000/api/files/7b3c... \
  -H "Cookie: exposlides_sid=a75dff6b-..."
```

Ошибки:

- `401` — нет сессии
- `404` — файл не найден в file-service

### POST /api/tasks

Создаёт задачу на генерацию презентации.

Требует: cookie.

Тело:

```json
{
  "template_file_id": "7b3c...",
  "script_file_id": "9d1a..."
}
```

Оба `file_id` должны быть получены ранее через `POST /api/files/upload`.

Успех `200`:

```json
{"task_id": "77e75e75-9803-4286-acc1-5c2a6fee12c2"}
```

Внутри: gateway сохраняет задачу в Redis со статусом `queued` и публикует в Kafka `task.created` с payload:

```json
{
  "task_id": "77e75e75-...",
  "attempt": 1,
  "payload": {
    "template_file_id": "7b3c...",
    "script_file_id": "9d1a...",
    "session_id": "a75dff6b-..."
  },
  "error": null
}
```

Ошибки:

- `401` — нет сессии
- `422` — невалидное тело

### GET /api/tasks

Возвращает список всех задач текущей сессии.

Требует: cookie.

Успех `200`:

```json
{
  "tasks": [
    {
      "task_id": "77e75e75-...",
      "status": "done",
      "template_file_id": "7b3c...",
      "script_file_id": "9d1a...",
      "structure_file_id": "aa12...",
      "content_file_id": "bb34...",
      "result_file_id": "cc56...",
      "error": null,
      "created_at": 1727188800.123,
      "updated_at": 1727189012.456
    }
  ]
}
```

Сортировка: по `created_at`, новые сверху.

Ошибки:

- `401` — нет сессии

### GET /api/tasks/{task_id}

Возвращает одну задачу.

Требует: cookie.

Успех `200` — объект задачи (см. выше).

Ошибки:

- `401` — нет сессии
- `404` — задача не найдена или принадлежит другой сессии

## WebSocket

URL: `ws://localhost:1000/ws/` (Socket.IO протокол).

Подключение:

```python
import socketio

sio = socketio.AsyncClient()
await sio.connect(
    "http://localhost:1000",
    socketio_path="ws",
    auth={"sid": "a75dff6b-..."},
)
```

Сервер проверяет `sid` при подключении. Если `sid` не передан или неизвестен — соединение отклоняется.

После подключения сокет автоматически добавляется в комнату `sid`, поэтому события приходят только этому пользователю.

### События

Все события имеют одинаковый формат payload:

```json
{
  "task_id": "77e75e75-...",
  "status": "generating_content",
  "payload": {
    "structure_file_id": "aa12...",
    "content_file_id": "bb34...",
    "result_file_id": "cc56...",
    "error": null
  }
}
```

| Событие | Status | Что означает |
|---|---|---|
| `task.parsed` | `generating_content` | parser-service закончил, началась генерация контента |
| `task.content_ready` | `building` | контент готов, началась сборка pptx |
| `task.built` | `done` | pptx готов, можно скачать по `result_file_id` |
| `task.failed` | `failed` | что-то упало, причина в `payload.error` |

Пример подписки:

```python
@sio.on("task.built")
async def on_built(data):
    task_id = data["task_id"]
    result_file_id = data["payload"]["result_file_id"]
    print(f"Готово: {task_id} -> {result_file_id}")
```

## Полный сценарий интеграции

```python
import asyncio
import socketio
import httpx

BASE = "http://localhost:1000"

async def run():
    async with httpx.AsyncClient(base_url=BASE) as http:
        await http.post("/api/session/bootstrap")

        with open("template.pptx", "rb") as f:
            template_resp = await http.post(
                "/api/files/upload",
                files={"file": ("template.pptx", f, "application/octet-stream")},
            )
        template_file_id = template_resp.json()["file_id"]

        with open("script.txt", "rb") as f:
            script_resp = await http.post(
                "/api/files/upload",
                files={"file": ("script.txt", f, "text/plain")},
            )
        script_file_id = script_resp.json()["file_id"]

        task_resp = await http.post(
            "/api/tasks",
            json={
                "template_file_id": template_file_id,
                "script_file_id": script_file_id,
            },
        )
        task_id = task_resp.json()["task_id"]

        me = await http.get("/api/session/me")
        sid = me.json()["sid"]

        sio = socketio.AsyncClient()

        @sio.on("task.built")
        async def on_built(data):
            if data["task_id"] != task_id:
                return
            file_id = data["payload"]["result_file_id"]
            result = await http.get(f"/api/files/{file_id}")
            with open("result.pptx", "wb") as out:
                out.write(result.content)
            print("Файл сохранён")
            await sio.disconnect()

        @sio.on("task.failed")
        async def on_failed(data):
            if data["task_id"] != task_id:
                return
            print("Ошибка:", data["payload"]["error"])
            await sio.disconnect()

        await sio.connect(BASE, socketio_path="ws", auth={"sid": sid})
        await sio.wait()

asyncio.run(run())
```

## Коды ошибок

| Код | Когда |
|---|---|
| `200` | Успех |
| `401` | Нет cookie или сессия истекла |
| `404` | Задача/файл не найдены, либо принадлежат другой сессии |
| `413` | Файл больше `MAX_UPLOAD_SIZE` |
| `422` | Невалидное тело запроса (Pydantic) |
| `502` | file-service вернул ошибку |

## Восстановление после F5

Фронт при загрузке страницы:

1. `POST /api/session/bootstrap` — получает тот же `sid` из cookie
2. `GET /api/tasks` — получает список задач с актуальными статусами
3. Для активных задач (`queued`, `generating_content`, `building`) — открывает WebSocket и слушает события
4. Для завершённых (`done`) — показывает кнопку «Открыть» → `GET /api/files/{result_file_id}`
5. Для упавших (`failed`) — показывает текст ошибки

## CORS

Разрешены любые источники (`allow_origins=["*"]`), `allow_credentials=True`. Если Streamlit крутится на другом порту — запросы пройдут.

Cookie `SameSite=Lax` — работает для same-site и top-level navigation. Если Streamlit будет на другом домене, cookie придётся сменить на `SameSite=None; Secure=True` и перейти на HTTPS.

## Ограничения текущей версии

- Пароля/логина нет — только анонимные сессии
- `task.built` сейчас никто не продюсит: builder-service подключается отдельно, статус может остановиться на `building`
- Формат результата — только `.pptx`. Экспорт в `.pdf`/`.html` появится позже
- Если gateway перезапустится — консьюмер начнёт читать с `auto_offset_reset="latest"` и пропустит события, которые были в момент падения. Задачи в Redis сохранятся, но статус не обновится

## Полезные команды

Проверка живости:

```bash
curl http://localhost:1000/health
```

Просмотр логов:

```bash
docker compose logs -f gateway-service
```

Ручной bootstrap и создание задачи в одном окне:

```bash
curl -c /tmp/cookies.txt -X POST http://localhost:1000/api/session/bootstrap
curl -b /tmp/cookies.txt -F "file=@template.pptx" http://localhost:1000/api/files/upload
curl -b /tmp/cookies.txt -X POST http://localhost:1000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"template_file_id": "...", "script_file_id": "..."}'
curl -b /tmp/cookies.txt http://localhost:1000/api/tasks
```

## Что нужно фронту (Streamlit)

Минимальный набор для интеграции:

- HTTP-клиент (httpx/requests)
- Socket.IO клиент (python-socketio)
- Один `POST /api/session/bootstrap` при старте приложения
- Два `POST /api/files/upload` для template и script
- Один `POST /api/tasks` для создания задачи
- Один `GET /api/tasks` для восстановления списка после перезагрузки
- Один WebSocket на всё приложение, слушает `task.*` и фильтрует по `task_id`
- Один `GET /api/files/{file_id}` для скачивания результата

Никакой авторизации, никаких токенов — всё через cookie, которую браузер шлёт автоматически.