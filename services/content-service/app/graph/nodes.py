import json
import logging
from typing import Any, Dict, Optional, Tuple

from app.chains.llm import llm_client
from app.chains.prompts import (
    ANALYZE_SCRIPT_PROMPT,
    GENERATE_CONTENT_PROMPT,
    PLAN_SLIDES_PROMPT,
)
from app.config import settings as service_settings
from app.errors import (
    AnalysisValidationError,
    ContentValidationError,
    PlanValidationError,
    UserMappingValidationError,
)
from app.models.graph_state import (
    ContentGraphState,
    GeneratedSlideContent,
    ScriptAnalysis,
    SlidePlan,
    SlidePlanItem,
)
from app.models.presentation import PresentationData, SlideData
from app.models.request import GenerationSettings
from app.utils.grounding import extract_fact_tokens, find_unsupported_claim_markers
from app.utils.validation import (
    LIST_PLACEHOLDER_TYPES,
    ContentValidator,
    contains_blank_list_items,
    contains_manual_list_markers,
)

logger = logging.getLogger(__name__)


async def analyze_script(state: ContentGraphState) -> dict[str, Any]:
    """Анализ скрипта"""
    logger.info("=== Запуск узла analyze_script ===")
    mapping_issues = _user_mapping_validation_issues(
        state.user_mapping,
        state.presentation,
    )
    if mapping_issues:
        raise UserMappingValidationError(
            "Пользовательская разметка не прошла проверку: "
            + "; ".join(mapping_issues)
        )

    base_prompt = ANALYZE_SCRIPT_PROMPT.format(
        script=state.script,
        language=state.settings.language,
        complexity=state.settings.complexity,
    )
    prompt = base_prompt
    for attempt in range(service_settings.llm_response_retries + 1):
        analysis = await llm_client.generate_json(prompt, ScriptAnalysis)
        issues = _analysis_grounding_issues(state.script, analysis)
        if not issues:
            logger.debug("Результат анализа: %s", analysis.model_dump())
            return {"analysis": analysis}
        if attempt >= service_settings.llm_response_retries:
            raise AnalysisValidationError(
                "Анализ источника не прошёл проверку: " + "; ".join(issues)
            )
        logger.warning("Анализ источника отклонён, повтор %d: %s", attempt + 1, issues)
        prompt = _append_validation_feedback(base_prompt, issues)

    raise AssertionError("unreachable")


async def plan_slides(state: ContentGraphState) -> dict[str, Any]:
    """Планирование слайдов"""
    logger.info("=== Запуск узла plan_slides ===")
    slides_info = _prepare_slides_info(state.presentation)
    layouts_info = _prepare_layouts_info(state.presentation)
    analysis = state.analysis.model_dump() if state.analysis else {}
    user_mapping = state.user_mapping or {}

    base_prompt = PLAN_SLIDES_PROMPT.format(
        slides_info=slides_info,
        layouts_info=layouts_info,
        analysis=json.dumps(analysis, ensure_ascii=False),
        user_mapping=json.dumps(user_mapping, ensure_ascii=False),
        language=state.settings.language,
        tone=state.settings.tone,
        complexity=state.settings.complexity,
        max_slides=state.settings.max_slides or len(state.presentation.slides),
    )
    prompt = base_prompt
    for attempt in range(service_settings.llm_response_retries + 1):
        logger.debug("Промпт для plan_slides:\n%s", prompt)
        plan = await llm_client.generate_json(prompt, SlidePlan)
        issues = _plan_validation_issues(
            plan,
            state.presentation,
            state.analysis,
            state.settings.max_slides,
            state.script,
            state.user_mapping,
            state.settings.strict_user_mapping,
        )
        if not issues:
            normalized_plan = _normalize_plan(plan, state.presentation)
            logger.debug("План слайдов (после нормализации): %s", normalized_plan.model_dump())
            return {"plan": normalized_plan}
        if attempt >= service_settings.llm_response_retries:
            raise PlanValidationError("План не прошёл проверку: " + "; ".join(issues))
        logger.warning("План отклонён, повтор %d: %s", attempt + 1, issues)
        prompt = _append_validation_feedback(base_prompt, issues)

    raise AssertionError("unreachable")


async def generate_content(state: ContentGraphState) -> dict[str, Any]:
    """Генерация контента для слайдов"""
    logger.info("=== Запуск узла generate_content ===")
    if not state.plan:
        raise ContentValidationError("Невозможно сгенерировать контент без плана слайдов")

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
            source_text=state.script,
        )
        if slide_idx is not None:
            content[slide_idx] = slide_content
            logger.debug("Слайд %d сгенерирован: %s", slide_idx, slide_content.model_dump())
        else:
            logger.warning("Для элемента плана %s не удалось определить индекс слайда", slide_plan)

    logger.debug("Итоговый контент: %s", {k: v.model_dump() for k, v in content.items()})
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
        state.script,
    )
    logger.info("Результат валидации: ok=%s, issues=%s", validation.ok, validation.issues)
    update = {"validation": validation}
    if not validation.ok:
        update["retries"] = state.retries + 1
        if state.retries < service_settings.content_validation_retries:
            logger.info("Будет повторная генерация (retry %d)", state.retries + 1)
    return update


async def _generate_slide_content(
    presentation: PresentationData,
    slide_plan: SlidePlanItem,
    user_mapping: Optional[dict],
    issues: list[str],
    analysis: Optional[ScriptAnalysis],
    settings: GenerationSettings,
    source_text: str | None = None,
) -> Tuple[Optional[int], GeneratedSlideContent]:
    """Генерация контента для одного слайда"""
    slide = None
    template_slide_index = slide_plan.template_slide_index
    if template_slide_index is not None:
        slide = next((s for s in presentation.slides if s.index == template_slide_index), None)
    if slide is None and slide_plan.layout_type:
        slide = next((s for s in presentation.slides if s.layout_type == slide_plan.layout_type), None)
    if slide is None:
        raise ContentValidationError(
            "Не найден слайд шаблона для элемента плана: "
            f"{slide_plan.model_dump()}"
        )

    slide_info = _prepare_slide_info(slide)
    prompt = GENERATE_CONTENT_PROMPT.format(
        slide_info=slide_info,
        slide_plan=json.dumps(slide_plan.model_dump(), ensure_ascii=False),
        analysis_context=_prepare_analysis_context(analysis, slide_plan),
        required_facts=_prepare_required_facts(slide_plan),
        issues="\n".join(issues) if issues else "нет",
        language=settings.language,
        tone=settings.tone,
        complexity=settings.complexity,
        source_text=source_text or "",
    )
    base_prompt = prompt
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
        property_schema = {"type": "string", "minLength": 1}
        if ph.max_length:
            property_schema["maxLength"] = ph.max_length
        schema["properties"][key] = property_schema
        schema["required"].append(key)

    if not schema["required"]:
        raise ContentValidationError(
            f"Слайд {slide.index} не содержит текстовых placeholder для генерации"
        )

    logger.debug("Схема для слайда %d: %s", slide.index, json.dumps(schema, ensure_ascii=False))

    # Вызываем LLM с точной схемой и проверяем факты именно этого слайда.
    raw_placeholders = None
    for attempt in range(service_settings.llm_response_retries + 1):
        raw_placeholders = await llm_client.generate_json_with_schema(prompt, schema)
        grounding_issues = _slide_content_grounding_issues(
            raw_placeholders,
            slide_plan,
            analysis,
        )
        if not grounding_issues:
            break
        if attempt >= service_settings.llm_response_retries:
            raise ContentValidationError(
                f"Слайд {slide.index} не прошёл проверку фактов: "
                + "; ".join(grounding_issues)
            )
        logger.warning(
            "Контент слайда %d отклонён, повтор %d: %s",
            slide.index,
            attempt + 1,
            grounding_issues,
        )
        prompt = _append_validation_feedback(base_prompt, grounding_issues)

    placeholders: Dict[str, str] = {}
    if raw_placeholders:
        placeholders.update(raw_placeholders)

    # Применение пользовательской разметки
    if user_mapping:
        slide_mapping = user_mapping.get(str(slide.index), {})
        placeholders.update(slide_mapping)
        logger.debug("Применена пользовательская разметка для слайда %d", slide.index)

    return (slide.index, GeneratedSlideContent(placeholders=placeholders))


def _normalize_plan(plan: SlidePlan, presentation: PresentationData) -> SlidePlan:
    """Adds trusted template metadata after semantic validation has passed."""
    slide_by_index = {slide.index: slide for slide in presentation.slides}
    normalized_items = [
        item.model_copy(
            update={"layout_type": slide_by_index[item.template_slide_index].layout_type}
        )
        for item in plan.slides
    ]
    return plan.model_copy(update={"slides": normalized_items})


def _analysis_grounding_issues(source_text: str, analysis: ScriptAnalysis) -> list[str]:
    analysis_text = "\n".join(
        [
            analysis.topic,
            analysis.audience,
            analysis.objective,
            *analysis.key_messages,
            *analysis.facts,
            *(
                text
                for block in analysis.blocks
                for text in [block.heading, block.summary, *block.key_points, *block.facts]
            ),
        ]
    )
    source_tokens = extract_fact_tokens(source_text)
    analysis_tokens = extract_fact_tokens(analysis_text)
    issues = []
    missing_tokens = sorted(source_tokens - analysis_tokens)
    unexpected_tokens = sorted(analysis_tokens - source_tokens)
    if missing_tokens:
        issues.append("не сохранены факты из источника: " + ", ".join(missing_tokens))
    if unexpected_tokens:
        issues.append("добавлены факты не из источника: " + ", ".join(unexpected_tokens))
    unsupported_claims = sorted(find_unsupported_claim_markers(source_text, analysis_text))
    if unsupported_claims:
        issues.append(
            "добавлены неподтверждённые оценки или сравнения: "
            + ", ".join(unsupported_claims)
        )
    return issues


def _plan_validation_issues(
    plan: SlidePlan,
    presentation: PresentationData,
    analysis: Optional[ScriptAnalysis],
    max_slides: Optional[int],
    source_text: str,
    user_mapping: Optional[dict] = None,
    strict_user_mapping: bool = False,
) -> list[str]:
    issues = []
    available_indices = {slide.index for slide in presentation.slides}
    slide_by_index = {slide.index: slide for slide in presentation.slides}
    planned_indices = [item.template_slide_index for item in plan.slides]
    slide_limit = max_slides or len(available_indices)
    if len(plan.slides) > slide_limit:
        issues.append(f"слайдов {len(plan.slides)}, разрешено не больше {slide_limit}")
    invalid_indices = sorted(set(planned_indices) - available_indices)
    if invalid_indices:
        issues.append("нет слайдов шаблона с индексами: " + ", ".join(map(str, invalid_indices)))
    if len(planned_indices) != len(set(planned_indices)):
        issues.append("template_slide_index должен быть уникальным")

    if strict_user_mapping and user_mapping:
        mapped_indices = {int(slide_index) for slide_index in user_mapping}
        missing_mapped_indices = sorted(mapped_indices - set(planned_indices))
        if missing_mapped_indices:
            issues.append(
                "план не использовал слайды из пользовательской разметки: "
                + ", ".join(map(str, missing_mapped_indices))
            )

    unfillable_indices = sorted(
        {
            slide_index
            for slide_index in planned_indices
            if slide_index in slide_by_index and not slide_by_index[slide_index].placeholders
        }
    )
    if unfillable_indices:
        issues.append(
            "слайды не содержат текстовых placeholder: "
            + ", ".join(map(str, unfillable_indices))
        )

    available_block_indices = {block.index for block in analysis.blocks} if analysis else set()
    referenced_block_indices = {
        block_index
        for item in plan.slides
        for block_index in item.source_block_indices
    }
    invalid_block_indices = sorted(referenced_block_indices - available_block_indices)
    if invalid_block_indices:
        issues.append(
            "source_block_indices отсутствуют в анализе: "
            + ", ".join(map(str, invalid_block_indices))
        )
    plan_text = "\n".join(
        text
        for item in plan.slides
        for text in [item.title, item.content, item.purpose, item.key_message]
    )
    source_tokens = extract_fact_tokens(source_text)
    plan_tokens = extract_fact_tokens(plan_text)
    missing_tokens = sorted(source_tokens - plan_tokens)
    unexpected_tokens = sorted(plan_tokens - source_tokens)
    if missing_tokens:
        issues.append("план не распределил факты: " + ", ".join(missing_tokens))
    if unexpected_tokens:
        issues.append("план добавил факты не из источника: " + ", ".join(unexpected_tokens))
    unsupported_claims = sorted(find_unsupported_claim_markers(source_text, plan_text))
    if unsupported_claims:
        issues.append(
            "план содержит неподтверждённые оценки или сравнения: "
            + ", ".join(unsupported_claims)
        )
    return issues


def _user_mapping_validation_issues(
    user_mapping: Optional[dict],
    presentation: PresentationData,
) -> list[str]:
    if not user_mapping:
        return []

    slides_by_key = {str(slide.index): slide for slide in presentation.slides}
    issues = []
    for slide_key, raw_mapping in user_mapping.items():
        if not isinstance(slide_key, str) or slide_key not in slides_by_key:
            issues.append(f"неизвестный индекс слайда: {slide_key!r}")
            continue
        if not isinstance(raw_mapping, dict):
            issues.append(f"слайд {slide_key}: разметка должна быть JSON-объектом")
            continue

        slide = slides_by_key[slide_key]
        placeholders_by_key = {
            str(placeholder.idx) if placeholder.idx is not None else placeholder.name: placeholder
            for placeholder in slide.placeholders
            if placeholder.idx is not None or placeholder.name is not None
        }
        for placeholder_key, value in raw_mapping.items():
            if not isinstance(placeholder_key, str) or placeholder_key not in placeholders_by_key:
                issues.append(
                    f"слайд {slide_key}: неизвестный placeholder {placeholder_key!r}"
                )
                continue
            if not isinstance(value, str) or not value.strip():
                issues.append(
                    f"слайд {slide_key}, placeholder {placeholder_key!r}: "
                    "требуется непустая строка"
                )
                continue
            max_length = placeholders_by_key[placeholder_key].max_length
            if max_length is not None and len(value) > max_length:
                issues.append(
                    f"слайд {slide_key}, placeholder {placeholder_key!r}: "
                    f"текст длиннее максимума ({len(value)} > {max_length})"
                )

            placeholder_type = placeholders_by_key[placeholder_key].placeholder_type
            if (
                placeholder_type in LIST_PLACEHOLDER_TYPES
                and contains_manual_list_markers(value)
            ):
                issues.append(
                    f"слайд {slide_key}, placeholder {placeholder_key!r}: "
                    "текст содержит ручные маркеры списка"
                )
            if (
                placeholder_type in LIST_PLACEHOLDER_TYPES
                and contains_blank_list_items(value)
            ):
                issues.append(
                    f"слайд {slide_key}, placeholder {placeholder_key!r}: "
                    "список содержит пустые строки"
                )

    return issues


def _append_validation_feedback(prompt: str, issues: list[str]) -> str:
    return (
        f"{prompt}\n\n"
        "Предыдущий результат отклонён проверкой:\n- "
        + "\n- ".join(issues)
        + "\nИсправь все перечисленные ошибки и верни новый результат."
    )


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
        "facts": [fact for block in selected_blocks for fact in block.facts],
        "blocks": [block.model_dump() for block in selected_blocks],
    }
    return json.dumps(context, ensure_ascii=False)


def _prepare_required_facts(slide_plan: SlidePlanItem) -> str:
    plan_text = "\n".join(
        [slide_plan.title, slide_plan.content, slide_plan.key_message]
    )
    tokens = sorted(extract_fact_tokens(plan_text))
    return ", ".join(tokens) if tokens else "числовых фактов нет"


def _slide_content_grounding_issues(
    placeholders: dict[str, Any],
    slide_plan: SlidePlanItem,
    analysis: Optional[ScriptAnalysis],
) -> list[str]:
    generated_text = "\n".join(str(value) for value in placeholders.values())
    plan_text = "\n".join(
        [slide_plan.title, slide_plan.content, slide_plan.key_message]
    )
    required_tokens = extract_fact_tokens(plan_text)
    allowed_text = _prepare_analysis_context(analysis, slide_plan)
    allowed_tokens = extract_fact_tokens(allowed_text)
    generated_tokens = extract_fact_tokens(generated_text)
    issues = []
    missing_tokens = sorted(required_tokens - generated_tokens)
    unexpected_tokens = sorted(generated_tokens - allowed_tokens)
    if missing_tokens:
        issues.append("обязательные факты отсутствуют: " + ", ".join(missing_tokens))
    if unexpected_tokens:
        issues.append("добавлены факты не из источника: " + ", ".join(unexpected_tokens))
    return issues


def _prepare_slides_info(presentation: PresentationData) -> str:
    """Описание слайдов шаблона"""
    infos = []
    for slide in presentation.slides:
        placeholders_desc = []
        for ph in slide.placeholders:
            placeholders_desc.append(
                f"  - {ph.name or ph.idx} (type={ph.placeholder_type}, "
                f"max_len={ph.max_length or 'нет'}), "
                f"пример: {json.dumps(ph.text[:160], ensure_ascii=False)}"
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
