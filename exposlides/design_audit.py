"""Детерминированный аудит и выборочные исправления плана верстки."""

from __future__ import annotations

import hashlib
import math
import re
import tomllib
from functools import lru_cache
from pathlib import Path

from exposlides.design_models import (
    AuditIssue,
    AuditReport,
    DeckPlan,
    PlacedBlock,
    SlidePattern,
    TemplateProfile,
)

EMU_PER_PT = 12700


@lru_cache(maxsize=1)
def audit_rules() -> dict:
    path = Path(__file__).resolve().parents[1] / "config/skills.toml"
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    if config.get("schema_version") != "1.0":
        raise ValueError("Неподдерживаемая версия правил аудита")
    rules = config["skills"]["deterministic_auditor"]
    for key in ("max_bullets", "max_bullet_words", "max_table_rows", "max_table_columns", "max_chart_series"):
        if not isinstance(rules[key], int) or not 1 <= rules[key] <= 100:
            raise ValueError(f"Некорректное правило {key}")
    if not 1 <= rules["minimum_contrast"] <= 21:
        raise ValueError("Некорректный порог контраста")
    return rules


def text_lines(block: PlacedBlock) -> int:
    """Консервативная оценка: не заменяет проверку рендера готового файла."""
    width_pt = max(1, block.box.width / EMU_PER_PT - 16)
    capacity = max(1, int(width_pt / (block.style.size * 0.54)))
    texts = block.items or [block.text]
    return sum(max(1, math.ceil(len(line) / capacity)) for text in texts for line in text.splitlines())


def capacity_risk(block: PlacedBlock) -> bool:
    return text_lines(block) * block.style.size * 1.25 + 12 > block.box.height / EMU_PER_PT


def _reference_size(block: PlacedBlock, pattern: SlidePattern) -> float:
    if block.source_shape_id is not None:
        slot = next((slot for slot in pattern.slots
                     if slot.shape_id == block.source_shape_id), None)
        if slot is not None:
            if slot.paragraph_font_sizes:
                count = sum(len(item.splitlines()) for item in (block.items or [block.text])) or 1
                return max(slot.paragraph_font_sizes[:count])
            return slot.style.size
    return pattern.title_style.size if block.kind == "title" else pattern.body_style.size


def contrast_ratio(first: str, second: str) -> float:
    def luminance(color):
        values = [int(color[i:i+2], 16)/255 for i in (0, 2, 4)]
        channels = [v/12.92 if v <= 0.04045 else ((v+0.055)/1.055)**2.4 for v in values]
        return sum(a*b for a, b in zip(channels, (0.2126, 0.7152, 0.0722), strict=True))
    values = sorted([luminance(first), luminance(second)])
    return (values[1]+0.05)/(values[0]+0.05)


def overlap_area(a, b):
    return max(0, min(a.left+a.width, b.left+b.width)-max(a.left, b.left)) * max(
        0, min(a.top+a.height, b.top+b.height)-max(a.top, b.top)
    )


def _issue(rule, severity, slide, block, message, fix="none", evidence=""):
    identity = f"{rule}:{slide.id}:{block.id if block else 'slide'}"
    return AuditIssue(
        id=hashlib.sha256(identity.encode()).hexdigest()[:16], rule=rule, severity=severity,
        slide_id=slide.id, block_id=block.id if block else None,
        box=block.box if block else None, message=message, fix=fix, evidence=evidence,
        source_ids=block.source_ids if block else [],
    )


def audit_deck(plan: DeckPlan, profile: TemplateProfile) -> AuditReport:
    rules = audit_rules()
    issues = []
    patterns = {p.source_slide_index: p for p in profile.patterns}
    seen = {}
    previous_layout = None
    layout_run = 0
    compositions = []
    cycle_reported = False
    for slide in plan.slides:
        pattern = patterns[slide.source_slide_index]
        body = [b for b in slide.blocks if b.kind not in {"title", "page_number"}]
        if not body:
            issues.append(_issue("empty_slide", "error", slide, None, "На слайде только заголовок"))
        if sum(len(b.items) for b in body if b.kind == "text") > rules["max_bullets"]:
            issues.append(_issue("slide_bullet_density", "warning", slide, None,
                                 f"На слайде больше {rules['max_bullets']} тезисов"))
        fonts = {b.style.font for b in slide.blocks}
        if len(fonts) > 2:
            issues.append(_issue("font_count", "warning", slide, None,
                                 "На слайде больше двух гарнитур"))
        allowed_fonts = {pattern.font, pattern.title_style.font, pattern.body_style.font}
        allowed_fonts.update(s.style.font for s in pattern.slots)
        signature = tuple((b.kind, b.text, tuple(b.items), b.dataset_id) for b in body)
        if signature and signature in seen:
            issues.append(_issue("duplicate_slide", "warning", slide, None,
                                 f"Содержимое повторяет слайд {seen[signature]}"))
        seen[signature] = slide.id
        composition = (slide.source_slide_index, tuple(sorted(
            (block.kind, block.box.left, block.box.top, block.box.width, block.box.height)
            for block in slide.blocks if block.kind != "page_number"
        )))
        layout_run = layout_run + 1 if composition == previous_layout else 1
        previous_layout = composition
        compositions.append(composition)
        for period in range(2, min(4, len(compositions) // 2) + 1):
            recent = compositions[-period:]
            if (not cycle_reported and len(set(recent)) > 1
                    and recent == compositions[-2 * period:-period]):
                issues.append(_issue("layout_cycle", "warning", slide, None,
                                     f"Повторяется цикл из {period} композиций шаблона"))
                cycle_reported = True
        if layout_run == 3:
            issues.append(_issue("repeated_layout", "warning", slide, None,
                                 "Три слайда подряд повторяют композицию шаблона; "
                                 "проверьте визуальное разнообразие"))
        for block in slide.blocks:
            b = block.box
            if block.style.font not in allowed_fonts:
                issues.append(_issue("template_font", "warning", slide, block,
                                     "Гарнитура отсутствует в исходном образце"))
            reference_size = _reference_size(block, pattern)
            if block.kind in {"title", "text"} and not 0.8*reference_size <= block.style.size <= reference_size*1.25:
                issues.append(_issue("type_scale", "warning", slide, block,
                                     "Кегль существенно отличается от исходного образца"))
            replaced_regions = [
                box for layer, photos in (("slide", pattern.replaceable_images),
                                          ("layout", pattern.layout_images))
                for sid, box in photos.items()
                if any(b.kind == "image" and b.source_shape_id == sid
                       and b.source_layer == layer for b in slide.blocks)
            ]
            for protected in pattern.protected_regions:
                if protected in replaced_regions:
                    continue
                if overlap_area(b, protected) > min(b.width*b.height, protected.width*protected.height)*0.02:
                    issues.append(_issue("protected_overlap", "error", slide, block,
                                         "Контент пересекает защищённый элемент шаблона"))
                    break
            if block.kind in {"text", "title"} and block.fill and contrast_ratio(block.style.color, block.fill) < rules["minimum_contrast"]:
                issues.append(_issue("contrast", "warning", slide, block,
                                     f"Контраст текста к заливке ниже {rules['minimum_contrast']}:1"))
            native_photo = block.kind == "image" and block.image_fit == "template" and (
                (pattern.layout_images if block.source_layer == "layout" else pattern.replaceable_images)
                .get(block.source_shape_id) == b
            )
            if not native_photo and (b.left < 0 or b.top < 0 or b.left+b.width > plan.width
                                     or b.top+b.height > plan.height):
                issues.append(_issue("outside_slide", "error", slide, block,
                                     "Объект выходит за границы слайда", "move_inside"))
            if block.kind in {"text", "title"} and capacity_risk(block):
                issues.append(_issue("text_capacity", "warning", slide, block,
                                     "Текст может не поместиться: проверьте изображение слайда",
                                     "fit_text", "Оценка по геометрии и кеглю, без измерения глифов"))
            if block.style.color.upper() not in [c.upper() for c in pattern.palette]:
                issues.append(_issue("palette", "warning", slide, block,
                                     "Цвет текста отсутствует в палитре темы", "palette"))
            text = "\n".join([block.text, *block.items])
            if re.search(r"lorem ipsum|\bTODO\b|\bXXX\b|вставьте текст", text, re.I):
                issues.append(_issue("placeholder", "error", slide, block,
                                     "В результате осталась служебная заглушка"))
            if block.kind == "text" and len(block.items) > rules["max_bullets"]:
                issues.append(_issue("bullet_density", "warning", slide, block,
                                     f"Более {rules['max_bullets']} тезисов в одном блоке"))
            if block.kind == "text" and any(len(t.split()) > rules["max_bullet_words"] for t in block.items):
                issues.append(_issue("long_bullet", "warning", slide, block,
                                     f"Тезис длиннее {rules['max_bullet_words']} слов"))
            if block.kind in {"table", "chart"}:
                dataset = next(d for d in plan.datasets if d.id == block.dataset_id)
                if block.kind == "table" and (len(dataset.rows) > rules["max_table_rows"] or len(dataset.columns) > rules["max_table_columns"]):
                    issues.append(_issue("table_density", "warning", slide, block,
                                         f"Таблица превышает ориентир {rules['max_table_rows']} строк или {rules['max_table_columns']} столбцов"))
                if block.kind == "chart" and len(dataset.columns)-1 > rules["max_chart_series"]:
                    issues.append(_issue("chart_density", "warning", slide, block,
                                         f"На графике более {rules['max_chart_series']} рядов данных"))
        for first_index, first in enumerate(slide.blocks):
            for second in slide.blocks[first_index+1:]:
                a, b = first.box, second.box
                overlap_w = min(a.left+a.width, b.left+b.width)-max(a.left, b.left)
                overlap_h = min(a.top+a.height, b.top+b.height)-max(a.top, b.top)
                if overlap_w > 0 and overlap_h > 0:
                    ratio = overlap_w*overlap_h/min(a.width*a.height, b.width*b.height)
                    if ratio > 0.02:
                        issues.append(_issue("overlap", "error", slide, first,
                                             f"Объект пересекается с {second.id}"))
    return AuditReport(
        issues=issues,
        checks=["outside_slide", "text_capacity", "palette", "placeholder", "empty_slide",
                "duplicate_slide", "repeated_layout", "layout_cycle", "overlap", "bullet_density", "table_density", "chart_density",
                "slide_bullet_density", "long_bullet", "template_font", "font_count", "type_scale",
                "protected_overlap", "contrast"],
        limitations=[
            "Вместимость текста оценена приближённо; окончательно проверяйте рендер.",
            "Контекстуальный анализ изображения выполняется отдельным модельным этапом.",
            "Контраст автоматически проверяется только для заданной сплошной заливки блока.",
        ],
    )


def audit_saved_pptx(
    output: Path, template: Path, plan: DeckPlan, profile: TemplateProfile,
) -> AuditReport:
    """Проверить сохранённые объекты, данные, стили и защищённые элементы."""
    from exposlides.design_saved_audit import audit_saved_pptx as audit_saved

    return audit_saved(output, template, plan, profile)


def apply_fixes(
    plan: DeckPlan, profile: TemplateProfile, report: AuditReport, issue_ids: list[str],
) -> DeckPlan:
    selected = set(issue_ids)
    known = {issue.id: issue for issue in report.issues}
    if not selected or selected-set(known):
        raise ValueError("Выберите существующие замечания текущей версии")
    if any(known[key].fix == "none" for key in selected):
        raise ValueError("Для выбранного замечания нет безопасного автоматического исправления")
    result = plan.model_copy(deep=True)
    patterns = {p.source_slide_index: p for p in profile.patterns}
    for issue_id in selected:
        issue = known[issue_id]
        slide = next(s for s in result.slides if s.id == issue.slide_id)
        block = next(b for b in slide.blocks if b.id == issue.block_id)
        pattern = patterns[slide.source_slide_index]
        if issue.fix == "move_inside":
            if block.source_shape_id is not None:
                raise ValueError(
                    "Исходную фигуру шаблона нельзя переместить автоматически. "
                    "Выберите другой макет."
                )
            block.box.width = min(block.box.width, result.width)
            block.box.height = min(block.box.height, result.height)
            block.box.left = max(0, min(block.box.left, result.width-block.box.width))
            block.box.top = max(0, min(block.box.top, result.height-block.box.height))
        elif issue.fix == "fit_text":
            original = block.style.size
            minimum = min(original, max(14, _reference_size(block, pattern) * 0.8))
            while capacity_risk(block) and block.style.size > minimum:
                block.style.size = max(minimum, block.style.size-1)
            if capacity_risk(block) and block.source_shape_id is None:
                # Расширяем только выбранный блок в свободную область под ним.
                # Соседние объекты и защищённые элементы остаются на своих местах.
                obstacles = [b.box for b in slide.blocks if b.id != block.id]
                obstacles.extend(pattern.protected_regions)
                bottom = result.height
                for other in obstacles:
                    horizontal = min(block.box.left+block.box.width, other.left+other.width)-max(
                        block.box.left, other.left,
                    )
                    if horizontal > 0 and other.top >= block.box.top+block.box.height:
                        bottom = min(bottom, other.top-int(EMU_PER_PT*4))
                required = math.ceil((text_lines(block)*block.style.size*1.25+12)*EMU_PER_PT)
                if required <= bottom-block.box.top:
                    block.box.height = max(block.box.height, required)
            if capacity_risk(block):
                raise ValueError(
                    "Текст не помещается при читаемом кегле. Сократите план или выберите другой макет."
                )
        elif issue.fix == "palette":
            # Используем исходный цвет body/title, если он определён темой.
            candidate = pattern.title_style.color if block.kind == "title" else pattern.body_style.color
            block.style.color = candidate if candidate in pattern.palette else pattern.palette[0]
    previous_errors = {i.id for i in report.issues if i.severity == "error"}
    updated = audit_deck(result, profile)
    if any(i.severity == "error" and i.id not in previous_errors for i in updated.issues):
        raise ValueError("Исправление создаёт новое критическое замечание; версия не изменена")
    return result
