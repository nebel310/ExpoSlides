import json
import logging
from typing import Any, Dict, Optional, Tuple

from app.chains.llm import llm_client
from app.chains.prompts import ANALYZE_SCRIPT_PROMPT, GENERATE_CONTENT_PROMPT, PLAN_SLIDES_PROMPT
from app.models.graph_state import (
    ContentGraphState,
    GeneratedSlideContent,
    ScriptAnalysis,
    SlidePlan,
    SlidePlanItem,
)
from app.models.presentation import PresentationData, SlideData
from app.models.request import GenerationSettings
from app.utils.validation import ContentValidator

logger = logging.getLogger(__name__)




async def analyze_script(state: ContentGraphState) -> dict[str, Any]:
    """Анализ скрипта"""
    logger.info("=== Запуск узла analyze_script ===")
    prompt = ANALYZE_SCRIPT_PROMPT.format(
        script=state.script,
        language=state.settings.language,
        complexity=state.settings.complexity,
    )
    analysis = await llm_client.generate_json(prompt, ScriptAnalysis)
    logger.info("Результат анализа: %s", analysis.model_dump())
    return {"analysis": analysis}


async def plan_slides(state: ContentGraphState) -> dict[str, Any]:
    """Планирование слайдов"""
    logger.info("=== Запуск узла plan_slides ===")
    slides_info = _prepare_slides_info(state.presentation)
    layouts_info = _prepare_layouts_info(state.presentation)
    analysis = state.analysis.model_dump() if state.analysis else {}
    user_mapping = state.user_mapping or {}

    prompt = PLAN_SLIDES_PROMPT.format(
        slides_info=slides_info,
        layouts_info=layouts_info,
        analysis=json.dumps(analysis, ensure_ascii=False),
        user_mapping=json.dumps(user_mapping, ensure_ascii=False),
        language=state.settings.language,
        tone=state.settings.tone,
        complexity=state.settings.complexity,
        max_slides=state.settings.max_slides or len(state.presentation.slides),
    )
    logger.debug("Промпт для plan_slides:\n%s", prompt)
    plan = await llm_client.generate_json(prompt, SlidePlan)

    plan = _normalize_plan(plan, state.presentation, state.settings.max_slides)

    logger.info("План слайдов (после нормализации): %s", plan.model_dump())
    return {"plan": plan}


async def generate_content(state: ContentGraphState) -> dict[str, Any]:
    """Генерация контента для слайдов"""
    logger.info("=== Запуск узла generate_content ===")
    if not state.plan:
        logger.warning("План отсутствует, возвращаю пустой контент")
        return {"content": {}}

    content: dict[int, GeneratedSlideContent] = {}
    issues = state.validation.issues if state.validation else []
    previous_content = state.content or {}

    logger.info("Всего слайдов в плане: %d", len(state.plan.slides))
    for i, slide_plan in enumerate(state.plan.slides, 1):
        logger.info("--- Генерация контента для слайда %d/%d ---", i, len(state.plan.slides))
        slide_index = slide_plan.template_slide_index
        slide_issues = _issues_for_slide(issues, slide_index)
        if (
            state.validation is not None
            and slide_index is not None
            and slide_index in previous_content
            and not slide_issues
        ):
            content[slide_index] = previous_content[slide_index]
            logger.info("Слайд %d прошёл валидацию и сохранён без повторной генерации", slide_index)
            continue

        slide_idx, slide_content = await _generate_slide_content(
            state.presentation,
            slide_plan,
            state.user_mapping,
            slide_issues,
            state.analysis,
            state.settings,
        )
        if slide_idx is not None:
            content[slide_idx] = slide_content
            logger.info("Слайд %d сгенерирован: %s", slide_idx, slide_content.model_dump())
        else:
            logger.warning("Для элемента плана %s не удалось определить индекс слайда", slide_plan)

    logger.info("Итоговый контент: %s", {k: v.model_dump() for k, v in content.items()})
    return {"content": content}


async def validate_content(state: ContentGraphState) -> dict[str, Any]:
    """Валидация контента"""
    logger.info("=== Запуск узла validate_content ===")
    planned_slide_indices = {
        item.template_slide_index
        for item in state.plan.slides
        if item.template_slide_index is not None
    } if state.plan else None
    validation = await ContentValidator.validate(
        state.presentation,
        state.content or {},
        planned_slide_indices,
    )
    logger.info("Результат валидации: ok=%s, issues=%s", validation.ok, validation.issues)
    update = {"validation": validation}
    if not validation.ok and state.retries < 2:
        update["retries"] = state.retries + 1
        logger.info("Будет повторная генерация (retry %d)", state.retries + 1)
    return update


async def _generate_slide_content(
    presentation: PresentationData,
    slide_plan: SlidePlanItem,
    user_mapping: Optional[dict],
    issues: list[str],
    analysis: Optional[ScriptAnalysis],
    settings: GenerationSettings,
) -> Tuple[Optional[int], GeneratedSlideContent]:
    """Генерация контента для одного слайда"""
    slide = None
    template_slide_index = slide_plan.template_slide_index
    if template_slide_index is not None:
        slide = next((s for s in presentation.slides if s.index == template_slide_index), None)
    if slide is None and slide_plan.layout_type:
        slide = next((s for s in presentation.slides if s.layout_type == slide_plan.layout_type), None)
    if slide is None:
        logger.warning(f"Не найден слайд для плана: {slide_plan.model_dump()}, пропускаю")
        return (None, GeneratedSlideContent())

    slide_info = _prepare_slide_info(slide)
    prompt = GENERATE_CONTENT_PROMPT.format(
        slide_info=slide_info,
        slide_plan=json.dumps(slide_plan.model_dump(), ensure_ascii=False),
        analysis_context=_prepare_analysis_context(analysis, slide_plan),
        issues="\n".join(issues) if issues else "нет",
        language=settings.language,
        tone=settings.tone,
        complexity=settings.complexity,
    )
    logger.debug("Промпт для _generate_slide_content:\n%s", prompt)

    # Формируем схему с конкретными индексами placeholder'ов
    schema = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False
    }
    for ph in slide.placeholders:
        key = str(ph.idx) if ph.idx is not None else ph.name
        if key is None:
            continue
        property_schema = {"type": "string"}
        if ph.max_length:
            property_schema["maxLength"] = ph.max_length
        schema["properties"][key] = property_schema
        schema["required"].append(key)

    logger.debug("Схема для слайда %d: %s", slide.index, json.dumps(schema, ensure_ascii=False))

    # Вызываем LLM с точной схемой
    raw_placeholders = await llm_client.generate_json_with_schema(prompt, schema)

    placeholders: Dict[str, str] = {}
    if raw_placeholders:
        placeholders.update(raw_placeholders)

    # Применение пользовательской разметки
    if user_mapping:
        slide_mapping = user_mapping.get(str(slide.index), {})
        placeholders.update(slide_mapping)
        logger.debug("Применена пользовательская разметка для слайда %d", slide.index)

    return (slide.index, GeneratedSlideContent(placeholders=placeholders))


def _normalize_plan(
    plan: SlidePlan,
    presentation: PresentationData,
    max_slides: Optional[int],
) -> SlidePlan:
    """Привязывает план к существующим уникальным слайдам шаблона."""
    available_slides = presentation.slides
    slide_by_index = {slide.index: slide for slide in available_slides}
    slide_limit = min(max_slides or len(available_slides), len(available_slides))
    normalized_items: list[SlidePlanItem] = []
    used_indices: set[int] = set()

    for position, item in enumerate(plan.slides):
        if len(normalized_items) >= slide_limit:
            break

        selected_index = item.template_slide_index
        if selected_index not in slide_by_index or selected_index in used_indices:
            selected_index = _select_fallback_slide_index(
                item,
                position,
                available_slides,
                used_indices,
            )
        if selected_index is None:
            logger.warning("Элемент плана %d не удалось привязать к слайду, пропущен", position)
            continue

        used_indices.add(selected_index)
        selected_slide = slide_by_index[selected_index]
        normalized_items.append(
            item.model_copy(
                update={
                    "template_slide_index": selected_index,
                    "layout_type": selected_slide.layout_type,
                }
            )
        )

    if not normalized_items:
        logger.warning("План пуст или некорректен, использую слайды шаблона по порядку")
        normalized_items = [
            SlidePlanItem(
                template_slide_index=slide.index,
                layout_type=slide.layout_type,
                purpose="Сохранить содержание исходного слайда",
            )
            for slide in available_slides[:slide_limit]
        ]

    return plan.model_copy(update={"slides": normalized_items})


def _select_fallback_slide_index(
    item: SlidePlanItem,
    position: int,
    available_slides: list[SlideData],
    used_indices: set[int],
) -> Optional[int]:
    if item.layout_type:
        matching_slide = next(
            (
                slide
                for slide in available_slides
                if slide.layout_type == item.layout_type and slide.index not in used_indices
            ),
            None,
        )
        if matching_slide:
            return matching_slide.index

    if position < len(available_slides):
        positional_slide = available_slides[position]
        if positional_slide.index not in used_indices:
            return positional_slide.index

    first_unused_slide = next(
        (slide for slide in available_slides if slide.index not in used_indices),
        None,
    )
    return first_unused_slide.index if first_unused_slide else None


def _issues_for_slide(issues: list[str], slide_index: Optional[int]) -> list[str]:
    if slide_index is None:
        return issues
    slide_prefixes = (f"Слайд {slide_index}:", f"Слайд {slide_index},")
    global_issues = [issue for issue in issues if not issue.startswith("Слайд ")]
    slide_issues = [issue for issue in issues if issue.startswith(slide_prefixes)]
    return global_issues + slide_issues


def _prepare_analysis_context(
    analysis: Optional[ScriptAnalysis],
    slide_plan: SlidePlanItem,
) -> str:
    if analysis is None:
        return "{}"

    selected_block_indices = set(slide_plan.source_block_indices)
    selected_blocks = [
        block
        for block in analysis.blocks
        if not selected_block_indices or block.index in selected_block_indices
    ]
    context = {
        "topic": analysis.topic,
        "objective": analysis.objective,
        "key_messages": analysis.key_messages,
        "facts": analysis.facts,
        "blocks": [block.model_dump() for block in selected_blocks],
    }
    return json.dumps(context, ensure_ascii=False)


def _prepare_slides_info(presentation: PresentationData) -> str:
    """Описание слайдов шаблона"""
    infos = []
    for slide in presentation.slides:
        placeholders_desc = []
        for ph in slide.placeholders:
            placeholders_desc.append(
                f"  - {ph.name or ph.idx} (type={ph.placeholder_type}, max_len={ph.max_length or 'нет'})"
            )
        infos.append(
            f"Слайд {slide.index}: layout={slide.layout_name}, type={slide.layout_type}\n"
            + "\n".join(placeholders_desc)
        )
    return "\n\n".join(infos)


def _prepare_layouts_info(presentation: PresentationData) -> str:
    """Описание макетов"""
    infos = []
    for layout in presentation.layouts:
        placeholders_desc = []
        for ph in layout.placeholders:
            placeholders_desc.append(f"  - {ph.name or ph.idx} (type={ph.placeholder_type})")
        infos.append(
            f"Layout '{layout.name}' (index={layout.index}):\n" + "\n".join(placeholders_desc)
        )
    return "\n\n".join(infos)


def _prepare_slide_info(slide: SlideData) -> str:
    """Информация о слайде с ключами-индексами"""
    placeholders_desc = []
    for ph in slide.placeholders:
        key = str(ph.idx) if ph.idx is not None else ph.name
        placeholders_desc.append(
            f"Placeholder {ph.name or ph.idx} (type={ph.placeholder_type}), "
            f"ключ: \"{key}\", текущий текст: '{ph.text}', max_len={ph.max_length or 'нет'}"
        )
    return (
        f"Слайд {slide.index}: layout={slide.layout_name}, type={slide.layout_type}\n"
        + "\n".join(placeholders_desc)
    )


def _prepare_new_slide_info(presentation: PresentationData, layout_type: Optional[str]) -> str:
    """Информация о новом слайде"""
    if not layout_type:
        return "Новый слайд без указания макета"
    layout = next(
        (candidate for candidate in presentation.layouts if candidate.name == layout_type),
        None,
    )
    if not layout:
        return f"Новый слайд с layout_type={layout_type} (макет не найден)"
    placeholders_desc = []
    for ph in layout.placeholders:
        key = str(ph.idx) if ph.idx is not None else ph.name
        placeholders_desc.append(
            f"Placeholder {ph.name or ph.idx} (type={ph.placeholder_type}), ключ: \"{key}\""
        )
    return (
        f"Новый слайд на основе layout '{layout.name}' (index={layout.index})\n"
        + "\n".join(placeholders_desc)
    )
