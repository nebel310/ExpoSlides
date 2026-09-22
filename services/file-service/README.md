# File Service

gRPC-микросервис для хранения файлов в MinIO с метаданными в PostgreSQL.
Поддерживает версионирование, валидацию по содержимому и типы:
`pptx`, `pdf`, `json`, `txt`, `png`, `jpg`, `gif`, `bmp`, `tiff`, `emf`, `wmf`, `svg`, `webp`.

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
- `filename` — оригинальное имя (расширение должно соответствовать типу содержимого)
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

Тип определяется по содержимому (по магическим байтам), а не по расширению.

### Документы

- `pptx` — ZIP с `[Content_Types].xml` и папкой `ppt/`
- `pdf` — начинается с `%PDF`
- `json` — валидный JSON в UTF-8
- `txt` — валидный UTF-8 без нулевых байтов

### Растровые изображения

- `png` — `\x89PNG\r\n\x1a\n`
- `jpg` — `\xFF\xD8\xFF`; принимаются расширения `.jpg` и `.jpeg`
- `gif` — `GIF87a` или `GIF89a`
- `bmp` — `BM`
- `tiff` — `II*\x00` (little-endian) или `MM\x00*` (big-endian);
  принимаются расширения `.tiff` и `.tif`
- `webp` — `RIFF` + `WEBP` на смещении 8

### Векторная графика и метафайлы Windows

- `emf` — `\x01\x00\x00\x00` и сигнатура ` EMF` на смещении 40
- `wmf` — `\xD7\xCD\xC6\x9A` (placeable) или `\x01\x00\x09\x00` (standard)
- `svg` — начинается с `<?xml` или `<svg`

### Проверка расширения

После определения типа расширение из `filename` сверяется со списком
допустимых для этого типа (в нижнем регистре):

| Тип    | Допустимые расширения  |
|--------|------------------------|
| pptx   | `.pptx`                |
| pdf    | `.pdf`                 |
| json   | `.json`                |
| txt    | `.txt`                 |
| png    | `.png`                 |
| jpg    | `.jpg`, `.jpeg`        |
| gif    | `.gif`                 |
| bmp    | `.bmp`                 |
| tiff   | `.tiff`, `.tif`        |
| emf    | `.emf`                 |
| wmf    | `.wmf`                 |
| svg    | `.svg`                 |
| webp   | `.webp`                |

Если тип содержимого не распознан или расширение не входит в список
допустимых — загрузка отклоняется с `INVALID_ARGUMENT`.

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
Если менял `validators.py` — не забудь `docker compose up -d --build file-service`,
иначе тесты будут ходить в старый контейнер.

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