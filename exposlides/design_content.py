"""Материалы и проверенный план истории, общий для всех вариантов верстки."""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from pathlib import Path

from exposlides.design_models import ContentPlan, Dataset, DesignRequest, SourceExcerpt, StorySlide


def source_excerpts(script: str) -> list[SourceExcerpt]:
    excerpts = []
    # Граница предложения не разрывает десятичные значения и сокращения единиц.
    pattern = r"[^\n]+(?:\n(?!\s*\n)[^\n]+)*"
    for index, match in enumerate(re.finditer(pattern, script), 1):
        value = match.group().strip()
        if value:
            excerpts.append(SourceExcerpt(
                id=f"source-{index}", text=value, start=match.start(), end=match.end(),
            ))
    return excerpts


def extractive_plan(request: DesignRequest, excerpts: list[SourceExcerpt]) -> ContentPlan:
    """Явный локальный режим: только извлечение исходного текста, без имитации LLM."""
    sections = []
    for excerpt in excerpts:
        sentences = re.split(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z])|\n", excerpt.text)
        sections.append([(s.strip(), excerpt.id) for s in sentences if s.strip()])
    pieces = [piece for section in sections for piece in section]
    count = min(request.slide_count, len(pieces))
    if count < request.slide_count and request.count_mode == "exact":
        raise ValueError(
            f"В локальном режиме найдено {len(pieces)} смысловых фрагментов для "
            f"{request.slide_count} слайдов. Добавьте материалы или уменьшите число слайдов."
        )
    chunks = []
    if count >= len(sections):
        allocations = [1]*len(sections)
        for _ in range(count-len(sections)):
            candidates = [i for i, section in enumerate(sections) if allocations[i] < len(section)]
            selected = max(candidates, key=lambda i: sum(len(p[0]) for p in sections[i])/allocations[i])
            allocations[selected] += 1
        for section, allocated in zip(sections, allocations, strict=True):
            chunks.extend(section[i*len(section)//allocated:(i+1)*len(section)//allocated]
                          for i in range(allocated))
    else:
        for i in range(count):
            group = sections[i*len(sections)//count:(i+1)*len(sections)//count]
            chunks.append([piece for section in group for piece in section])
    slides = []
    for index, chunk in enumerate(chunks):
        first = chunk[0][0]
        title = first if len(first) <= 120 else first[:117].rsplit(" ", 1)[0]+"…"
        body = chunk[1:] if len(chunk) > 1 and len(first) <= 120 else chunk
        slides.append(StorySlide(
            id=f"slide-{index+1}", title=title,
            paragraphs=[p[0] for p in body], source_ids=list(dict.fromkeys(p[1] for p in chunk)),
        ))
    return ContentPlan(title=slides[0].title, slides=slides)


def _semantic_module():
    name = "exposlides_shared_fact_grounding"
    if name not in sys.modules:
        path = Path(__file__).resolve().parents[1] / (
            "services/content-service/app/utils/fact_grounding.py"
        )
        if not path.is_file():
            raise RuntimeError("Модуль проверки фактов не установлен")
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            raise
    return sys.modules[name]


def dataset_source(dataset: Dataset) -> str:
    facts = [f"{dataset.name}. Источник: {dataset.source}."]
    for row in dataset.rows:
        for column, value in zip(dataset.columns[1:], row[1:], strict=True):
            facts.append(f"{column} ({row[0]}): {value} {dataset.unit}.")
    return "\n".join(facts)


def validate_story(
    plan: ContentPlan, request: DesignRequest, excerpts: list[SourceExcerpt],
) -> list[str]:
    """Проверить источники, количество, полноту и смысл до передачи в верстку."""
    issues = []
    count = len(plan.slides)
    if count > request.slide_count or (request.count_mode == "exact" and count != request.slide_count):
        issues.append(f"Ожидалось {request.slide_count} слайдов, получено {count}")
    by_id = {e.id: e.text for e in excerpts}
    used = {key for slide in plan.slides for key in slide.source_ids}
    missing = set(by_id)-used
    unknown = used-set(by_id)
    if missing:
        issues.append("Потеряны разделы источника: "+", ".join(sorted(missing)))
    if unknown:
        issues.append("Неизвестные ссылки на источник: "+", ".join(sorted(unknown)))
    semantic = _semantic_module()
    datasets = {d.id: d for d in request.datasets}
    for slide in plan.slides:
        text = "\n".join([slide.title, *slide.paragraphs])
        if slide.visual and slide.visual.labels:
            text += "\n"+"\n".join(slide.visual.labels)
        source = "\n".join(by_id[s] for s in slide.source_ids if s in by_id)
        if slide.visual and slide.visual.dataset_id in datasets:
            source += "\n" + dataset_source(datasets[slide.visual.dataset_id])
        if source:
            issues.extend(f"{slide.id}: {i}" for i in semantic.semantic_content_issues(source, text))
            if slide.notes:
                issues.extend(f"{slide.id} (заметки): {i}"
                              for i in semantic.semantic_content_issues(source, slide.notes))
        if slide.visual and slide.visual.dataset_id and slide.visual.dataset_id not in datasets:
            issues.append(f"{slide.id}: неизвестный набор данных")
    whole = "\n".join("\n".join([s.title, *s.paragraphs, *(s.visual.labels if s.visual else [])])
                      for s in plan.slides)
    referenced_datasets = {s.visual.dataset_id for s in plan.slides if s.visual and s.visual.dataset_id}
    source_with_data = request.script + "\n" + "\n".join(
        dataset_source(datasets[key]) for key in referenced_datasets if key in datasets
    )
    for excerpt in excerpts:
        if not excerpt.required:
            continue
        attributed = "\n".join(
            "\n".join([s.title, *s.paragraphs])
            for s in plan.slides if excerpt.id in s.source_ids
        )
        if semantic.missing_required_messages(attributed, [excerpt.text]):
            issues.append(f"Содержание раздела {excerpt.id} раскрыто не полностью")
    number_pattern = re.compile(r"(?<!\w)[−+-]?\d+(?:[.,]\d+)?\s*%?")
    def numbers(value: str) -> set[str]:
        return {
            m.group().strip().replace(" ", "").replace(",", ".").replace("−", "-")
            for m in number_pattern.finditer(value)
        }
    source_numbers, output_numbers = numbers(request.script), numbers(whole)
    if source_numbers - output_numbers:
        issues.append("Потеряны числовые значения: "+", ".join(sorted(source_numbers-output_numbers)))
    notes = "\n".join(s.notes for s in plan.slides)
    unsupported = (output_numbers | numbers(notes))-numbers(source_with_data)
    if unsupported:
        issues.append("Неподтверждённые числа: "+", ".join(sorted(unsupported)))
    issues.extend(semantic.semantic_content_issues(
        source_with_data, whole, required_messages=request.required_messages,
    ))
    return list(dict.fromkeys(issues))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
