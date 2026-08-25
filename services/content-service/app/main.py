import asyncio
import json
import logging
from pathlib import Path

from app.config import setup_logging
from app.graph.builder import build_graph
from app.models.graph_state import ContentGraphState
from app.models.request import GenerationSettings
from app.models.response import GenerationResponse, SlideContentResponse
from app.utils.presentation_parser import PresentationParser

logger = logging.getLogger(__name__)


async def main() -> None:
    """Запуск генерации контента"""
    setup_logging()
    logger.info("=== Запуск content-service ===")

    base_path = Path(__file__).resolve().parent.parent
    template_path = base_path / "template.json"
    script_path = base_path / "script.txt"

    logger.info("Чтение входных файлов")
    template = json.loads(template_path.read_text(encoding="utf-8"))
    script = script_path.read_text(encoding="utf-8")

    logger.info("Парсинг презентации из JSON")
    presentation = PresentationParser.parse(template)
    logger.debug("Распарсенная презентация: %d слайдов, %d макетов", len(presentation.slides), len(presentation.layouts))

    initial_state = ContentGraphState(
        presentation=presentation,
        script=script,
        user_mapping=None,
        settings=GenerationSettings(),
    )

    logger.info("Построение графа")
    graph = build_graph()

    logger.info("Запуск графа")
    result = await graph.ainvoke(initial_state)
    result_state = ContentGraphState(**result)
    logger.info("Граф завершил работу")

    response_content = {}
    for idx, slide in result_state.content.items():
        response_content[idx] = SlideContentResponse(placeholders=slide.placeholders, notes=None)

    response = GenerationResponse(
        content=response_content,
        validation_report=result_state.validation.model_dump() if result_state.validation else None,
    )

    output_path = base_path / "generated_content.json"
    output_path.write_text(
        json.dumps(response.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Результат сохранён в %s", output_path)
    logger.info("=== Завершение content-service ===")


if __name__ == "__main__":
    asyncio.run(main())