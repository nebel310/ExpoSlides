from abc import ABC, abstractmethod
from pathlib import Path

from app.models.presentation import Presentation




class BaseParser(ABC):
    """Базовый класс для парсеров файлов"""

    @classmethod
    @abstractmethod
    async def parse(cls, file_path: str | Path) -> Presentation:
        """Асинхронно извлекает структуру презентации из файла"""
        raise NotImplementedError