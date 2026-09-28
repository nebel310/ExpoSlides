"""HTTP-транспорт Chat Completions API без скрытых повторных запросов."""

from typing import Any
from urllib.parse import urlsplit

import httpx
from app.errors import LLMCredentialsError
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ChatCompletionsResponseError(ValueError):
    """Ответ получен, но не содержит завершённого сообщения модели."""


class ChatMessage(BaseModel):
    model_config = ConfigDict(strict=True)

    content: str | None


class ChatChoice(BaseModel):
    model_config = ConfigDict(strict=True)

    message: ChatMessage
    finish_reason: str | None = None


class ChatCompletion(BaseModel):
    model_config = ConfigDict(strict=True)

    choices: list[ChatChoice] = Field(min_length=1)


def _raise_embedded_error(error: Any, response: httpx.Response) -> None:
    """Сохраняет HTTP-код провайдера, не раскрывая текст ошибки или ответа."""
    status = 502
    code = error.get("code") if isinstance(error, dict) else None
    if isinstance(code, str) and len(code) == 3 and code.isascii() and code.isdigit():
        code = int(code)
    if isinstance(code, int) and not isinstance(code, bool) and 400 <= code <= 599:
        status = code
    upstream_response = httpx.Response(
        status_code=status,
        headers=response.headers,
        request=response.request,
    )
    raise httpx.HTTPStatusError(
        f"LLM provider returned an upstream error (HTTP {status})",
        request=response.request,
        response=upstream_response,
    )


def _parse_response(response: httpx.Response) -> ChatCompletion:
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError as error:
        raise ChatCompletionsResponseError("LLM provider returned malformed JSON") from error

    if isinstance(data, dict):
        if data.get("error") is not None:
            _raise_embedded_error(data["error"], response)
        choices = data.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if isinstance(choice, dict) and choice.get("error") is not None:
                    _raise_embedded_error(choice["error"], response)

    try:
        completion = ChatCompletion.model_validate(data)
    except ValidationError as error:
        raise ChatCompletionsResponseError(
            "LLM provider returned an invalid response envelope"
        ) from error
    for choice in completion.choices:
        if choice.finish_reason in {"length", "content_filter", "error"}:
            raise ChatCompletionsResponseError(
                f"LLM generation did not complete ({choice.finish_reason})"
            )
    return completion


class ChatCompletionsClient:
    """Синхронные и асинхронные запросы к совместимому Chat Completions API."""

    def __init__(self, base_url: str, api_key: str, timeout: float):
        self._base_url = base_url.rstrip("/") + "/"
        self._api_key = api_key
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout
        self._async_client: httpx.AsyncClient | None = None

    def chat(self, payload: dict) -> ChatCompletion:
        self._validate_credentials()
        with httpx.Client(
            base_url=self._base_url,
            headers=self._headers,
            timeout=self._timeout,
            verify=True,
        ) as client:
            response = client.post("chat/completions", json=payload)
        return _parse_response(response)

    async def achat(self, payload: dict) -> ChatCompletion:
        self._validate_credentials()
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers,
                timeout=self._timeout,
                verify=True,
            )
        response = await self._async_client.post("chat/completions", json=payload)
        return _parse_response(response)

    def _validate_credentials(self) -> None:
        if urlsplit(self._base_url).hostname == "router.huggingface.co" and not (
            self._api_key.startswith("hf_") and len(self._api_key) > 3
        ):
            raise LLMCredentialsError(
                "Для Hugging Face укажите LLM_API_KEY с токеном, начинающимся на hf_."
            )

    async def aclose(self) -> None:
        client = self._async_client
        self._async_client = None
        if client is not None:
            await client.aclose()
