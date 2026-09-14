from pydantic import BaseModel, Field


class ContentGenerationRequest(BaseModel):
    """Запрос на генерацию контента из слоя оркестрации в домен"""

    structure: dict
    script: str = Field(min_length=1)
    feedback: str | None = None


class ContentGenerationResult(BaseModel):
    """Результат генерации контента из домена в слой оркестрации"""

    content: dict[int, dict]
    passed: bool
    reason: str | None = None