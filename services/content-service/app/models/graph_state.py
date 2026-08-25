from typing import Optional
from pydantic import BaseModel, Field
from app.models.presentation import PresentationData
from app.models.request import GenerationSettings




class ScriptAnalysis(BaseModel):
    """Результат анализа скрипта"""
    blocks: list[dict] = Field(default_factory=list)
    key_messages: list[str] = Field(default_factory=list)


class SlidePlan(BaseModel):
    """План слайдов"""
    slides: list[dict] = Field(default_factory=list)


class ValidationReport(BaseModel):
    """Отчёт о валидации"""
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
    content: Optional[dict] = None
    validation: Optional[ValidationReport] = None
    retries: int = 0