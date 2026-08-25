from langgraph.graph import StateGraph, END
from app.models.graph_state import ContentGraphState
from app.graph import nodes




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
    if state.retries < 2:
        return "retry"
    return "end"