from math import isfinite
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
            elements = slide.get("elements", [])
            for element in elements:
                if element.get("type") == "text" and element.get("placeholder_type"):
                    text = element.get("text", {}).get("full_text", "")
                    max_length = cls._estimate_max_length(element, elements)
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
    def _estimate_max_length(
        cls, element: dict, elements: Optional[list[dict]] = None
    ) -> Optional[int]:
        """Приблизительная вместимость с учётом геометрии и размера шрифта.

        Короткий текст-заполнитель не ограничивает весь доступный блок. Без
        размеров блока или разрешённого размера шрифта остаётся прежняя оценка
        по образцу. Эвристика не заменяет визуальную проверку готового слайда.
        """
        text_data = element.get("text") or {}
        text = text_data.get("full_text", "")
        sample_length = len(text)
        fallback = int(sample_length * 1.3) if text else None
        bbox = element.get("bbox") or {}
        width = cls._positive_number(bbox.get("width"))
        height = cls._positive_number(bbox.get("height"))
        font_sizes = [
            size
            for paragraph in text_data.get("paragraphs", [])
            for run in paragraph.get("runs", [])
            if (size := cls._positive_number((run.get("style") or {}).get("size_pt")))
            is not None
        ]
        if width is None or height is None or not font_sizes:
            return fallback

        # BBox хранится в EMU, шрифт — в пунктах. Отступы и средняя ширина
        # символа выбраны с запасом, в том числе для кириллицы и широких букв.
        font_size = max(font_sizes)
        placeholder_type = (element.get("placeholder_type") or "").upper()
        if placeholder_type in {"TITLE", "CENTER_TITLE", "VERTICAL_TITLE"}:
            width, height = cls._available_title_box(
                element, elements or [], width, height, font_size
            )
        usable_width = width / 12700 * 0.9
        usable_height = height / 12700 * 0.95
        character_width = font_size * 0.7
        line_height = font_size * 1.1
        columns = usable_width / character_width

        if columns < 1 or usable_height < font_size * 0.65:
            # Исходный текст не доказывает, что он помещается в вырожденный
            # блок: не переносим его длину как нижнюю границу в этом случае.
            return max(1, int(columns * min(1, usable_height / line_height)))

        # Первая строка занимает высоту шрифта, между последующими строками
        # нужен интервал. Деление всей высоты на интервал занижает число строк:
        # блок 39.9 pt вмещает две строки 18 pt (18 + 19.8), а не одну.
        lines = 1 + int(max(0, usable_height - font_size) / line_height)
        geometry_length = max(1, int(columns)) * lines
        if placeholder_type in {"TITLE", "CENTER_TITLE", "VERTICAL_TITLE"}:
            semantic_limit = 100
        elif placeholder_type in {"FOOTER", "HEADER", "DATE", "SLIDE_NUMBER"}:
            semantic_limit = 80
        elif placeholder_type == "SUBTITLE":
            semantic_limit = 300
        else:
            semantic_limit = 1000

        # Геометрия приблизительна. Уже существующий текст нормального блока
        # сохраняет свою длину даже при более консервативной оценке.
        return max(sample_length, min(geometry_length, semantic_limit))

    @classmethod
    def _available_title_box(
        cls, element: dict, elements: list[dict], width: float, height: float, font_size: float
    ) -> tuple[float, float]:
        """Свободный прямоугольник заголовка перед передними соседними блоками.

        В шаблонах рамка короткого заголовка иногда продолжается под фотографией
        или основным текстом. Ограничиваем её только при явно известном z_order;
        фон и фигуры, содержащие заголовок, не считаем препятствиями. Это локальная
        эвристика, а не полная модель обтекания фигур или измерение текста шрифтом.
        """
        bbox = element.get("bbox") or {}
        left = cls._finite_number(bbox.get("left"))
        top = cls._finite_number(bbox.get("top"))
        z_order = cls._finite_number(element.get("z_order"))
        if left is None or top is None or z_order is None:
            return width, height

        peers = []
        for peer in elements:
            peer_z = cls._finite_number(peer.get("z_order"))
            if peer is element or peer_z is None or peer_z <= z_order:
                continue
            peer_box = peer.get("bbox") or {}
            peer_left = cls._finite_number(peer_box.get("left"))
            peer_top = cls._finite_number(peer_box.get("top"))
            peer_width = cls._positive_number(peer_box.get("width"))
            peer_height = cls._positive_number(peer_box.get("height"))
            if None in (peer_left, peer_top, peer_width, peer_height):
                continue
            peers.append((peer.get("type"), peer_left, peer_top, peer_width, peer_height))

        # Сначала оставляем место для текста или таблицы под заголовком. Верхняя граница
        # соседа должна начинаться внутри рамки, а не над ней (как у фона).
        for peer_type, peer_left, peer_top, peer_width, _ in peers:
            horizontal_overlap = min(left + width, peer_left + peer_width) - max(left, peer_left)
            if (
                peer_type in {"text", "table"}
                and horizontal_overlap > 0
                and top < peer_top < top + height
            ):
                height = min(height, peer_top - top)

        for peer_type, peer_left, peer_top, _, peer_height in peers:
            vertical_overlap = min(top + height, peer_top + peer_height) - max(top, peer_top)
            meaningful_overlap = min(height * 0.5, font_size * 12700)
            if (
                peer_type in {"image", "other"}
                and left < peer_left < left + width
                and vertical_overlap >= meaningful_overlap
            ):
                width = min(width, peer_left - left)
        return width, height

    @staticmethod
    def _finite_number(value: object) -> Optional[float]:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not isfinite(value):
            return None
        return float(value)

    @classmethod
    def _positive_number(cls, value: object) -> Optional[float]:
        number = cls._finite_number(value)
        return number if number is not None and number > 0 else None
