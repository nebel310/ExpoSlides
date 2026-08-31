from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def collect_generated_text(response: dict[str, Any]) -> str:
    text_fragments = []
    for slide in response.get("content", {}).values():
        text_fragments.extend(str(value) for value in slide.get("placeholders", {}).values())
    return "\n".join(text_fragments)


def score_response(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    generated_text = _normalize(collect_generated_text(response))
    preserved_facts = [
        fact for fact in case["must_preserve"] if _normalize(fact) in generated_text
    ]
    forbidden_hits = [
        claim for claim in case["forbidden_claims"] if _normalize(claim) in generated_text
    ]
    slide_count = len(response.get("content", {}))
    max_slides = case["settings"]["max_slides"]
    slide_limit_ok = slide_count <= max_slides
    fact_recall = len(preserved_facts) / len(case["must_preserve"])
    score = round(
        max(0.0, min(1.0, fact_recall - 0.25 * len(forbidden_hits) - (0 if slide_limit_ok else 0.2)))
        * 100
    )
    return {
        "case_id": case["id"],
        "score": score,
        "fact_recall": round(fact_recall, 3),
        "preserved_facts": preserved_facts,
        "missing_facts": [fact for fact in case["must_preserve"] if fact not in preserved_facts],
        "forbidden_hits": forbidden_hits,
        "slide_count": slide_count,
        "slide_limit_ok": slide_limit_ok,
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
