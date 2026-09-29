# Полный релиз — 29 сентября 2026

Опубликовано: https://exposlides.158-160-217-249.sslip.io/.
Итоговый релиз `/home/alex/exposlides/releases/20260929-full-02` содержит полный снимок
текущей dev (HEAD 12f2991) и применённые исправления изображений, загрузки и планировщика.
Это снимок рабочей копии, а не новый Git-коммит. Push и commit не выполнялись.

Патчи применены в порядке image-api-20260928.patch → studio-upload-20260929.patch →
story-stream-20260929.patch. Исходники исправлений теперь находятся в основной
рабочей копии, а не только в изолированных кандидатах. Интерфейс пересобран из этих исходников.

Перед изменениями: 1412 основных тестов прошли, Ruff прошёл.
После объединения локально:

```bash
uv run --no-sync --offline pytest -p no:cacheprovider --tb=short
# 1439 passed, 8 предупреждений зависимостей, 23.82 с
uv run --no-sync --offline ruff check --no-cache .
# All checks passed!
uv lock --check --offline
# 109 пакетов, успешно
uv run --no-sync --offline python scripts/test_services.py
# parser 218 passed; content 89 passed; gateway 93 passed
cd frontend
npm ci --offline --ignore-scripts --no-audit --no-fund
npm test
# 41 passed
npm run build
# TypeScript и production bundle — успешно
```

На сервере в новом релизе:

```bash
uv sync --locked --offline
uv lock --check --offline
uv run --no-sync --offline pytest -p no:cacheprovider --tb=short
# 1439 passed, 1 предупреждение Starlette, 47.01 с
uv run --no-sync --offline ruff check --no-cache .
# All checks passed!
```

Новая сборка на сохранённом валидированном плане создала три варианта PPTX/PDF/HTML
за 23.30 с. Каждый PPTX повторно открыт python-pptx: 12 слайдов и непустой текст.
Результаты: `/home/alex/exposlides/shared/verification/full-20260929`.
В этом развёртывании новые платные запросы LLM/image не выполнялись; сохранён
проверенный ранее план. Это проверка сборки/экспорта, не новый LLM end-to-end запуск.

Перед переключением активных заданий не было. current переключён атомарно, служба
перезапущена. Все 7 прежних job.json сохранили SHA256; shared/studio не заменялся.
Конфигурация модели подключена ссылкой на прежний shared/content.env, без чтения
или копирования секретов в релизный архив. Настройки Caddy и systemd сохранены.
Архив содержит 377 исходных файлов без artifacts, .env, .venv, node_modules, .git,
ключей и пользовательских PPTX; release-manifest.json содержит их SHA256.

## Откат

Предыдущий релиз `/home/alex/exposlides/releases/20260928-image-api-01` сохранён.
Метаданные переключения и хеши истории:
`/home/alex/exposlides/shared/deploy-backups/20260929-full-01`.
При отсутствии активных генераций вернуть current на предыдущий релиз и
перезапустить exposlides. Shared-конфигурацию и историю не менять.

## Изменённые файлы при объединении

- `README.md`
- `agents/designer.toml`
- `config/models.toml`
- `deploy/alex-cloud/STORY-STREAM-2026-09-29.md`
- `deploy/alex-cloud/story-stream-20260929.patch`
- `exposlides/design_models.py`
- `exposlides/design_pipeline.py`
- `exposlides/studio_static/app.js`
- `frontend/README.md`
- `frontend/package-lock.json`
- `frontend/package.json`
- `frontend/src/App.tsx`
- `frontend/src/api.ts`
- `frontend/test.mjs`
- `frontend/tests/studio.test.tsx`
- `frontend/tests/upload-form.test.tsx`
- `prompts/designer/image_scene.md`
- `services/content-service/app/chains/chat_completions.py`
- `services/content-service/app/chains/hf_images.py`
- `services/content-service/app/chains/llm.py`
- `services/content-service/app/config.py`
- `services/content-service/app/design_capabilities.py`
- `services/content-service/app/design_config.py`
- `services/content-service/app/design_image.py`
- `services/content-service/app/design_main.py`
- `tests/test_design_agent_config.py`
- `tests/test_design_capabilities.py`
- `tests/test_design_generation.py`
- `tests/test_design_image.py`
- `tests/test_design_image_hf.py`
- `tests/test_openrouter_transport.py`


## Дополнительная проверка по скриншоту 03:08

Задание efebabc312d244d29822608c462bc326 начато 00:03:33 UTC до публикации full-01
в 00:07:27 UTC. Оно получило HTTP 200 от модели, но завершилось через 182.106 с.
Причина: отдельный FastLLMClient сохранял 180-секундный тайм-аут, несмотря на
240-секундный внешний бюджет story. Материалы совпадают с предыдущей проверкой:
7361 символ, 12 слайдов.

Подготовлен full-02: services/content-service/app/chains/llm.py принимает явный
request_timeout; только app/design_main.py задаёт 220 секунд. Общий лимит story
240 секунд и задания 300 секунд сохранён. Настройки других клиентов не меняются.
Шесть регрессий в tests/test_fast_request_timing.py проверяют отмену, транспортный
тайм-аут, приоритет ограничения и отклонение нулевого/отрицательного/бесконечного
значения. Локально 1445 passed за 23.03 с, Ruff прошёл.

Свежая интеграционная проверка использует исходный PPTX/TXT, настоящий LLM-запрос,
планирование и последующую сборку в отдельном каталоге. Дополнительная передача
этих материалов в optional image-generation была отклонена автоматической
проверкой разрешений: прежнее согласие покрывало LLM планировщика. Эта операция
не выполнялась. Разрешённая проверка выполняется с IMAGE_GENERATION_ENABLED=false;
производственные настройки генератора иллюстраций не изменены.


## Итог full-02

Свежий вызов модели, без повторного использования старого ответа, прошёл проверку:
12 слайдов, планирование 168.76 с; полная цепочка parser → LLM → три варианта
PPTX/PDF/HTML — 195.35 с. Все три PPTX повторно открыты, проверены 12 слайдов
и текст каждого. Иллюстрация в этой проверке отключена по описанному выше ограничению.
Результаты: `/home/alex/exposlides/shared/verification/full-20260929-live-02`.

Финальный серверный pytest: 1445 passed, 1 предупреждение Starlette, 46.38 с.
Ruff прошёл. Команды те же, что в разделе проверок выше, из каталога full-02.

Опубликован full-02 с перезапуском службы. Предыдущий full-01 сохранён;
метаданные отката — `/home/alex/exposlides/shared/deploy-backups/20260929-full-02`.
Исправление тайм-аута добавляет изменения в app/chains/llm.py, app/design_main.py
и tests/test_fast_request_timing.py поверх полного релиза. История сохранена.

`git diff --check` для исходников прошёл. Для исторического файла
story-stream-20260929.patch Git отмечает три строки контекста с пробелом;
это формат unified patch, который не обрезался во избежание повреждения патча.
