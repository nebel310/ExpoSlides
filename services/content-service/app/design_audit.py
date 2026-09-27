"""Необязательный визуально-контекстуальный аудит через настроенный Qwen endpoint."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chains.chat_completions import ChatCompletionsResponseError  # noqa: E402
from app.chains.llm import LLMClient, fast_llm_client  # noqa: E402
from app.config import settings, setup_logging  # noqa: E402
from app.design_config import model_for_role, role_config, role_prompt  # noqa: E402
from app.errors import LLMGenerationError  # noqa: E402
from pydantic import Field, ValidationError  # noqa: E402

from exposlides.design_models import AuditIssue, AuditReport, Contract  # noqa: E402

RULES = (
    "title_conclusion", "title_alignment", "one_message", "source_grounding", "nonempty",
    "visual_relevance", "prompt_artifacts", "spelling", "language_consistency",
    "visual_support", "narrative_flow",
)
Rule = Literal[
    "title_conclusion", "title_alignment", "one_message", "source_grounding", "nonempty",
    "visual_relevance", "prompt_artifacts", "spelling", "language_consistency",
    "visual_support", "narrative_flow",
]


class AuditSlide(Contract):
    id: str = Field(min_length=1, max_length=100)
    image_path: Path
    text: str = Field(max_length=30_000)
    source_text: str = Field(max_length=100_000)
    source_ids: list[str] = Field(default_factory=list)


class ContextualAuditRequest(Contract):
    enabled: bool = False
    slides: list[AuditSlide] = Field(min_length=1, max_length=50)
    timeout_seconds: float = Field(default=120, gt=0, le=180)
    concurrency: int = Field(default=3, ge=1, le=4)


class Finding(Contract):
    rule: Rule
    severity: Literal["error", "warning", "info"] = "warning"
    message: str = Field(min_length=1, max_length=1000)
    evidence: str = Field(min_length=1, max_length=2000)


class SlideVerdict(Contract):
    findings: list[Finding] = Field(default_factory=list, max_length=30)
    checked_rules: list[Rule] = Field(min_length=1)


def _image_url(path: Path) -> str:
    """Внешние URL и произвольные двоичные файлы не отправляются как изображения."""
    if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Изображение отсутствует или превышает 8 МБ")
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    else:
        raise ValueError("Для аудита требуется PNG или JPEG")
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


class VisionAuditClient:
    async def inspect(self, prompt: str, image_url: str) -> SlideVerdict:
        model_for_role("contextual_auditor", settings.llm_fast_model)
        if not settings.llm_api_key.strip():
            raise LLMGenerationError("Не настроен ключ контекстуального аудита")
        current = prompt
        attempts = role_config("contextual_auditor")["attempts"]
        for attempt in range(attempts):
            payload = LLMClient._chat_payload(
                current, SlideVerdict.model_json_schema(), True, settings.llm_fast_model,
            )
            payload["messages"][0]["content"] = [
                {"type": "text", "text": current},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]
            try:
                response = await fast_llm_client._achat_with_transient_retry(payload)
                content = response.choices[0].message.content if response.choices else None
                if not isinstance(content, str):
                    raise ValueError("Нет структурированного ответа")
                result = SlideVerdict.model_validate(LLMClient._parse_json_object(content))
                if set(result.checked_rules) != set(RULES):
                    raise ValueError("Проверены не все правила аудита")
                return result
            except (ValueError, ValidationError, ChatCompletionsResponseError):
                if attempt == attempts - 1:
                    raise LLMGenerationError("Некорректный ответ контекстуального аудита") from None
                current = prompt + (
                    "\nПредыдущий ответ некорректен. Верните JSON по схеме. "
                    "В checked_rules перечислите все заданные правила, findings содержит "
                    "только обнаруженные проблемы с конкретным свидетельством."
                )
        raise AssertionError("unreachable")


async def audit(
    request: ContextualAuditRequest, client: VisionAuditClient | None = None,
) -> AuditReport:
    if not request.enabled:
        return AuditReport(contextual_status="not_run", limitations=[
            "Контекстуальный аудит не запускался: поддержка изображений endpoint не подтверждена.",
        ])
    if len({slide.id for slide in request.slides}) != len(request.slides):
        raise ValueError("Повторные идентификаторы слайдов аудита")
    client = client or VisionAuditClient()
    config = role_config("contextual_auditor")
    template = role_prompt("contextual_auditor")
    semaphore = asyncio.Semaphore(min(request.concurrency, config["concurrency"]))

    async def inspect(index: int, slide: AuditSlide) -> SlideVerdict:
        async with semaphore:
            image = await asyncio.to_thread(_image_url, slide.image_path)
            payload = {
                "slide_id": slide.id, "source": slide.source_text, "text": slide.text,
                "previous_slide_text": request.slides[index - 1].text if index else "",
                "rules": RULES,
            }
            prompt = template.replace("{payload}", json.dumps(payload, ensure_ascii=False))
            return await client.inspect(prompt, image)

    tasks = [asyncio.create_task(inspect(index, slide))
             for index, slide in enumerate(request.slides)]
    timed_out = False
    try:
        async with asyncio.timeout(min(request.timeout_seconds, config["timeout_seconds"])):
            results = await asyncio.gather(*tasks, return_exceptions=True)
    except TimeoutError:
        timed_out = True
        for task in tasks:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    issues = []
    limitations = []
    if timed_out:
        limitations.append("Контекстуальный аудит превысил общий лимит ожидания.")
    completed = 0
    for slide, result in zip(request.slides, results, strict=True):
        if isinstance(result, BaseException):
            limitations.append(f"Слайд {slide.id}: контекстуальная проверка не завершена.")
            continue
        completed += 1
        for index, finding in enumerate(result.findings):
            identifier = hashlib.sha256(
                f"{slide.id}:{finding.rule}:{index}:{finding.message}".encode(),
            ).hexdigest()[:16]
            issues.append(AuditIssue(
                id=f"context-{identifier}", rule=f"contextual.{finding.rule}",
                check_type="contextual", severity=finding.severity,
                slide_id=slide.id, message=finding.message, evidence=finding.evidence,
                source_ids=slide.source_ids, fix="none",
            ))
    return AuditReport(
        issues=issues, checks=[f"contextual.{rule}" for rule in RULES] if completed else [],
        contextual_status=(
            "completed" if completed == len(request.slides) and not timed_out else "failed"
        ),
        limitations=limitations,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    setup_logging()

    async def run():
        request = ContextualAuditRequest.model_validate_json(
            args.request.read_text(encoding="utf-8"),
        )
        try:
            report = await audit(request)
        finally:
            await fast_llm_client.aclose()
        args.output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return 0 if report.contextual_status != "failed" else 1

    try:
        return asyncio.run(run())
    except Exception:
        print("Не удалось выполнить контекстуальную проверку слайдов.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
