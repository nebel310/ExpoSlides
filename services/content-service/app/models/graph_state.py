from typing import Optional

from app.models.presentation import PresentationData
from app.models.request import GenerationSettings
from pydantic import BaseModel, Field


class ScriptBlock(BaseModel):
    """Последовательный смысловой блок исходного текста."""

    index: int = Field(default=1, ge=1)
    heading: str = ""
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)


class ScriptAnalysis(BaseModel):
    """Структурированное, основанное на источнике представление скрипта."""

    topic: str = ""
    audience: str = ""
    objective: str = ""
    blocks: list[ScriptBlock] = Field(default_factory=list)
    key_messages: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)


class SlidePlanItem(BaseModel):
    """План слайда"""

    template_slide_index: Optional[int] = None
    layout_type: Optional[str] = None
    title: str = ""
    content: str = ""
    purpose: str = ""
    key_message: str = ""
    source_block_indices: list[int] = Field(default_factory=list)


class SlidePlan(BaseModel):
    """План презентации"""
    slides: list[SlidePlanItem] = Field(default_factory=list)


class GeneratedSlideContent(BaseModel):
    """Сгенерированный контент слайда"""
    placeholders: dict[str, str] = Field(default_factory=dict)


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
