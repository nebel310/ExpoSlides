from app.config import settings
from app.errors import ContentValidationError
from app.graph import nodes
from app.models.graph_state import ContentGraphState
from langgraph.graph import END, StateGraph


def build_graph():
    """Сборка графа"""
    workflow = StateGraph(ContentGraphState)

    workflow.add_node("analyze_script", nodes.analyze_script)
    workflow.add_node("plan_slides", nodes.plan_slides)
    workflow.add_node("generate_content", nodes.generate_content)
    workflow.add_node("validate_content", nodes.validate_content)

    workflow.set_entry_point("analyze_script")
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
