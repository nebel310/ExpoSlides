# File Service

gRPC-микросервис для хранения файлов в MinIO с метаданными в PostgreSQL.
Поддерживает версионирование, валидацию по содержимому и типы: `pptx`, `pdf`, `json`, `txt`.

## Что делает

- Принимает файлы по gRPC, валидирует содержимое (не по расширению) и сохраняет в MinIO.
- Хранит метаданные (имя, размер, тип, `task_id`, версия) в PostgreSQL.
- Поддерживает версионирование: одна загрузка — одна версия.
- Отдаёт файлы по `file_id` и номеру версии (`0` — последняя).
- Удаляет файл вместе со всеми версиями.

## gRPC API

Порт: `50051`. Контракт: `proto/file_service.proto`.

### UploadFile

Загружает новую версию файла или создаёт новый файл.

**Запрос:**
- `filename` — оригинальное имя (расширение должно совпадать с типом содержимого)
- `content` — байты файла
- `content_type` — MIME-тип (опционально)
- `task_id` — идентификатор задачи (опционально)
- `file_id` — если указан, создаётся новая версия существующего файла; иначе создаётся новый

**Ответ:**
- `file_id`, `original_name`, `size`, `file_type`, `version`

**Ошибки:**
- `INVALID_ARGUMENT` — содержимое не соответствует ни одному разрешённому типу или расширение не совпадает
- `RESOURCE_EXHAUSTED` — файл больше `MAX_UPLOAD_SIZE`
- `NOT_FOUND` — передан `file_id`, которого нет в БД

### DownloadFile

Скачивает конкретную версию файла.

**Запрос:** `file_id`, `version` (`0` — последняя)
**Ответ:** `content`, `filename`, `content_type`, `version`
**Ошибки:** `NOT_FOUND`

### GetFileInfo

Возвращает метаданные файла без содержимого.

**Запрос:** `file_id`, `version` (`0` — последняя)
**Ответ:** `file_id`, `original_name`, `object_key`, `content_type`, `size`, `task_id`, `created_at`, `version`
**Ошибки:** `NOT_FOUND`

### DeleteFile

Удаляет файл и все его версии (из MinIO и БД).

**Запрос:** `file_id`
**Ответ:** пусто (`google.protobuf.Empty`)
**Ошибки:** `NOT_FOUND`

### HealthCheck

Проверка живости сервиса. Возвращает `status = "ok"`.

## Правила валидации

Тип определяется по содержимому, а не по расширению:
- `pptx` — ZIP с `[Content_Types].xml` и папкой `ppt/`
- `pdf` — начинается с `%PDF`
- `json` — валидный JSON в UTF-8
- `txt` — валидный UTF-8 без нулевых байтов

Дополнительно расширение в `filename` должно совпадать с определённым типом.

## Версионирование

- Первая загрузка: `version = 1`, ключ в MinIO `{file_id}/v1{ext}`.
- Повторная загрузка с тем же `file_id`: `version = max + 1`, ключ `{file_id}/v{version}{ext}`.
- Скачивание с `version = 0` возвращает последнюю версию.
- Удаление по `file_id` убирает все версии сразу.

## Переменные окружения

```
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=files
MAX_UPLOAD_SIZE=52428800
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/files
```

## Запуск

Из корня проекта:

```bash
docker compose up -d --build
```

Сервис доступен на `localhost:50051`.

## Генерация gRPC-кода

При изменении `proto/file_service.proto`:

```bash
python -m grpc_tools.protoc -Iproto --python_out=services/file-service --grpc_python_out=services/file-service proto/file_service.proto
```

В Docker-образе генерация выполняется автоматически при сборке.

## Тесты

```bash
uv run pytest services/file-service/tests -v
```

Требуют запущенных контейнеров `file-service`, `minio`, `postgres`.

## Пример использования (Python)

```python
import grpc
from file_service_pb2 import UploadFileRequest, DownloadFileRequest
from file_service_pb2_grpc import FileServiceStub

channel = grpc.insecure_channel("localhost:50051")
stub = FileServiceStub(channel)

with open("template.pptx", "rb") as f:
    response = stub.UploadFile(UploadFileRequest(
        filename="template.pptx",
        content=f.read(),
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        task_id="task-123",
    ))
print(response.file_id, response.version)

data = stub.DownloadFile(DownloadFileRequest(file_id=response.file_id, version=0))
```