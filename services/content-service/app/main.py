from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from uuid import uuid4

from app.config import setup_logging
from app.errors import ContentValidationError
from app.graph.builder import build_graph
from app.models.graph_state import ContentGraphState
from app.models.request import GenerationSettings
from app.models.response import GenerationResponse, SlideContentResponse
from app.utils.presentation_parser import PresentationParser

logger = logging.getLogger(__name__)

SERVICE_ROOT = Path(__file__).resolve().parent.parent


async def run(
    template_json: str | Path,
    script_file: str | Path,
    output_json: str | Path,
    generation_settings: GenerationSettings | None = None,
    user_mapping: dict | None = None,
) -> Path:
    """Сгенерировать и атомарно сохранить контент презентации."""
    template_path = Path(template_json).expanduser().resolve()
    script_path = Path(script_file).expanduser().resolve()
    output_path = Path(output_json).expanduser().resolve()

    if output_path in {template_path, script_path}:
        raise ValueError("Путь результата должен отличаться от путей входных файлов")

    if not template_path.is_file():
        raise FileNotFoundError(f"Presentation JSON не найден: {template_path}")
    if not script_path.is_file():
        raise FileNotFoundError(f"Файл исходного текста не найден: {script_path}")
    if template_path.suffix.casefold() != ".json":
        raise ValueError(f"Ожидался входной файл .json: {template_path}")
    if script_path.suffix.casefold() != ".txt":
        raise ValueError(f"Ожидался файл сценария .txt: {script_path}")
    if output_path.suffix.casefold() != ".json":
        raise ValueError(f"Ожидался выходной файл .json: {output_path}")

    logger.info("Чтение входных данных")
    template = json.loads(template_path.read_text(encoding="utf-8"))
    script = script_path.read_text(encoding="utf-8")
    if not script.strip():
        raise ValueError("Исходный текст презентации пуст")

    logger.info("Парсинг презентации из JSON")
    presentation = PresentationParser.parse(template)
    if not presentation.slides:
        raise ValueError("Presentation JSON не содержит слайдов")
    logger.debug(
        "Распарсенная презентация: %d слайдов, %d макетов",
        len(presentation.slides),
        len(presentation.layouts),
    )

    initial_state = ContentGraphState(
        presentation=presentation,
        script=script,
        user_mapping=user_mapping,
        settings=generation_settings or GenerationSettings(),
    )

    logger.info("Построение графа")
    graph = build_graph()

    logger.info("Запуск графа")
    result = await graph.ainvoke(initial_state)
    result_state = ContentGraphState(**result)
    logger.info("Граф завершил работу")

    if not result_state.validation or not result_state.validation.ok:
        issues = result_state.validation.issues if result_state.validation else []
        raise ContentValidationError(
            "Граф завершился без успешной валидации"
            + (": " + "; ".join(issues) if issues else "")
        )
    if not result_state.content:
        raise ContentValidationError("Граф не сгенерировал ни одного слайда")

    response_content = {
        idx: SlideContentResponse(placeholders=slide.placeholders, notes=None)
        for idx, slide in result_state.content.items()
    }
    response = GenerationResponse(
        content=response_content,
        validation_report=result_state.validation.model_dump(),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
    try:
        payload = json.dumps(response.model_dump(), ensure_ascii=False, indent=2)
        await asyncio.to_thread(temporary_path.write_text, payload, encoding="utf-8")
        await asyncio.to_thread(temporary_path.replace, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    logger.info("Результат сохранён в %s", output_path)
    return output_path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Сгенерировать контент для PPTX-шаблона")
    parser.add_argument("--template-json", type=Path, default=SERVICE_ROOT / "template.json")
    parser.add_argument("--script", type=Path, default=SERVICE_ROOT / "script.txt")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=SERVICE_ROOT / "generated_content.json",
    )
    parser.add_argument("--user-mapping", type=Path)
    parser.add_argument("--language", default="ru")
    parser.add_argument("--tone", default="professional")
    parser.add_argument("--complexity", default="medium")
    parser.add_argument("--max-slides", type=int)
    return parser.parse_args(argv)


def _load_user_mapping(path: Path | None) -> dict | None:
    if path is None:
        return None
    mapping_path = path.expanduser().resolve()
    if not mapping_path.is_file():
        raise FileNotFoundError(f"Файл пользовательской разметки не найден: {mapping_path}")
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    if not isinstance(mapping, dict):
        raise ValueError("Пользовательская разметка должна быть JSON-объектом")
    return mapping


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    args = _parse_args(argv)
    try:
        if (
            args.user_mapping is not None
            and args.output_json.expanduser().resolve()
            == args.user_mapping.expanduser().resolve()
        ):
            raise ValueError(
                "Путь результата должен отличаться от пути пользовательской разметки"
            )
        generation_settings = GenerationSettings(
            language=args.language,
            tone=args.tone,
            complexity=args.complexity,
            max_slides=args.max_slides,
        )
        user_mapping = _load_user_mapping(args.user_mapping)
        asyncio.run(
            run(
                args.template_json,
                args.script,
                args.output_json,
                generation_settings,
                user_mapping,
            )
        )
    except Exception as error:
        logger.error("Content-service завершился с ошибкой: %s", error)
        logger.debug("Детали ошибки content-service", exc_info=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
