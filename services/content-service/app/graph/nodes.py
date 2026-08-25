import asyncio
import json
import logging
from typing import Any, Optional, Tuple

from app.models.graph_state import (
    ContentGraphState,
    ScriptAnalysis,
    SlidePlan,
    SlidePlanItem,
    GeneratedSlideContent,
)
from app.models.presentation import PresentationData, SlideData
from app.chains.prompts import ANALYZE_SCRIPT_PROMPT, PLAN_SLIDES_PROMPT, GENERATE_CONTENT_PROMPT
from app.chains.llm import llm_client
from app.utils.validation import ContentValidator

logger = logging.getLogger(__name__)




async def analyze_script(state: ContentGraphState) -> dict[str, Any]:
    """Анализ скрипта"""
    logger.info("=== Запуск узла analyze_script ===")
    prompt = ANALYZE_SCRIPT_PROMPT.format(script=state.script)
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
    )
    logger.debug("Промпт для plan_slides:\n%s", prompt)
    plan = await llm_client.generate_json(prompt, SlidePlan)

    if not plan.slides:
        logger.warning("План пуст, заполняю всеми слайдами шаблона")
        plan.slides = [
            SlidePlanItem(template_slide_index=slide.index, title="", content="", purpose="")
            for slide in state.presentation.slides
        ]
    else:
        updated_slides = []
        for i, item in enumerate(plan.slides):
            if item.template_slide_index is not None:
                updated_slides.append(item)
            else:
                layout = item.layout_type
                matched_index = None
                if layout:
                    for slide in state.presentation.slides:
                        if slide.layout_type == layout:
                            matched_index = slide.index
                            break
                if matched_index is None and i < len(state.presentation.slides):
                    matched_index = state.presentation.slides[i].index
                if matched_index is not None:
                    updated_item = item.model_copy(update={"template_slide_index": matched_index})
                    updated_slides.append(updated_item)
                    logger.debug(f"Элементу плана {i} присвоен template_slide_index={matched_index}")
                else:
                    logger.warning(f"Элемент плана {i} не удалось привязать к слайду, пропущен")
        plan.slides = updated_slides

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

    logger.info("Всего слайдов в плане: %d", len(state.plan.slides))
    for i, slide_plan in enumerate(state.plan.slides, 1):
        logger.info("--- Генерация контента для слайда %d/%d ---", i, len(state.plan.slides))
        slide_idx, slide_content = await _generate_slide_content(
            state.presentation,
            slide_plan,
            state.user_mapping,
            issues,
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
    validation = await ContentValidator.validate(state.presentation, state.content or {})
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
) -> Tuple[Optional[int], GeneratedSlideContent]:
    """Генерация контента для одного слайда"""
    slide = None
    template_slide_index = slide_plan.template_slide_index
    if template_slide_index is not None:
        slide = next((s for s in presentation.slides if s.index == template_slide_index), None)
    if slide is None and slide_plan.layout_type:
        # попытка найти по layout_type
        slide = next((s for s in presentation.slides if s.layout_type == slide_plan.layout_type), None)
    if slide is None:
        logger.warning(f"Не найден слайд для плана: {slide_plan.model_dump()}, пропускаю")
        return (None, GeneratedSlideContent())

    slide_info = _prepare_slide_info(slide)
    prompt = GENERATE_CONTENT_PROMPT.format(
        slide_info=slide_info,
        slide_plan=slide_plan.model_dump(),
        issues="\n".join(issues) if issues else "нет",
    )
    logger.debug("Промпт для _generate_slide_content:\n%s", prompt)

    generated = await llm_client.generate_json(prompt, GeneratedSlideContent)
    placeholders = generated.placeholders

    placeholders = _normalize_placeholders(placeholders, slide)

    if user_mapping and slide is not None:
        slide_mapping = user_mapping.get(str(slide.index), {})
        placeholders.update(slide_mapping)
        logger.debug("Применена пользовательская разметка для слайда %d", slide.index)

    return (slide.index, GeneratedSlideContent(placeholders=placeholders))


def _normalize_placeholders(raw: dict[str, str], slide: SlideData) -> dict[str, str]:
    """Приведение ключей placeholder к str(idx) или name"""
    normalized = {}
    for ph in slide.placeholders:
        key_candidates = []
        if ph.idx is not None:
            key_candidates.append(str(ph.idx))
        if ph.name:
            key_candidates.append(ph.name)
        if ph.placeholder_type:
            key_candidates.append(ph.placeholder_type)
        for key in key_candidates:
            if key in raw:
                canonical_key = str(ph.idx) if ph.idx is not None else ph.name
                normalized[canonical_key] = raw[key]
                break
    return normalized


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
    """Информация о слайде"""
    placeholders_desc = []
    for ph in slide.placeholders:
        key_options = []
        if ph.idx is not None:
            key_options.append(f'"{ph.idx}" (idx)')
        if ph.name:
            key_options.append(f'"{ph.name}" (name)')
        if not key_options:
            key_options.append(f'"{ph.placeholder_type}" (type)')
        keys_str = " или ".join(key_options)
        placeholders_desc.append(
            f"Placeholder {ph.name or ph.idx} (type={ph.placeholder_type}), ключ: {keys_str}, "
            f"текущий текст: '{ph.text}', max_len={ph.max_length or 'нет'}"
        )
    return (
        f"Слайд {slide.index}: layout={slide.layout_name}, type={slide.layout_type}\n"
        + "\n".join(placeholders_desc)
    )


def _prepare_new_slide_info(presentation: PresentationData, layout_type: Optional[str]) -> str:
    """Информация о новом слайде"""
    if not layout_type:
        return "Новый слайд без указания макета"
    layout = next((l for l in presentation.layouts if l.name == layout_type), None)
    if not layout:
        return f"Новый слайд с layout_type={layout_type} (макет не найден)"
    placeholders_desc = []
    for ph in layout.placeholders:
        key_options = []
        if ph.idx is not None:
            key_options.append(f'"{ph.idx}" (idx)')
        if ph.name:
            key_options.append(f'"{ph.name}" (name)')
        if not key_options:
            key_options.append(f'"{ph.placeholder_type}" (type)')
        keys_str = " или ".join(key_options)
        placeholders_desc.append(
            f"Placeholder {ph.name or ph.idx} (type={ph.placeholder_type}), ключ: {keys_str}"
        )
    return (
        f"Новый слайд на основе layout '{layout.name}' (index={layout.index})\n"
        + "\n".join(placeholders_desc)
    )