from typing import Optional

from pydantic import BaseModel, Field


class SlideContentResponse(BaseModel):
    """Контент слайда для ответа"""
    placeholders: dict[str, str] = Field(default_factory=dict)
    notes: Optional[str] = None


class GenerationResponse(BaseModel):
    """Ответ сервиса"""
    content: dict[int, SlideContentResponse] = Field(default_factory=dict)
    validation_report: Optional[dict] = None
    error: Optional[str] = None