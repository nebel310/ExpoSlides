"""Совместимые имена прежнего транспорта OpenRouter."""

from app.chains.chat_completions import (
    ChatChoice,
    ChatCompletion,
    ChatCompletionsClient,
    ChatCompletionsResponseError,
    ChatMessage,
)

OpenRouterClient = ChatCompletionsClient
OpenRouterResponseError = ChatCompletionsResponseError

__all__ = [
    "ChatChoice",
    "ChatCompletion",
    "ChatMessage",
    "OpenRouterClient",
    "OpenRouterResponseError",
]
