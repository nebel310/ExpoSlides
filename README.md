# ExpoSlides

ExpoSlides — набор Python-сервисов для разбора PPTX-шаблона и подготовки контента
презентации. Текущее состояние проекта и ограничения описаны в
[`PROJECT_REVIEW.md`](PROJECT_REVIEW.md).

## Окружение разработки

Для управления Python и зависимостями используется [uv](https://docs.astral.sh/uv/).
Версия Python задаётся в `.python-version`, точные версии пакетов — в `uv.lock`.

```bash
uv sync --locked
```

## Проверки качества

```bash
uv run ruff check .
uv run pytest
```

Тесты не обращаются к LLM API: внешние вызовы должны подменяться тестовыми
реализациями.

## Сравнение качества генерации

Фиксированные сценарии и scorer находятся в каталоге `evals`. Пример оценки
сохранённого ответа:

```bash
uv run python evals/score.py quarterly-results generated_content.json
```

Описание метрик и правила честного сравнения версий приведены в
[`evals/README.md`](evals/README.md).
