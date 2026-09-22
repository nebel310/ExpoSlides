from typing import Literal, Optional

from pydantic import BaseModel, Field


class GenerationSettings(BaseModel):
    """Настройки генерации"""

    language: str = Field(default="ru", min_length=2, max_length=16)
    tone: str = Field(default="professional", min_length=2, max_length=32)
    complexity: str = Field(default="medium", min_length=2, max_length=32)
    max_slides: Optional[int] = Field(default=None, ge=1)
    strict_user_mapping: bool = True
    generation_mode: Literal["standard", "fast"] = "standard"


class GenerationRequest(BaseModel):
    """Запрос на генерацию"""
    presentation: dict
    script: str
    user_mapping: Optional[dict] = None
    settings: GenerationSettings = Field(default_factory=GenerationSettings)
