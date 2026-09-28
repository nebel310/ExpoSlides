from typing import Any

from pydantic import BaseModel


class WSEvent(BaseModel):
    """Событие WebSocket"""
    event: str
    task_id: str
    payload: dict[str, Any]