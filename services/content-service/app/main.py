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

    output_path = base_path / "generated_content.json"
    output_path.write_text(
        json.dumps(_state_to_dict(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Результат сохранён в {output_path}")


def _state_to_dict(state: ContentGraphState) -> dict:
    """Преобразует состояние графа в словарь для сериализации"""
    return {
        "presentation": state.presentation.model_dump(),
        "script": state.script,
        "analysis": state.analysis.model_dump() if state.analysis else None,
        "plan": state.plan.model_dump() if state.plan else None,
        "content": {str(k): v.model_dump() for k, v in state.content.items()} if state.content else None,
        "validation": state.validation.model_dump() if state.validation else None,
        "retries": state.retries,
    }


if __name__ == "__main__":
    asyncio.run(main())