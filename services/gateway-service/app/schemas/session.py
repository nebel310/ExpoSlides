from pydantic import BaseModel


class SessionBootstrapResponse(BaseModel):
    """Ответ bootstrap сессии"""
    sid: str