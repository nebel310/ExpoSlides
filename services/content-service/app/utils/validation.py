from app.models.graph_state import GeneratedSlideContent, ValidationReport
from app.models.presentation import PresentationData
from app.utils.grounding import (
    extract_fact_tokens,
    extract_significant_words,
    find_unsupported_claim_markers,
)


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
        for slide in presentation.slides:
            if slide_indices is not None and slide.index not in slide_indices:
                continue

            slide_content = content.get(slide.index)
            if not slide_content:
                if any(ph.text for ph in slide.placeholders):
                    issues.append(f"Слайд {slide.index}: нет сгенерированного контента")
                continue

            for ph in slide.placeholders:
                generated_text = None
                if ph.idx is not None:
                    generated_text = slide_content.placeholders.get(str(ph.idx))
                if generated_text is None and ph.name:
                    generated_text = slide_content.placeholders.get(ph.name)
                if generated_text is None and ph.placeholder_type:
                    generated_text = slide_content.placeholders.get(ph.placeholder_type)

                if generated_text is None or not generated_text.strip():
                    if ph.text:
                        issues.append(f"Слайд {slide.index}, placeholder {ph.name or ph.idx}: не заполнен")
                    continue

                if ph.max_length and len(generated_text) > ph.max_length:
                    issues.append(
                        f"Слайд {slide.index}, placeholder {ph.name or ph.idx}: текст длиннее максимума "
                        f"({len(generated_text)} > {ph.max_length})"
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
                overlap_ratio = len(source_words & generated_words) / len(source_words)
                if overlap_ratio < 0.15:
                    issues.append(
                        "Текст слайдов недостаточно связан с исходным материалом "
                        f"(совпадение значимых слов {overlap_ratio:.0%})"
                    )

        ok = len(issues) == 0
        return ValidationReport(ok=ok, issues=issues)
