import asyncio
import json
from pathlib import Path

from app.graph.builder import build_graph
from app.models.graph_state import ContentGraphState
from app.models.request import GenerationSettings
from app.utils.presentation_parser import PresentationParser




async def main() -> None:
    """Запускает генерацию контента на основе template.json и script.txt"""
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

    # Преобразуем словарь результата в ContentGraphState для удобной сериализации
    result_state = ContentGraphState(**result)

    output_path = base_path / "generated_content.json"
    output_path.write_text(
        json.dumps(result_state.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Результат сохранён в {output_path}")


if __name__ == "__main__":
    asyncio.run(main())