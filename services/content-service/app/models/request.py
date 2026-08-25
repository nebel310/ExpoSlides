from typing import Optional
from pydantic import BaseModel, Field




class GenerationSettings(BaseModel):
    """Настройки генерации контента"""
    language: str = "ru"
    tone: str = "professional"
    complexity: str = "medium"
    max_slides: Optional[int] = None
    strict_user_mapping: bool = True


class GenerationRequest(BaseModel):
    """Запрос на генерацию контента"""
    presentation: dict = Field(..., description="JSON от parsing-service")
    script: str = Field(..., description="Текст доклада")
    user_mapping: Optional[dict] = Field(
        default=None,
        description="Пользовательская разметка: slide_index -> placeholder_name -> текст"
    )
    settings: GenerationSettings = Field(default_factory=GenerationSettings)