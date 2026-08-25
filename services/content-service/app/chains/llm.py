from typing import Type, TypeVar
from pydantic import BaseModel
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from app.config import settings




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
        # GigaChat SDK пока не поддерживает async напрямую, но вызов выполняется в отдельном потоке
        import asyncio
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, self.client.chat, chat)
        content = response.choices[0].message.content
        import json
        data = json.loads(content)
        return model.model_validate(data)

llm_client = LLMClient()