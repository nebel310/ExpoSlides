import re

from app.models.graph_state import GeneratedSlideContent, ValidationReport
from app.models.presentation import PresentationData
from app.utils.grounding import (
    extract_fact_tokens,
    extract_significant_words,
    find_unsupported_claim_markers,
)

LIST_PLACEHOLDER_TYPES = {
    "BODY",
    "OBJECT",
    "TEXT",
    "VERTICAL_BODY",
    "VERTICAL_OBJECT",
}
LIST_MARKER_PATTERN = re.compile(r"^(?:[-+–—*•]\s+|\d+[.)]\s+)")


class ContentValidator:
    """Программная валидация сгенерированного контента"""

    @classmethod
    async def validate(
        cls,
        presentation: PresentationData,
        content: dict[int, GeneratedSlideContent],
        slide_indices: set[int] | None = None,
        source_text: str | None = None,
    ) -> ValidationReport:
        """Проверка полноты и длины текста"""
        issues = []
        expected_slide_indices = (
            slide_indices
            if slide_indices is not None
            else {slide.index for slide in presentation.slides}
        )
        unexpected_slide_indices = sorted(content.keys() - expected_slide_indices)
        if unexpected_slide_indices:
            issues.append(
                "Контент содержит слайды вне плана: "
                + ", ".join(map(str, unexpected_slide_indices))
            )

        for slide in presentation.slides:
            if slide_indices is not None and slide.index not in slide_indices:
                continue

            slide_content = content.get(slide.index)
            if not slide_content:
                if slide.placeholders:
                    issues.append(f"Слайд {slide.index}: нет сгенерированного контента")
                continue

            available_keys = {
                str(placeholder.idx)
                if placeholder.idx is not None
                else placeholder.name
                for placeholder in slide.placeholders
                if placeholder.idx is not None or placeholder.name is not None
            }
            unexpected_keys = sorted(slide_content.placeholders.keys() - available_keys)
            if unexpected_keys:
                issues.append(
                    f"Слайд {slide.index}: неизвестные placeholders: "
                    + ", ".join(unexpected_keys)
                )

            for ph in slide.placeholders:
                generated_text = None
                if ph.idx is not None:
                    generated_text = slide_content.placeholders.get(str(ph.idx))
                if generated_text is None and ph.name:
                    generated_text = slide_content.placeholders.get(ph.name)

                if generated_text is None or not generated_text.strip():
                    issues.append(
                        f"Слайд {slide.index}, placeholder {ph.name or ph.idx}: не заполнен"
                    )
                    continue

                if ph.max_length and len(generated_text) > ph.max_length:
                    issues.append(
                        f"Слайд {slide.index}, placeholder {ph.name or ph.idx}: текст длиннее максимума "
                        f"({len(generated_text)} > {ph.max_length})"
                    )

                if (
                    ph.placeholder_type in LIST_PLACEHOLDER_TYPES
                    and contains_manual_list_markers(generated_text)
                ):
                    issues.append(
                        f"Слайд {slide.index}, placeholder {ph.name or ph.idx}: "
                        "текст содержит ручные маркеры списка; нужны только строки пунктов"
                    )

                if (
                    ph.placeholder_type in LIST_PLACEHOLDER_TYPES
                    and contains_blank_list_items(generated_text)
                ):
                    issues.append(
                        f"Слайд {slide.index}, placeholder {ph.name or ph.idx}: "
                        "список содержит пустые строки"
                    )

        if source_text:
            generated_text = "\n".join(
                placeholder_text
                for slide_content in content.values()
                for placeholder_text in slide_content.placeholders.values()
            )
            source_fact_tokens = extract_fact_tokens(source_text)
            generated_fact_tokens = extract_fact_tokens(generated_text)
            missing_fact_tokens = sorted(source_fact_tokens - generated_fact_tokens)
            unexpected_fact_tokens = sorted(generated_fact_tokens - source_fact_tokens)
            if missing_fact_tokens:
                issues.append(
                    "Исходные числовые факты отсутствуют в результате: "
                    + ", ".join(missing_fact_tokens)
                )
            if unexpected_fact_tokens:
                issues.append(
                    "Результат содержит числовые факты не из источника: "
                    + ", ".join(unexpected_fact_tokens)
                )

            unsupported_claims = sorted(
                find_unsupported_claim_markers(source_text, generated_text)
            )
            if unsupported_claims:
                issues.append(
                    "Результат содержит неподтверждённые оценки или сравнения: "
                    + ", ".join(unsupported_claims)
                )

            source_words = extract_significant_words(source_text)
            generated_words = extract_significant_words(generated_text)
            if len(source_words) >= 4:
                shared_words = source_words & generated_words
                # Проверяем привязку результата к источнику, а не долю слов длинного
                # доклада, перенесённых в краткие слайды. Минимум общих слов защищает
                # от пустого результата и повторения одного тематического термина.
                overlap_ratio = len(shared_words) / max(1, len(generated_words))
                if len(shared_words) < 4 or overlap_ratio < 0.30:
                    issues.append(
                        "Текст слайдов недостаточно связан с исходным материалом "
                        f"(совпадение значимых слов результата {overlap_ratio:.0%}, "
                        f"общих слов {len(shared_words)})"
                    )

        ok = len(issues) == 0
        return ValidationReport(ok=ok, issues=issues)


def contains_manual_list_markers(text: str) -> bool:
    lines = [line.lstrip() for line in text.splitlines() if line.strip()]
    return bool(lines) and any(LIST_MARKER_PATTERN.match(line) for line in lines)


def contains_blank_list_items(text: str) -> bool:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n" in normalized and any(not line.strip() for line in normalized.split("\n"))
