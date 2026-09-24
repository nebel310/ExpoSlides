# Content service: формат результата

CLI (`app.main.run`) и сетевой `ContentPipeline` сохраняют один формат JSON:

```json
{
  "content": {
    "1": {"placeholders": {"0": "Заголовок"}, "notes": null}
  },
  "validation_report": {"ok": true, "issues": []},
  "error": null
}
```

Ключи `content` — исходные 1-based индексы слайдов шаблона, ключи `placeholders` —
строковый `placeholder_idx` (либо имя, если индекс отсутствует). Порядок слайдов
сохраняется. Этот файл читает `GeneratedContent` в builder-service.

Сетевой pipeline загружает файл `content.json` в file-service и публикует его
`content_file_id` в `task.content_ready`. Формат Kafka-сообщения не меняется.
При ошибке генерации публикуется `task.failed`; успешный файл не создаётся.

Ранее сетевой pipeline сохранял только внутренний словарь слайдов без `content`.
Уже сохранённые файлы автоматически не мигрируют: их следует сгенерировать заново
либо явно обернуть в `content` с `validation_report: null` и `error: null`.
CLI-формат остаётся прежним. Для совместимости с подменяемой доменной функцией
`ContentGenerationResult.validation_report` необязателен; реальная генерация
передаёт отчёт графа, а отсутствующий отчёт сохраняется как `null`.

Офлайн-проверка единого формата (включая повторный сетевой запрос и чтение builder):

```bash
uv run pytest tests/test_content_service_main.py
```

Генерация трёх альтернатив и сетевой запуск builder этим контрактом не реализуются.

## Feedback при внешнем retry

При `task.content_retry` pipeline скачивает UTF-8 feedback по `feedback_file_id`.
Домен сохраняет его в `ContentGraphState.feedback`: замечания передаются в
планирование и генерацию текста, включая повторные запросы после ошибок валидации.
Исходный `script` остаётся неизменным; анализ и grounding используют только его.
Числа и другие утверждения из feedback не становятся подтверждёнными фактами.
Противоречащие источнику замечания не разрешают отключить проверки.

Поле состояния используется также планированием, пакетной генерацией и исправлением
контента fast-режима. При отсутствии feedback прежние промпты не меняются.
Сетевой домен по-прежнему использует standard-режим. Внешний retry строит новую
презентацию: предыдущий сгенерированный файл в его контракте не передаётся.

Проверки: `uv run pytest tests/test_content_feedback.py tests/test_content_service_main.py tests/test_fast_generation.py`.
