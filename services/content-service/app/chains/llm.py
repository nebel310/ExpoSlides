import asyncio
import json
import logging
import re
from typing import Any, Type, TypeVar

from app.config import settings
from app.errors import LLMGenerationError
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class _InvalidLLMResponse(ValueError):
    """A response was received but does not satisfy the requested structure."""


class LLMClient:
    """Клиент для структурированного вывода GigaChat"""

    def __init__(self):
        self.client = GigaChat(
            base_url=settings.llm_base_url,
            credentials=settings.llm_api_key,
            scope=settings.llm_scope,
            verify_ssl_certs=False,
            timeout=settings.llm_api_timeout,
        )

    async def generate_json(self, prompt: str, model: Type[T], strict: bool = True) -> T:
        """Генерация объекта модели из текста"""
        schema = model.model_json_schema()
        current_prompt = prompt
        for attempt in range(settings.llm_response_retries + 1):
            try:
                data = await self._request_json(current_prompt, schema, strict)
                return model.model_validate(data)
            except (_InvalidLLMResponse, ValidationError) as error:
                if attempt >= settings.llm_response_retries:
                    raise LLMGenerationError(
                        f"LLM response for {model.__name__} remained invalid after "
                        f"{attempt + 1} attempts: {error}"
                    ) from error
                logger.warning(
                    "Некорректный ответ LLM для %s, повтор %d/%d: %s",
                    model.__name__,
                    attempt + 1,
                    settings.llm_response_retries,
                    error,
                )
                current_prompt = self._build_correction_prompt(prompt, error)

        raise AssertionError("unreachable")

    async def generate_json_with_schema(
        self,
        prompt: str,
        schema: dict,
        strict: bool = True,
    ) -> dict:
        """Генерация JSON по произвольной схеме"""
        current_prompt = prompt
        for attempt in range(settings.llm_response_retries + 1):
            try:
                data = await self._request_json(current_prompt, schema, strict)
                self._validate_flat_object_schema(data, schema)
                return data
            except _InvalidLLMResponse as error:
                if attempt >= settings.llm_response_retries:
                    raise LLMGenerationError(
                        "LLM response remained invalid after "
                        f"{attempt + 1} attempts: {error}"
                    ) from error
                logger.warning(
                    "Некорректный JSON-ответ LLM, повтор %d/%d: %s",
                    attempt + 1,
                    settings.llm_response_retries,
                    error,
                )
                current_prompt = self._build_correction_prompt(prompt, error)

        raise AssertionError("unreachable")

    async def _request_json(self, prompt: str, schema: dict, strict: bool) -> dict:
        """Внутренний метод: отправка запроса и парсинг JSON"""
        if not settings.llm_api_key.strip():
            raise LLMGenerationError(
                "LLM_API_KEY не настроен. Укажите ключ GigaChat в окружении или .env"
            )

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
                raise _InvalidLLMResponse("empty response")
            data = self._parse_json_object(content)
            if not isinstance(data, dict):
                raise _InvalidLLMResponse("top-level JSON value must be an object")
            return data
        except _InvalidLLMResponse:
            raise
        except Exception as error:
            logger.error("Ошибка вызова LLM: %s", error)
            logger.debug("Детали ошибки вызова LLM", exc_info=True)
            raise LLMGenerationError(f"LLM request failed: {error}") from error

    @staticmethod
    def _build_correction_prompt(original_prompt: str, error: Exception) -> str:
        return (
            f"{original_prompt}\n\n"
            "Предыдущий ответ отклонён валидатором. "
            f"Причина: {error}. "
            "Верни только корректный JSON, полностью соответствующий заданной JSON Schema."
        )

    @staticmethod
    def _parse_json_object(content: str) -> Any:
        """Parse JSON and recover common formatting noise without changing values."""
        normalized = content.strip()
        if normalized.startswith("```"):
            lines = normalized.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            normalized = "\n".join(lines).strip()

        try:
            return json.loads(normalized)
        except json.JSONDecodeError:
            repaired_prefixes = LLMClient._strip_non_json_line_prefixes(normalized)
            without_trailing_commas = re.sub(
                r",\s*([}\]])",
                r"\1",
                repaired_prefixes,
            )
            try:
                return json.loads(without_trailing_commas)
            except json.JSONDecodeError as repaired_error:
                raise _InvalidLLMResponse(f"invalid JSON: {repaired_error}") from repaired_error

    @staticmethod
    def _strip_non_json_line_prefixes(content: str) -> str:
        """Remove model noise inserted before otherwise intact JSON line tokens."""
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end < start:
            return content

        json_region = content[start : end + 1]
        structural_starts = set('{[}]"-0123456789')
        repaired_lines = []
        for line in json_region.splitlines():
            stripped = line.lstrip()
            if (
                not stripped
                or stripped[0] in structural_starts
                or stripped.startswith(("true", "false", "null"))
            ):
                repaired_lines.append(stripped)
                continue

            token_positions = [
                stripped.find(token)
                for token in ('"', "{", "[", "}", "]")
                if stripped.find(token) >= 0
            ]
            if token_positions:
                stripped = stripped[min(token_positions) :]
            repaired_lines.append(stripped)
        return "\n".join(repaired_lines)

    @staticmethod
    def _validate_flat_object_schema(data: dict[str, Any], schema: dict[str, Any]) -> None:
        if schema.get("type") != "object":
            return

        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        missing = required - data.keys()
        if missing:
            raise _InvalidLLMResponse(f"missing required properties: {sorted(missing)}")

        if schema.get("additionalProperties") is False:
            unexpected = data.keys() - properties.keys()
            if unexpected:
                raise _InvalidLLMResponse(f"unexpected properties: {sorted(unexpected)}")

        for key, value in data.items():
            property_schema = properties.get(key, {})
            if property_schema.get("type") == "string" and not isinstance(value, str):
                raise _InvalidLLMResponse(f"property {key!r} must be a string")
            max_length = property_schema.get("maxLength")
            if max_length is not None and isinstance(value, str) and len(value) > max_length:
                raise _InvalidLLMResponse(
                    f"property {key!r} exceeds maxLength {max_length}"
                )
            allowed_values = property_schema.get("enum")
            if allowed_values is not None and value not in allowed_values:
                raise _InvalidLLMResponse(
                    f"property {key!r} must be one of {allowed_values}"
                )

llm_client = LLMClient()
