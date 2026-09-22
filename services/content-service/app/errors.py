import ssl

import httpx
from gigachat.exceptions import AuthenticationError, ForbiddenError, RateLimitError, ServerError
from pydantic import ValidationError

# Файловые сервисы изолированы; эти коды также принимает exposlides.cli.
CONTENT_ERROR_EXIT_CODES = {
    "invalid_response": 20,
    "content_validation": 21,
    "timeout": 22,
    "auth": 23,
    "network": 24,
}


class GenerationPipelineError(RuntimeError):
    """Base error for a generation run that must not produce a successful result."""


class LLMGenerationError(GenerationPipelineError):
    """The LLM request or its structured response could not be recovered."""


class AnalysisValidationError(GenerationPipelineError):
    """The source analysis is incomplete or contains unsupported facts."""


class PlanValidationError(GenerationPipelineError):
    """The generated slide plan violates template or grounding constraints."""


class ContentValidationError(GenerationPipelineError):
    """Generated slide content remains invalid after all retries."""


class UserMappingValidationError(GenerationPipelineError):
    """User-provided slide or placeholder mapping violates the file contract."""


def content_error_code(error: BaseException, *, credentials_configured: bool = True) -> str:
    """Классифицировать причину без чтения текста ошибки, ответа или HTTP-заголовков."""
    chain: list[BaseException] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__

    if any(isinstance(item, (TimeoutError, httpx.TimeoutException)) for item in chain):
        return "timeout"
    if any(isinstance(item, (AuthenticationError, ForbiddenError)) for item in chain):
        return "auth"
    if not credentials_configured and any(isinstance(item, LLMGenerationError) for item in chain):
        return "auth"
    if any(
        isinstance(item, (httpx.TransportError, ConnectionError, ssl.SSLError, RateLimitError,
                          ServerError))
        for item in chain
    ):
        return "network"
    if any(
        isinstance(item, ValidationError) or getattr(item, "invalid_response", False) is True
        for item in chain
    ):
        return "invalid_response"
    if any(
        isinstance(item, (AnalysisValidationError, PlanValidationError, ContentValidationError,
                          UserMappingValidationError))
        for item in chain
    ):
        return "content_validation"
    return "unknown"
