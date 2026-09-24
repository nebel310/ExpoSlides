# Gateway Service

API-шлюз ExpoSlides. Принимает файлы, создаёт задачи, слушает Kafka и транслирует статусы во фронт через WebSocket.

## Что делает

- Хранит анонимные сессии в Redis, идентифицирует пользователя по cookie `exposlides_sid`.
- Проксирует загрузку и скачивание файлов в `file-service` по gRPC.
- Публикует `task.created` в Kafka.
- Слушает `task.parsed`, `task.content_ready`, `task.built`, `task.failed`.
- Обновляет статус задачи в Redis и пушит событие в комнату сессии через Socket.IO.

## Запуск

Из корня проекта

    docker compose up -d --build redis gateway-service

Сервис доступен на `localhost:1000`.

## HTTP API

- `POST /api/session/bootstrap` — создать или обновить сессию
- `GET /api/session/me` — вернуть текущий sid
- `POST /api/files/upload` — multipart `file`, проксирует в file-service
- `GET /api/files/{file_id}` — скачать файл
- `POST /api/tasks` — тело `{template_file_id, script_file_id}`, возвращает `task_id`
- `GET /api/tasks` — список задач сессии
- `GET /api/tasks/{task_id}` — одна задача

## WebSocket

- URL: `ws://localhost:1000/ws/` (Socket.IO протокол)
- Auth: `auth={"sid": "<sid>"}`
- События: `task.parsed`, `task.content_ready`, `task.built`, `task.failed`
- Payload: `{task_id, status, payload: {structure_file_id, content_file_id, result_file_id, error}}`

## Переменные окружения

    REDIS_URL=redis://redis:6379/0
    KAFKA_BOOTSTRAP_SERVERS=kafka:9092
    KAFKA_GROUP_ID=gateway-service
    KAFKA_TOPIC_TASK_CREATED=task.created
    KAFKA_TOPIC_TASK_PARSED=task.parsed
    KAFKA_TOPIC_TASK_CONTENT_READY=task.content_ready
    KAFKA_TOPIC_TASK_BUILT=task.built
    KAFKA_TOPIC_TASK_FAILED=task.failed
    FILE_SERVICE_GRPC_HOST=file-service
    FILE_SERVICE_GRPC_PORT=50051
    MAX_UPLOAD_SIZE=52428800
    GATEWAY_PORT=1000