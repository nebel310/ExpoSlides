import logging

from app.config import settings
from app.domain.contract import ContentGenerationRequest, ContentGenerationResult
from app.errors import ContentValidationError
from app.graph.builder import build_graph
from app.models.graph_state import ContentGraphState
from app.models.presentation import PresentationData
from app.models.request import GenerationSettings
from app.models.response import SlideContentResponse
from app.utils.presentation_parser import PresentationParser

logger = logging.getLogger(__name__)

STUB_TEXT = "helloworld"


async def generate_content(request: ContentGenerationRequest) -> ContentGenerationResult:
    """Сгенерировать контент презентации по структуре и скрипту"""
    if request.feedback:
        logger.info(
            "Получен внешний feedback длиной %d символов",
            len(request.feedback),
        )

    presentation = PresentationParser.parse(request.structure)
    if not presentation.slides:
        raise ContentValidationError("Presentation JSON не содержит слайдов")

    if settings.llm_stub_mode:
        logger.warning("LLM_STUB_MODE включён: контент заполняется заглушкой")
        return _generate_stub(presentation)

    initial_state = ContentGraphState(
        presentation=presentation,
        script=request.script,
        feedback=request.feedback,
        user_mapping=None,
        settings=GenerationSettings(),
    )

    logger.info("Запуск графа генерации контента")
    graph = build_graph()
    result = await graph.ainvoke(initial_state)
    result_state = ContentGraphState(**result)
    logger.info("Граф генерации контента завершил работу")

    if not result_state.validation or not result_state.validation.ok:
        issues = result_state.validation.issues if result_state.validation else []
        raise ContentValidationError(
            "Домен завершился без успешной валидации"
            + (": " + "; ".join(issues) if issues else "")
        )
    if not result_state.content:
        raise ContentValidationError("Домен не сгенерировал ни одного слайда")

    content = {
        slide_index: SlideContentResponse(
            placeholders=slide.placeholders,
            notes=None,
        ).model_dump()
        for slide_index, slide in result_state.content.items()
    }

    logger.info("Сгенерировано слайдов: %d", len(content))
    return ContentGenerationResult(
        content=content,
        passed=True,
        reason=None,
        validation_report=result_state.validation.model_dump(),
    )


def _generate_stub(presentation: PresentationData) -> ContentGenerationResult:
    """Заполняет все placeholder'ы строкой helloworld нужной длины"""
    content: dict[int, dict] = {}
    for slide in presentation.slides:
        placeholders: dict[str, str] = {}
        for placeholder in slide.placeholders:
            key = (
                str(placeholder.idx)
                if placeholder.idx is not None
                else placeholder.name
            )
            if key is None:
                continue
            length = placeholder.max_length or 20
            repeats = length // len(STUB_TEXT) + 1
            placeholders[key] = (STUB_TEXT * repeats)[:length]
        if placeholders:
            content[slide.index] = {"placeholders": placeholders, "notes": None}

    logger.info("Заглушка сгенерирована для %d слайдов", len(content))
    return ContentGenerationResult(
        content=content,
        passed=True,
        reason=None,
        validation_report={"ok": True, "issues": []},
    )