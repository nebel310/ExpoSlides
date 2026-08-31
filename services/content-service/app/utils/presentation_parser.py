from typing import Optional

from app.models.presentation import (
    LayoutData,
    LayoutPlaceholderData,
    PlaceholderData,
    PresentationData,
    SlideData,
)


class PresentationParser:
    """Парсер полного JSON презентации в упрощённую модель"""

    @classmethod
    def parse(cls, presentation_json: dict) -> PresentationData:
        """Преобразование полного JSON в PresentationData"""
        slides = []
        for slide in presentation_json.get("slides", []):
            placeholders = []
            for element in slide.get("elements", []):
                if element.get("type") == "text" and element.get("placeholder_type"):
                    text = element.get("text", {}).get("full_text", "")
                    max_length = cls._estimate_max_length(element)
                    placeholders.append(
                        PlaceholderData(
                            idx=element.get("placeholder_idx"),
                            name=element.get("placeholder_name"),
                            placeholder_type=element.get("placeholder_type"),
                            text=text,
                            max_length=max_length,
                        )
                    )
            slides.append(
                SlideData(
                    index=slide.get("index", 0),
                    layout_type=slide.get("layout_type"),
                    layout_name=slide.get("layout_name"),
                    placeholders=placeholders,
                    notes=slide.get("notes"),
                )
            )

        layouts = []
        for layout in presentation_json.get("layouts", []):
            placeholders = []
            for ph in layout.get("placeholders", []):
                placeholders.append(
                    LayoutPlaceholderData(
                        placeholder_type=ph.get("placeholder_type"),
                        name=ph.get("name"),
                        idx=ph.get("idx"),
                    )
                )
            layouts.append(
                LayoutData(
                    name=layout.get("name"),
                    index=layout.get("index"),
                    placeholders=placeholders,
                )
            )

        return PresentationData(
            slide_width=presentation_json.get("slide_width", 0),
            slide_height=presentation_json.get("slide_height", 0),
            slides=slides,
            layouts=layouts,
            theme=presentation_json.get("theme") or {},
        )

    @classmethod
    def _estimate_max_length(cls, element: dict) -> Optional[int]:
        """Оценка максимальной длины текста"""
        text = element.get("text", {}).get("full_text", "")
        if text:
            return int(len(text) * 1.3)
        return None