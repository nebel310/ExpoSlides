import asyncio
import json
from typing import Any, Optional
from app.models.graph_state import ContentGraphState, ScriptAnalysis, SlidePlan
from app.models.response import SlideContent
from app.models.presentation import SlideData, PresentationData
from app.chains.prompts import (
    ANALYZE_SCRIPT_PROMPT,
    PLAN_SLIDES_PROMPT,
    GENERATE_CONTENT_PROMPT,
)
from app.chains.llm import get_llm
from app.utils.validation import ContentValidator


async def analyze_script(state: ContentGraphState) -> dict[str, Any]:
    """Анализирует скрипт доклада"""
    llm = get_llm()
    prompt = ANALYZE_SCRIPT_PROMPT.format(script=state.script)
    response = await llm.ainvoke(prompt)
    try:
        data = json.loads(response.content)
        analysis = ScriptAnalysis(**data)
    except Exception:
        analysis = ScriptAnalysis()
    return {"analysis": analysis}


async def plan_slides(state: ContentGraphState) -> dict[str, Any]:
    """Планирует слайды на основе анализа и шаблона"""
    llm = get_llm()
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
    response = await llm.ainvoke(prompt)
    try:
        data = json.loads(response.content)
        plan = SlidePlan(**data)
    except Exception:
        plan = SlidePlan(slides=[])
    return {"plan": plan}


async def generate_content(state: ContentGraphState) -> dict[str, Any]:
    """Генерирует контент для слайдов по плану параллельно"""
    if not state.plan:
        return {"content": {}}

    tasks = []
    for slide_plan in state.plan.slides:
        tasks.append(_generate_slide_content(state.presentation, slide_plan, state.user_mapping))
    results = await asyncio.gather(*tasks)

    content = {}
    for slide_idx, slide_content in results:
        if slide_idx is not None:
            content[slide_idx] = slide_content
    return {"content": content}


async def validate_content(state: ContentGraphState) -> dict[str, Any]:
    """Валидирует сгенерированный контент"""
    validation = await ContentValidator.validate(state.presentation, state.content)
    update = {"validation": validation}
    if not validation.ok and state.retries < 2:
        update["retries"] = state.retries + 1
    return update


async def _generate_slide_content(
    presentation: PresentationData,
    slide_plan: dict,
    user_mapping: Optional[dict],
) -> tuple[Optional[int], SlideContent]:
    """Генерирует контент для одного слайда по плану"""
    llm = get_llm()

    template_slide_index = slide_plan.get("template_slide_index")
    if template_slide_index is not None:
        slide = next(
            (s for s in presentation.slides if s.index == template_slide_index),
            None,
        )
        slide_info = _prepare_slide_info(slide) if slide else "Слайд не найден"
    else:
        # Новый слайд: берём layout_type и создаём информацию из layouts
        layout_type = slide_plan.get("layout_type")
        slide_info = _prepare_new_slide_info(presentation, layout_type)

    prompt = GENERATE_CONTENT_PROMPT.format(
        slide_info=slide_info,
        slide_plan=json.dumps(slide_plan, ensure_ascii=False),
    )
    response = await llm.ainvoke(prompt)
    try:
        data = json.loads(response.content)
        placeholders = data.get("placeholders", {})
    except Exception:
        placeholders = {}

    if user_mapping and slide is not None:
        slide_mapping = user_mapping.get(str(slide.index), {})
        placeholders.update(slide_mapping)

    return (slide.index if slide else None, SlideContent(placeholders=placeholders))


def _prepare_slides_info(presentation: PresentationData) -> str:
    """Формирует описание слайдов шаблона"""
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
    """Формирует описание доступных макетов"""
    infos = []
    for layout in presentation.layouts:
        placeholders_desc = []
        for ph in layout.placeholders:
            placeholders_desc.append(
                f"  - {ph.name or ph.idx} (type={ph.placeholder_type})"
            )
        infos.append(
            f"Layout '{layout.name}' (index={layout.index}):\n"
            + "\n".join(placeholders_desc)
        )
    return "\n\n".join(infos)


def _prepare_slide_info(slide: SlideData) -> str:
    """Формирует информацию о конкретном слайде"""
    placeholders_desc = []
    for ph in slide.placeholders:
        placeholders_desc.append(
            f"Placeholder '{ph.name or ph.idx}' (type={ph.placeholder_type}): текущий текст: '{ph.text}', max_len={ph.max_length or 'нет'}"
        )
    return f"Слайд {slide.index}: layout={slide.layout_name}, type={slide.layout_type}\n" + "\n".join(placeholders_desc)


def _prepare_new_slide_info(presentation: PresentationData, layout_type: str) -> str:
    """Формирует информацию о новом слайде на основе макета"""
    layout = next((l for l in presentation.layouts if l.name == layout_type), None)
    if not layout:
        return f"Новый слайд с layout_type={layout_type} (макет не найден)"
    placeholders_desc = []
    for ph in layout.placeholders:
        placeholders_desc.append(
            f"Placeholder '{ph.name or ph.idx}' (type={ph.placeholder_type})"
        )
    return f"Новый слайд на основе layout '{layout.name}' (index={layout.index})\n" + "\n".join(placeholders_desc)