from typing import Optional
from pydantic import BaseModel, Field




class PlaceholderData(BaseModel):
    """Данные placeholder'а слайда"""
    idx: Optional[int] = None
    name: Optional[str] = None
    placeholder_type: Optional[str] = None
    text: str = ""
    max_length: Optional[int] = None


class SlideData(BaseModel):
    """Данные слайда, необходимые для генерации"""
    index: int
    layout_type: Optional[str] = None
    layout_name: Optional[str] = None
    placeholders: list[PlaceholderData] = Field(default_factory=list)
    notes: Optional[str] = None


class LayoutPlaceholderData(BaseModel):
    """Placeholder в макете"""
    placeholder_type: Optional[str] = None
    name: Optional[str] = None
    idx: Optional[int] = None


class LayoutData(BaseModel):
    """Макет слайда"""
    name: str
    index: int
    placeholders: list[LayoutPlaceholderData] = Field(default_factory=list)


class PresentationData(BaseModel):
    """Упрощённая структура презентации для content-service"""
    slide_width: int = 0
    slide_height: int = 0
    slides: list[SlideData] = Field(default_factory=list)
    layouts: list[LayoutData] = Field(default_factory=list)
    theme: dict = Field(default_factory=dict)