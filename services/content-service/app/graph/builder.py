import asyncio
from typing import Any

from app.config import settings
from app.errors import ContentValidationError
from app.graph import nodes
from app.graph.fast import generate_fast
from app.models.graph_state import ContentGraphState
from langgraph.graph import END, StateGraph


def build_graph():
    """Сборка графа"""
    workflow = StateGraph(ContentGraphState)

    workflow.add_node("analyze_script", nodes.analyze_script)
    workflow.add_node("plan_slides", nodes.plan_slides)
    workflow.add_node("generate_content", nodes.generate_content)
    workflow.add_node("validate_content", nodes.validate_content)
    workflow.add_node("generate_fast", _generate_fast_with_deadline)

    workflow.set_conditional_entry_point(
        lambda state: state.settings.generation_mode,
        {"standard": "analyze_script", "fast": "generate_fast"},
    )
    workflow.add_edge("generate_fast", END)
    workflow.add_edge("analyze_script", "plan_slides")
    workflow.add_edge("plan_slides", "generate_content")
    workflow.add_edge("generate_content", "validate_content")
    workflow.add_conditional_edges(
        "validate_content",
        _should_retry,
        {
            "retry": "generate_content",
            "end": END
        }
    )

    return workflow.compile()


async def _generate_fast_with_deadline(state: ContentGraphState) -> dict[str, Any]:
    """Общий бюджет включает запросы и отдельное исправление плана и текста."""
    try:
        async with asyncio.timeout(settings.fast_generation_timeout):
            return await generate_fast(state)
    except TimeoutError as error:
        raise ContentValidationError(
            "Модель не успела подготовить проверенную презентацию за отведённое время. "
            "Попробуйте ещё раз или уменьшите объём исходного текста."
        ) from error


def _should_retry(state: ContentGraphState):
    """Условие повтора генерации"""
    if state.validation and state.validation.ok:
        return "end"
    if state.retries <= settings.content_validation_retries:
        return "retry"
    issues = state.validation.issues if state.validation else ["нет отчёта валидации"]
    raise ContentValidationError(
        "Контент не прошёл валидацию после повторных попыток: " + "; ".join(issues)
    )
