from typing import Optional
from pydantic import BaseModel, Field




class GenerationSettings(BaseModel):
    """Настройки генерации"""
    language: str = "ru"
    tone: str = "professional"
    complexity: str = "medium"
    max_slides: Optional[int] = None
    strict_user_mapping: bool = True


class GenerationRequest(BaseModel):
    """Запрос на генерацию"""
    presentation: dict
    script: str
    user_mapping: Optional[dict] = None
    settings: GenerationSettings = Field(default_factory=GenerationSettings)