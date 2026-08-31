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
