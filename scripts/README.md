# Проверки проекта

После `uv sync --locked` основной офлайн-набор из корня:

```bash
uv lock --check
uv run ruff check .
uv run pytest
uv run python scripts/test_services.py
```

`test_services.py` дополняет корневой pytest тестами parser, content и gateway.
Генерирует protobuf-клиенты из `proto/*.proto` во временную директорию и запускает
каждый сервис в отдельном процессе: их одноимённые пакеты `app` не конфликтуют.
Рабочая директория также временная, поэтому локальные `.env` не загружаются.
Для unit-тестов задан фиктивный `LLM_API_KEY`; Kafka, Redis, LLM и файловый клиент
подменяются fixtures. Тесты `integration/` и `e2e/` исключены. Набор file-service
требует реальной инфраструктуры и не входит в эту команду.

Отдельные сервисы можно выбрать повторяемым параметром:

```bash
uv run python scripts/test_services.py --service parser --service gateway
```

Для React-интерфейса выполните из `frontend/`:

```bash
npm ci
npm run typecheck
npm test
npm run build
```

Python и npm установка требуют доступа к реестру или заполненного кеша; сами
перечисленные тесты не требуют API-ключей и работающей инфраструктуры.
Проверки GitHub Actions описаны в `.github/workflows/checks.yml`: Python 3.11–3.13,
Ruff, lock, корневые и изолированные service suites, затем TypeScript, frontend
tests и контроль актуальности bundled assets. Workflow добавлен как конфигурация;
его выполнение в GitHub нужно подтверждать отдельно по результатам CI.

Успешный unit-набор не подтверждает настоящий LLM, доступность FLUX, экспорт
LibreOffice, подключение Compose или матрицу браузеров. Эти проверки требуют
отдельного интеграционного/визуального прогона с фиксацией окружения и результата.
