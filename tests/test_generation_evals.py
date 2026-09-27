from __future__ import annotations

import json
import runpy
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = REPOSITORY_ROOT / "evals"


def _load_cases() -> list[dict]:
    return json.loads((EVAL_ROOT / "generation_cases.json").read_text(encoding="utf-8"))


def test_eval_cases_have_valid_grounding_contracts() -> None:
    cases = _load_cases()
    case_ids = [case["id"] for case in cases]

    assert len(cases) >= 3
    assert len(case_ids) == len(set(case_ids))
    for case in cases:
        normalized_script = case["script"].casefold()
        assert case["must_preserve"]
        assert all(fact.casefold() in normalized_script for fact in case["must_preserve"])
        assert all(claim.casefold() not in normalized_script for claim in case["forbidden_claims"])
        assert case["settings"]["max_slides"] >= 1


def test_eval_scorer_separates_grounded_and_incorrect_outputs() -> None:
    scorer = runpy.run_path(str(EVAL_ROOT / "score.py"))
    case = _load_cases()[0]
    grounded_response = {
        "content": {
            "1": {
                "placeholders": {
                    "0": "Во втором квартале 2026 года выручка составила 42 млн рублей",
                    "1": "Рост 18%, валовая маржа 27%",
                }
            }
        }
    }
    incorrect_response = {
        "content": {
            "1": {
                "placeholders": {
                    "0": "В 2025 году выручка составила 50 млн рублей",
                    "1": "Рост на 27%",
                }
            }
        }
    }

    grounded_score = scorer["score_response"](case, grounded_response)
    incorrect_score = scorer["score_response"](case, incorrect_response)

    assert grounded_score["score"] == 100
    assert grounded_score["fact_recall"] == 1.0
    assert incorrect_score["score"] < grounded_score["score"]
    assert incorrect_score["forbidden_hits"]


def test_fifteen_slide_eval_rejects_one_slide_with_only_four_fact_tokens() -> None:
    scorer = runpy.run_path(str(EVAL_ROOT / "score.py"))
    case = next(case for case in _load_cases() if case["id"] == "fast-product-review-15")
    response = {"content": {"1": {"placeholders": {"0": "2026; 42 млн рублей; 18%; 27%"}}}}
    result = scorer["score_response"](case, response)
    assert result["fact_recall"] == 1.0
    assert not result["slide_count_ok"]
    assert result["missing_messages"]
    assert result["score"] < 100


def test_fifteen_slide_eval_rejects_duplicate_padding() -> None:
    scorer = runpy.run_path(str(EVAL_ROOT / "score.py"))
    case = next(case for case in _load_cases() if case["id"] == "fast-product-review-15")
    response = {"content": {
        str(index): {"placeholders": {"0": case["script"]}}
        for index in range(1, 16)
    }}
    result = scorer["score_response"](case, response)
    assert result["slide_count_ok"]
    assert result["duplicate_slides"] == 14
    assert result["score"] < 100


def test_scorer_rejects_swapped_metric_bindings_even_if_tokens_survive() -> None:
    scorer = runpy.run_path(str(EVAL_ROOT / "score.py"))
    case = {
        "id": "metric-binding",
        "script": "Выручка составила 10 млн рублей, прибыль составила 2 млн рублей.",
        "must_preserve": ["10 млн рублей", "2 млн рублей"],
        "forbidden_claims": [], "settings": {"max_slides": 3},
    }
    response = {"content": {"1": {"placeholders": {
        "0": "Выручка составила 2 млн рублей, прибыль составила 10 млн рублей.",
    }}}}
    result = scorer["score_response"](case, response)
    assert result["fact_recall"] == 1.0
    assert result["semantic_issues"]
    assert result["score"] < 100


def test_scorer_rejects_explicitly_invalid_output() -> None:
    scorer = runpy.run_path(str(EVAL_ROOT / "score.py"))
    case = _load_cases()[0]
    response = {
        "content": {"1": {"placeholders": {"0": case["script"]}}},
        "validation_report": {"ok": False, "issues": ["Неверный контент"]},
    }
    result = scorer["score_response"](case, response)
    assert not result["output_valid"]
    assert result["score"] == 0


def test_scorer_handles_malformed_content_without_crashing() -> None:
    scorer = runpy.run_path(str(EVAL_ROOT / "score.py"))
    case = _load_cases()[0]
    for response in ({"content": []}, {"content": {"1": None}}, {"content": {}}):
        result = scorer["score_response"](case, response)
        assert result["score"] == 0
        assert not result["output_valid"]


def test_target_count_is_not_inferred_from_maximum() -> None:
    scorer = runpy.run_path(str(EVAL_ROOT / "score.py"))
    case = _load_cases()[0]
    response = {"content": {"1": {"placeholders": {"0": case["script"]}}}}
    result = scorer["score_response"](case, response)
    assert result["slide_count_ok"]
    assert result["score"] == 100
