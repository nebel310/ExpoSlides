from app.models.graph_state import GeneratedSlideContent, ValidationReport
from app.models.presentation import PresentationData


class ContentValidator:
    """Программная валидация сгенерированного контента"""

    @classmethod
    async def validate(
        cls,
        presentation: PresentationData,
        content: dict[int, GeneratedSlideContent],
        slide_indices: set[int] | None = None,
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

        ok = len(issues) == 0
        return ValidationReport(ok=ok, issues=issues)
