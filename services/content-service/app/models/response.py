from typing import Optional
from pydantic import BaseModel, Field




class SlideContent(BaseModel):
    """Сгенерированный контент для одного слайда"""
    placeholders: dict[str, str] = Field(default_factory=dict)
    notes: Optional[str] = None


class GenerationResponse(BaseModel):
    """Ответ content-service"""
    content: dict[int, SlideContent] = Field(default_factory=dict)
    validation_report: Optional[dict] = None
    error: Optional[str] = None