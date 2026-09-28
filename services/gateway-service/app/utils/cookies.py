import uuid
from typing import Optional

from app.config import settings
from fastapi import Request, Response


def get_sid_from_request(request: Request) -> Optional[str]:
    """Читает sid из cookie запроса"""
    return request.cookies.get(settings.cookie_name)


def set_sid_cookie(response: Response, sid: str) -> None:
    """Устанавливает cookie sid"""
    response.set_cookie(
        key=settings.cookie_name,
        value=sid,
        max_age=settings.cookie_max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def new_sid() -> str:
    """Генерирует новый sid"""
    return str(uuid.uuid4())
