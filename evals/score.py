from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def collect_generated_text(response: dict[str, Any]) -> str:
    text_fragments = []
    content = response.get("content", {})
    if not isinstance(content, dict):
        return ""
    for slide in content.values():
        if not isinstance(slide, dict) or not isinstance(slide.get("placeholders"), dict):
            continue
        text_fragments.extend(value for value in slide["placeholders"].values()
                              if isinstance(value, str))
    return "\n".join(text_fragments)


@lru_cache(maxsize=1)
def _grounding() -> ModuleType:
    """Один pure-модуль без импорта конфликтующих service-пакетов app и настроек."""
    path = (Path(__file__).resolve().parents[1] / "services" / "content-service"
            / "app" / "utils" / "fact_grounding.py")
    name = "_exposlides_eval_fact_grounding"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Не удалось загрузить проверки фактов")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _output_issues(response: dict[str, Any]) -> list[str]:
    issues = []
    content = response.get("content")
    if not isinstance(content, dict) or not content:
        return ["Нет непустого объекта content"]
    for key, slide in content.items():
        fields = slide.get("placeholders") if isinstance(slide, dict) else None
        if not isinstance(fields, dict) or not fields or any(
            not isinstance(value, str) or not value.strip() for value in fields.values()
        ):
            issues.append(f"Слайд {key}: некорректные или пустые текстовые поля")
    validation = response.get("validation_report", response.get("validation"))
    if isinstance(validation, dict) and validation.get("ok") is False:
        issues.append("Результат отклонён валидацией pipeline")
    return issues


def score_response(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    raw_text = collect_generated_text(response)
    generated_text = _normalize(raw_text)
    preserved_facts = [
        fact for fact in case["must_preserve"] if _normalize(fact) in generated_text
    ]
    forbidden_hits = [
        claim for claim in case["forbidden_claims"] if _normalize(claim) in generated_text
    ]
    content = response.get("content", {})
    slide_count = len(content) if isinstance(content, dict) else 0
    max_slides = case["settings"]["max_slides"]
    min_slides = case["settings"].get("min_slides", 1)
    target_slides = case["settings"].get("target_slides")
    slide_limit_ok = slide_count <= max_slides
    slide_count_ok = slide_limit_ok and slide_count >= min_slides
    if target_slides is not None:
        slide_count_ok = slide_count_ok and slide_count == target_slides
    fact_recall = len(preserved_facts) / len(case["must_preserve"]) if case["must_preserve"] else 1.0
    required_messages = list(case.get("required_messages", []))
    if case.get("require_all_sections"):
        required_messages.extend(section["text"] for section in case.get("sections", []))
    missing_messages = _grounding().missing_required_messages(raw_text, required_messages)
    message_recall = 1 - len(missing_messages) / len(required_messages) if required_messages else 1.0
    semantic_issues = _grounding().semantic_content_issues(case.get("script", ""), raw_text)
    output_issues = _output_issues(response)
    slide_texts = [
        _normalize(collect_generated_text({"content": {"slide": slide}}))
        for slide in content.values()
    ] if isinstance(content, dict) else []
    duplicate_slides = sum(count - 1 for text, count in Counter(slide_texts).items()
                           if text and count > 1)
    score = round(
        max(0.0, min(1.0, min(fact_recall, message_recall)
                     - 0.25 * len(forbidden_hits) - 0.25 * len(semantic_issues)
                     - (0 if slide_count_ok else 0.2) - 0.1 * duplicate_slides))
        * 100
    )
    if output_issues:
        score = 0
    return {
        "case_id": case["id"],
        "score": score,
        "fact_recall": round(fact_recall, 3),
        "preserved_facts": preserved_facts,
        "missing_facts": [fact for fact in case["must_preserve"] if fact not in preserved_facts],
        "forbidden_hits": forbidden_hits,
        "slide_count": slide_count,
        "slide_limit_ok": slide_limit_ok,
        "slide_count_ok": slide_count_ok,
        "message_recall": round(message_recall, 3),
        "missing_messages": missing_messages,
        "semantic_issues": semantic_issues,
        "duplicate_slides": duplicate_slides,
        "output_valid": not output_issues,
        "output_issues": output_issues,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score a generated ExpoSlides response")
    parser.add_argument("case_id")
    parser.add_argument("response", type=Path)
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).with_name("generation_cases.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    case = next((candidate for candidate in cases if candidate["id"] == args.case_id), None)
    if case is None:
        raise SystemExit(f"Unknown case_id: {args.case_id}")
    response = json.loads(args.response.read_text(encoding="utf-8"))
    print(json.dumps(score_response(case, response), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
