from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Ответ с ошибкой"""
    detail: str