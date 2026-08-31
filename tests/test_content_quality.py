import runpy
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTENT_APP_ROOT = REPOSITORY_ROOT / "services" / "content-service" / "app"


def test_retry_prompt_contains_validation_feedback() -> None:
    prompt_constants = runpy.run_path(str(CONTENT_APP_ROOT / "chains" / "prompts.py"))

    prompt = prompt_constants["GENERATE_CONTENT_PROMPT"].format(
        language="ru",
        tone="professional",
        complexity="medium",
        analysis_context="Факт: рост составил 18%",
        slide_info="Слайд 1",
        slide_plan="Заголовок и тезисы",
        issues="Текст заголовка слишком длинный",
    )

    assert "Текст заголовка слишком длинный" in prompt
