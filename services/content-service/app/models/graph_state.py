from typing import Optional

from app.models.presentation import PresentationData
from app.models.request import GenerationSettings
from pydantic import BaseModel, Field, PositiveInt


class ScriptBlock(BaseModel):
    """Последовательный смысловой блок исходного текста."""

    index: PositiveInt
    heading: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    key_points: list[str] = Field(min_length=1)
    facts: list[str]


class ScriptAnalysis(BaseModel):
    """Структурированное, основанное на источнике представление скрипта."""

    topic: str = Field(min_length=1)
    audience: str
    objective: str
    blocks: list[ScriptBlock] = Field(min_length=1)
    key_messages: list[str] = Field(min_length=1)
    facts: list[str]


class SlidePlanItem(BaseModel):
    """План слайда"""

    template_slide_index: PositiveInt
    layout_type: Optional[str] = None
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    key_message: str = Field(min_length=1)
    source_block_indices: list[PositiveInt] = Field(min_length=1)


class SlidePlan(BaseModel):
    """План презентации"""
    slides: list[SlidePlanItem] = Field(min_length=1)


class GeneratedSlideContent(BaseModel):
    """Сгенерированный контент слайда"""
    placeholders: dict[str, str] = Field(min_length=1)


class ValidationReport(BaseModel):
    """Отчёт валидации"""
    ok: bool = False
    issues: list[str] = Field(default_factory=list)


class ContentGraphState(BaseModel):
    """Состояние графа"""
    presentation: PresentationData
    script: str
    user_mapping: Optional[dict] = None
    settings: GenerationSettings = Field(default_factory=GenerationSettings)
    analysis: Optional[ScriptAnalysis] = None
    plan: Optional[SlidePlan] = None
    content: Optional[dict[int, GeneratedSlideContent]] = None
    validation: Optional[ValidationReport] = None
    retries: int = 0
