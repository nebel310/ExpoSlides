import asyncio
import json
from pathlib import Path

from app.graph.builder import build_graph
from app.models.graph_state import ContentGraphState
from app.models.request import GenerationSettings
from app.models.response import GenerationResponse, SlideContentResponse
from app.utils.presentation_parser import PresentationParser




async def main() -> None:
    """Запуск генерации контента"""
    base_path = Path(__file__).resolve().parent.parent
    template_path = base_path / "template.json"
    script_path = base_path / "script.txt"

    template = json.loads(template_path.read_text(encoding="utf-8"))
    script = script_path.read_text(encoding="utf-8")

    presentation = PresentationParser.parse(template)
    initial_state = ContentGraphState(
        presentation=presentation,
        script=script,
        user_mapping=None,
        settings=GenerationSettings(),
    )

    graph = build_graph()
    result = await graph.ainvoke(initial_state)
    result_state = ContentGraphState(**result)

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
    print(f"Результат сохранён в {output_path}")


if __name__ == "__main__":
    asyncio.run(main())