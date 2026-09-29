"""Изолированная генерация плана для нового версионируемого контракта."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chains.llm import FastLLMClient  # noqa: E402
from app.config import settings, setup_logging  # noqa: E402
from app.design_config import role_config, role_metadata, role_prompt  # noqa: E402
from app.errors import (  # noqa: E402
    CONTENT_ERROR_EXIT_CODES,
    ContentValidationError,
    GenerationConfigurationError,
    LLMCredentialsError,
    LLMGenerationError,
    content_error_code,
)
from app.utils.fact_grounding import (  # noqa: E402
    missing_required_messages,
    required_source_messages,
    source_topic_visible,
)

from exposlides.design_content import (  # noqa: E402
    source_excerpts,
    story_reference_issues,
    validate_story,
)
from exposlides.design_layout import story_layout_issues  # noqa: E402
from exposlides.design_models import ContentPlan, DesignRequest, TemplateProfile  # noqa: E402
from exposlides.template_layout import (  # noqa: E402
    composition_brief,
    cover_brief,
    cover_fits,
    cover_patterns,
)

# Длинный план получаем по частям, сохраняя общий timeout и полную валидацию.
# Внутри 240-секундной роли оставляем 20 секунд на короткое исправление.
fast_llm_client = FastLLMClient(stream=True, request_timeout=220)

PUBLIC_ERROR_MESSAGES = {
    "invalid_response": "Модель вернула некорректный ответ. Попробуйте ещё раз.",
    "content_validation": "План не прошёл проверку содержания. Уточните материалы или повторите попытку.",
    "timeout": "Превышено время ожидания плана. Попробуйте ещё раз.",
    "auth": "Доступ к модели не настроен или отклонён. Проверьте ключ LLM_API_KEY.",
    "network": "Сервис модели недоступен. Проверьте соединение и повторите попытку.",
    "configuration": "Некорректная конфигурация модели или роли планировщика.",
    "unknown": "Не удалось получить проверенный план. Проверьте модель и материалы.",
}


class StoryValidationError(ContentValidationError):
    """Диагностика содержания для закрытого каталога задания, не для ответа API."""

    def __init__(self, issues: list[str], plan: ContentPlan | None):
        super().__init__("План не прошёл проверку: " + "; ".join(issues))
        self.issues = list(issues)
        self.plan = plan


def _story_configuration() -> tuple[dict, str, dict]:
    try:
        config = role_config("story")
        for name in ("correction", "correction_patch", "correction_full",
                     "repair_requirements", "editorial_repair"):
            role_prompt("story", name)
        return (
            config, role_prompt("story"),
            role_metadata("story", settings.llm_fast_model),
        )
    except (ValueError, KeyError, TypeError, OSError) as error:
        # Только граница чтения конфигурации; ошибки данных не становятся config.
        raise GenerationConfigurationError("Некорректная конфигурация планировщика") from error


async def _close_client() -> None:
    try:
        async with asyncio.timeout(5):
            await fast_llm_client.aclose()
    except Exception:
        # Завершение транспорта не должно скрывать исходную причину ошибки.
        pass


def _correction_prompt(prompt: str, previous: ContentPlan | None,
                       errors: list[str], *, patch: bool, payload: dict) -> str:
    instruction = role_prompt("story", "correction_patch" if patch else "correction_full").rstrip("\n")
    data = {
        "input": payload,
        "generation_requirements": (
            role_prompt("story", "repair_requirements").rstrip("\n") if patch else prompt
        ),
        "previous_plan": previous.model_dump(mode="json") if previous else None,
        "issues": errors,
        "missing_source_content": [source for source in payload["sources"]
                                   if any(f"раздела {source['id']} " in e for e in errors)],
    }
    return role_prompt("story", "correction").rstrip("\n").replace(
        "{instruction}", instruction,
    ).replace("{payload}", json.dumps(data, ensure_ascii=False))


def _local_repairs(errors: list[str], payload: dict,
                   plan: ContentPlan) -> tuple[bool, list[dict]] | None:
    # Недостаток видимых пояснений требует замены слайда через ContentPlan patch.
    # Редакторские source_N ниже меняют только notes и не могут исправить обеднение.
    cover = any(e.startswith("Первый слайд не помещается") for e in errors)
    missing = [source for source in payload["sources"] if
               f"Содержание раздела {source['id']} раскрыто не полностью" in errors]
    recognized = len(missing) + int(cover)
    if recognized != len(errors) or not recognized:
        return None
    for source in missing:
        visible = "\n".join(
            "\n".join([slide.title, *slide.paragraphs,
                       *(slide.visual.labels if slide.visual else [])])
            for slide in plan.slides if source["id"] in slide.source_ids
        )
        # Правка notes может восстановить только пояснения. Отсутствующий тезис
        # или обязательное сообщение нужно исправлять в видимом тексте слайда.
        if (not source_topic_visible(source["text"], visible)
                or missing_required_messages(visible, required_source_messages(source["text"]))):
            return None
    return cover, missing


async def _repair_fields(client, plan: ContentPlan, payload: dict,
                         repairs: tuple[bool, list[dict]]) -> ContentPlan:
    """Короткие редакторские правки; размещение и сохранение остальных фактов — кодом."""
    cover, missing = repairs
    fields = {}
    if cover:
        layout = payload["template_layout"]
        for name, maximum in [("cover_title", layout["title_max_characters"]),
                              ("cover_subtitle", layout["subtitle_max_characters"])]:
            fields[name] = (str, Field(min_length=1, max_length=maximum))
    for index, source in enumerate(missing):
        fields[f"source_{index}"] = (str, Field(min_length=1, max_length=1200))
    model = create_model(
        "EditorialRepairs", __base__=BaseModel, __config__=ConfigDict(extra="forbid"), **fields,
    )
    prompt = role_prompt("story", "editorial_repair").rstrip("\n").replace(
        "{payload}", json.dumps({
            "cover": plan.slides[0].model_dump() if cover else None,
            "limits": payload.get("template_layout"),
            "source_fields": {f"source_{i}": source["text"] for i, source in enumerate(missing)},
        }, ensure_ascii=False),
    )
    reply = (await client.generate_json(prompt, model)).model_dump()
    updated = plan.model_dump()
    slides = updated["slides"]
    if cover:
        original = slides[0]
        original["notes"] = "\n\n".join(filter(None, [
            original["notes"], " ".join([original["title"], *original["paragraphs"]]),
        ]))
        original.update(title=reply["cover_title"], paragraphs=[reply["cover_subtitle"]], visual=None)
    for index, source in enumerate(missing):
        candidates = slides[1:] if payload.get("template_layout") and len(slides) > 1 else slides
        target = next((slide for slide in candidates if source["id"] in slide["source_ids"]),
                      candidates[0])
        target["notes"] = "\n\n".join(filter(None, [
            target["notes"], reply[f"source_{index}"],
        ]))
        target["source_ids"] = list(dict.fromkeys([*target["source_ids"], source["id"]]))
    try:
        return ContentPlan.model_validate(updated)
    except ValidationError as error:
        raise ContentValidationError("Исправления не помещаются в структуру плана") from error


def _redistribute_cover(profile: TemplateProfile, plan: ContentPlan) -> ContentPlan:
    """Перенести лишние абзацы тесной обложки, не сокращая и не теряя факты."""
    if len(plan.slides) < 2 or len(plan.slides[0].paragraphs) < 2:
        return plan
    if cover_fits(profile, plan.slides[0]):
        return plan
    candidate = plan.model_copy(deep=True)
    cover = candidate.slides[0]
    extra = cover.paragraphs[1:]
    cover.paragraphs = cover.paragraphs[:1]
    if not cover_fits(profile, cover):
        return plan
    for paragraph in extra:
        target = next((slide for slide in candidate.slides[1:]
                       if paragraph in slide.paragraphs), candidate.slides[1])
        if paragraph not in target.paragraphs:
            target.paragraphs.append(paragraph)
        target.source_ids = list(dict.fromkeys([*target.source_ids, *cover.source_ids]))
    return candidate


async def generate(request: DesignRequest, client=fast_llm_client,
                   *, profile: TemplateProfile | None = None) -> ContentPlan:
    config, template, _ = _story_configuration()
    excerpts = source_excerpts(request.script)
    payload = request.model_dump(exclude={"script"}) | {
        "sources": [s.model_dump() for s in excerpts],
    }
    use_cover = profile is not None and request.slide_count > 1 and bool(cover_patterns(profile))
    if profile is not None:
        payload["template_layout"] = composition_brief(profile, request.slide_count)
    if use_cover:
        payload["template_layout"].update(cover_brief(profile))
    prompt = template.replace("{payload}", json.dumps(payload, ensure_ascii=False))
    current = prompt
    errors = []
    response_error = None
    last_plan = None
    for _ in range(config["attempts"]):
        repairing = last_plan is not None and (
            len(last_plan.slides) == request.slide_count
            or (request.count_mode == "maximum" and len(last_plan.slides) <= request.slide_count)
        )
        try:
            local = _local_repairs(errors, payload, last_plan) if repairing else None
            if local and local[0] and len(last_plan.slides) < 2:
                local = None
            if local:
                plan = await _repair_fields(client, last_plan, payload, local)
            else:
                reply = await client.generate_json(current, ContentPlan)
            if repairing and not local:
                previous = {slide.id: slide for slide in last_plan.slides}
                unknown = {slide.id for slide in reply.slides} - previous.keys()
                if unknown:
                    response_error = None
                    errors = ["Исправление содержит неизвестные id. Сохраняйте id предыдущего плана."]
                    current = _correction_prompt(prompt, last_plan, errors, patch=True, payload=payload)
                    continue
                updates = {slide.id: slide for slide in reply.slides}
                plan = last_plan.model_copy(update={"slides": [
                    updates.get(slide.id, slide) for slide in last_plan.slides
                ]})
            elif not local:
                plan = reply
        except LLMGenerationError as error:
            if not getattr(error, "invalid_response", False):
                raise
            response_error = error
            errors = list(dict.fromkeys([*errors,
                "Ответ не соответствует JSON Schema ContentPlan. Соблюдайте ограничения схемы.",
            ]))
        else:
            response_error = None
            if use_cover:
                plan = _redistribute_cover(profile, plan)
            last_plan = plan
            errors = validate_story(plan, request, excerpts)
            if profile is not None:
                errors.extend(story_layout_issues(
                    profile, plan, request.datasets, ignore_cover=use_cover,
                ))
            if use_cover and not cover_fits(profile, plan.slides[0]):
                errors.append(
                    "Первый слайд не помещается на обложке шаблона. Сократите название темы "
                    "и оставьте один короткий подзаголовок без visual. Все содержательные "
                    "факты распределите по следующим слайдам, сохранив общее число слайдов. "
                    + json.dumps(payload["template_layout"], ensure_ascii=False)
                )
        if not errors:
            return plan
        patch = last_plan is not None and (
            len(last_plan.slides) == request.slide_count
            or (request.count_mode == "maximum" and len(last_plan.slides) <= request.slide_count)
        )
        current = _correction_prompt(prompt, last_plan, errors, patch=patch, payload=payload)
    raise StoryValidationError(errors, last_plan) from response_error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    args = parser.parse_args()

    async def run():
        try:
            setup_logging()
            request = DesignRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
            config, _, provenance = _story_configuration()
            if not settings.llm_api_key.strip():
                raise LLMCredentialsError("Не настроен ключ доступа к модели")
            async with asyncio.timeout(config["timeout_seconds"]):
                if args.profile:
                    profile = TemplateProfile.model_validate_json(
                        args.profile.read_text(encoding="utf-8"),
                    )
                    plan = await generate(request, profile=profile)
                else:
                    plan = await generate(request)
        except StoryValidationError as error:
            # Повторы закончились: сохраняем доступный план, а замечания pipeline
            # повторно вычислит и покажет рядом с готовой презентацией.
            if error.plan is None or story_reference_issues(error.plan, request):
                raise
            plan = error.plan
        finally:
            await _close_client()
        await asyncio.to_thread(
            args.output.write_text, plan.model_dump_json(indent=2), encoding="utf-8",
        )
        await asyncio.to_thread(
            args.output.with_name("story-provenance.json").write_text,
            json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    try:
        asyncio.run(run())
    except Exception as error:
        code = content_error_code(error, credentials_configured=bool(settings.llm_api_key.strip()))
        if isinstance(error, StoryValidationError):
            # Отдельный внутренний файл: сырой ответ провайдера и настройки сюда не попадают.
            # Download API студии не открывает этот файл; stdout/stderr остаются безопасными.
            try:
                args.output.with_suffix(".diagnostics.json").write_text(json.dumps({
                    "code": code, "issues": error.issues,
                    "last_validated_plan": error.plan.model_dump(mode="json") if error.plan else None,
                }, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError:
                pass  # Ошибка диагностики не должна подменять причину сбоя генерации.
        print(PUBLIC_ERROR_MESSAGES[code], file=sys.stderr)
        return CONTENT_ERROR_EXIT_CODES.get(code, 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
