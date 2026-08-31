import asyncio
import json
import logging
from typing import Optional, Type, TypeVar

from app.config import settings
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

class LLMClient:
    """Клиент для структурированного вывода GigaChat"""

    def __init__(self):
        self.client = GigaChat(
            base_url=settings.llm_base_url,
            credentials=settings.llm_api_key,
            scope=settings.llm_scope,
            verify_ssl_certs=False,
        )

    async def generate_json(self, prompt: str, model: Type[T], strict: bool = True) -> T:
        """Генерация объекта модели из текста"""
        schema = model.model_json_schema()
        data = await self._generate_json_with_schema(prompt, schema, strict)
        if data is None:
            return model()
        try:
            return model.model_validate(data)
        except Exception as e:
            logger.error("Ошибка валидации ответа LLM в %s: %s", model.__name__, e)
            return model()

    async def generate_json_with_schema(self, prompt: str, schema: dict, strict: bool = True) -> Optional[dict]:
        """Генерация JSON по произвольной схеме"""
        return await self._generate_json_with_schema(prompt, schema, strict)

    async def _generate_json_with_schema(self, prompt: str, schema: dict, strict: bool) -> Optional[dict]:
        """Внутренний метод: отправка запроса и парсинг JSON"""
        logger.debug("Отправка запроса в LLM. Модель: %s, strict: %s", settings.llm_model, strict)
        logger.debug("Промпт:\n%s", prompt)
        logger.debug("Схема:\n%s", json.dumps(schema, ensure_ascii=False, indent=2))

        chat = Chat(
            model=settings.llm_model,
            messages=[Messages(role=MessagesRole.USER, content=prompt)],
            response_format={
                "type": "json_schema",
                "schema": schema,
                "strict": strict,
            },
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )

        loop = asyncio.get_running_loop()
        try:
            response = await loop.run_in_executor(None, self.client.chat, chat)
            content = response.choices[0].message.content
            logger.debug("Ответ LLM (сырой):\n%s", content)
            if not content:
                logger.warning("Пустой ответ от LLM")
                return None
            try:
                data = json.loads(content)
                return data
            except json.JSONDecodeError as e:
                logger.error("Ошибка парсинга JSON: %s", e)
                return None
        except Exception:
            logger.exception("Ошибка вызова LLM")
            return None

llm_client = LLMClient()
