import asyncio
import json
import logging
from typing import Type, TypeVar
from pydantic import BaseModel
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from app.config import settings

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
        logger.debug("Отправка запроса в LLM. Модель: %s, strict: %s", settings.llm_model, strict)
        logger.debug("Промпт:\n%s", prompt)

        chat = Chat(
            model=settings.llm_model,
            messages=[Messages(role=MessagesRole.USER, content=prompt)],
            response_format={
                "type": "json_schema",
                "schema": model.model_json_schema(),
                "strict": strict,
            },
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )

        loop = asyncio.get_event_loop()
        try:
            response = await loop.run_in_executor(None, self.client.chat, chat)
            content = response.choices[0].message.content
            logger.debug("Ответ LLM (сырой):\n%s", content)
            try:
                data = json.loads(content)
                result = model.model_validate(data)
                logger.debug("Ответ успешно распарсен в %s: %s", model.__name__, result.model_dump())
                return result
            except Exception as e:
                logger.error("Ошибка парсинга ответа LLM: %s", e)
                logger.debug("Контент ответа: %s", content)
                return model()
        except Exception as e:
            logger.error("Ошибка вызова LLM: %s", e)
            return model()

llm_client = LLMClient()