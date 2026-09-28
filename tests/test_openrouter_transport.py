from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import httpx
import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


@pytest.fixture
def chat_completions(service_importer):
    return service_importer(CONTENT_SERVICE_ROOT, "app.chains.chat_completions")


def completion(content='{"title":"Пример"}', finish_reason="stop"):
    return {"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]}


@pytest.fixture
def transport_clients(chat_completions, monkeypatch):
    sync_type = httpx.Client
    async_type = httpx.AsyncClient
    clients = []
    options = []

    def install(handler):
        transport = httpx.MockTransport(handler)

        def sync_client(**kwargs):
            options.append(kwargs)
            client = sync_type(transport=transport, **kwargs)
            clients.append(client)
            return client

        def async_client(**kwargs):
            options.append(kwargs)
            client = async_type(transport=transport, **kwargs)
            clients.append(client)
            return client

        monkeypatch.setattr(chat_completions.httpx, "Client", sync_client)
        monkeypatch.setattr(chat_completions.httpx, "AsyncClient", async_client)
        return clients, options

    return install


@pytest.mark.parametrize(
    "base_url", ["https://router.huggingface.co/v1", "https://router.huggingface.co/v1/"]
)
def test_sync_request_preserves_payload_and_closes_client(
    chat_completions, transport_clients, base_url
):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=completion())

    clients, options = transport_clients(respond)
    client = chat_completions.ChatCompletionsClient(base_url, "hf_test-key", 17)
    payload = {
        "model": "Qwen/Qwen3.8-27B:deepinfra",
        "messages": [{"role": "user", "content": "Исходный текст"}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "content", "strict": True, "schema": {"type": "object"}},
        },
        "max_tokens": 128,
    }

    result = client.chat(payload)

    assert isinstance(result, chat_completions.ChatCompletion)
    assert result.choices[0].message.content == '{"title":"Пример"}'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://router.huggingface.co/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer hf_test-key"
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.content) == payload
    assert request.extensions["timeout"] == dict.fromkeys(("connect", "read", "write", "pool"), 17)
    assert options[0]["verify"] is True
    assert clients[0].is_closed


def test_async_client_is_lazy_reused_closed_and_reopened(chat_completions, transport_clients):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=completion(None))

    clients, options = transport_clients(respond)
    client = chat_completions.ChatCompletionsClient("https://router.huggingface.co/v1", "hf_async-key", 11)

    async def run():
        assert clients == []
        await client.aclose()
        assert clients == []
        for _ in range(2):
            result = await client.achat({"model": "Qwen/Qwen3.8-27B:deepinfra"})
            assert result.choices[0].message.content is None
        assert len(clients) == 1
        assert not clients[0].is_closed
        await client.aclose()
        assert clients[0].is_closed
        await client.aclose()
        await client.achat({"model": "Qwen/Qwen3.8-27B:deepinfra"})
        assert len(clients) == 2
        await client.aclose()
        assert clients[1].is_closed

    asyncio.run(run())
    assert len(requests) == 3
    assert all(str(request.url).endswith("/v1/chat/completions") for request in requests)
    assert all(request.headers["Authorization"] == "Bearer hf_async-key" for request in requests)
    assert all(option["verify"] is True and option["timeout"] == 11 for option in options)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 502, 503, 504])
@pytest.mark.parametrize("async_mode", [False, True])
def test_http_failures_are_exposed_without_hidden_retry(
    chat_completions, transport_clients, status, async_mode
):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, text="private provider details")

    clients, _ = transport_clients(respond)
    client = chat_completions.ChatCompletionsClient("https://router.huggingface.co/v1", "hf_test-key", 1)

    async def request_async():
        try:
            await client.achat({})
        finally:
            await client.aclose()

    with pytest.raises(httpx.HTTPStatusError) as caught:
        if async_mode:
            asyncio.run(request_async())
        else:
            client.chat({})

    assert caught.value.response.status_code == status
    assert "private provider details" not in str(caught.value)
    assert len(requests) == 1
    assert all(client.is_closed for client in clients)


@pytest.mark.parametrize(
    "body",
    [
        b"not JSON",
        b"null",
        b"[]",
        b"{}",
        b'{"choices":[]}',
        b'{"choices":[{}]}',
        b'{"choices":[{"message":{}}]}',
        b'{"choices":[{"message":{"content":42}}]}',
        b'{"choices":[{"message":{"content":"private data"},"finish_reason":42}]}',
    ],
)
def test_invalid_response_has_sanitized_typed_error(chat_completions, transport_clients, body):
    clients, _ = transport_clients(lambda request: httpx.Response(200, content=body))
    client = chat_completions.ChatCompletionsClient("https://router.huggingface.co/v1", "hf_test-key", 1)

    with pytest.raises(chat_completions.ChatCompletionsResponseError) as caught:
        client.chat({})

    assert "private data" not in str(caught.value)
    assert str(caught.value).startswith("LLM provider returned")
    assert clients[0].is_closed


@pytest.mark.parametrize("finish_reason", ["length", "content_filter", "error"])
def test_incomplete_generation_rejects_even_valid_json(
    chat_completions, transport_clients, finish_reason
):
    transport_clients(
        lambda request: httpx.Response(200, json=completion(finish_reason=finish_reason))
    )
    client = chat_completions.ChatCompletionsClient("https://router.huggingface.co/v1", "hf_test-key", 1)

    with pytest.raises(chat_completions.ChatCompletionsResponseError, match="did not complete"):
        client.chat({})


@pytest.mark.parametrize(
    "code, expected",
    [(429, 429), ("503", 503), (401, 401), (200, 502), (None, 502), ("bad", 502), (True, 502)],
)
@pytest.mark.parametrize("nested", [False, True])
def test_embedded_error_uses_upstream_status_without_leaking_details(
    chat_completions, transport_clients, code, expected, nested
):
    error = {"code": code, "message": "private provider details"}
    envelope = completion() if nested else {}
    if nested:
        envelope["choices"][0]["error"] = error
    else:
        envelope["error"] = error
    transport_clients(lambda request: httpx.Response(200, json=envelope))
    client = chat_completions.ChatCompletionsClient("https://router.huggingface.co/v1", "hf_test-key", 1)

    with pytest.raises(httpx.HTTPStatusError) as caught:
        client.chat({})

    assert caught.value.response.status_code == expected
    assert str(caught.value) == f"LLM provider returned an upstream error (HTTP {expected})"
    assert "private provider details" not in str(caught.value)
    assert caught.value.response.content == b""


@pytest.mark.parametrize("async_mode", [False, True])
def test_network_failure_is_not_retried(chat_completions, transport_clients, async_mode):
    requests = []

    def respond(request):
        requests.append(request)
        raise httpx.ConnectError("Connection failed", request=request)

    clients, _ = transport_clients(respond)
    client = chat_completions.ChatCompletionsClient("https://router.huggingface.co/v1", "hf_test-key", 1)

    async def request_async():
        try:
            await client.achat({})
        finally:
            await client.aclose()

    with pytest.raises(httpx.ConnectError):
        if async_mode:
            asyncio.run(request_async())
        else:
            client.chat({})

    assert len(requests) == 1
    assert all(client.is_closed for client in clients)


def test_async_invalid_response_is_typed(chat_completions, transport_clients):
    transport_clients(lambda request: httpx.Response(200, json={"choices": []}))
    client = chat_completions.ChatCompletionsClient("https://router.huggingface.co/v1", "hf_test-key", 1)

    async def run():
        try:
            await client.achat({})
        finally:
            await client.aclose()

    with pytest.raises(
        chat_completions.ChatCompletionsResponseError, match="invalid response envelope"
    ):
        asyncio.run(run())


def test_previous_openrouter_imports_are_compatible_aliases(chat_completions):
    legacy = importlib.import_module("app.chains.openrouter")

    assert legacy.OpenRouterClient is chat_completions.ChatCompletionsClient
    assert legacy.OpenRouterResponseError is chat_completions.ChatCompletionsResponseError
    assert legacy.ChatCompletion is chat_completions.ChatCompletion
    assert legacy.ChatChoice is chat_completions.ChatChoice
    assert legacy.ChatMessage is chat_completions.ChatMessage


@pytest.mark.parametrize("api_key", ["sk-or-v1-private", "", "bad-key", "hf_"])
@pytest.mark.parametrize("async_mode", [False, True])
def test_huggingface_rejects_other_provider_credentials_before_http(
    chat_completions, transport_clients, api_key, async_mode
):
    clients, _ = transport_clients(lambda request: pytest.fail("Unexpected HTTP request"))
    client = chat_completions.ChatCompletionsClient(
        "https://router.huggingface.co/v1", api_key, 1
    )

    with pytest.raises(chat_completions.LLMCredentialsError) as caught:
        if async_mode:
            asyncio.run(client.achat({}))
        else:
            client.chat({})

    assert str(caught.value) == (
        "Для Hugging Face укажите LLM_API_KEY с токеном, начинающимся на hf_."
    )
    assert clients == []


@pytest.mark.parametrize("async_mode", [False, True])
def test_custom_provider_credentials_do_not_require_huggingface_prefix(
    chat_completions, transport_clients, async_mode
):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=completion())

    transport_clients(respond)
    client = chat_completions.ChatCompletionsClient(
        "https://openrouter.ai/api/v1", "sk-or-v1-dummy", 1
    )

    async def request_async():
        try:
            return await client.achat({})
        finally:
            await client.aclose()

    result = asyncio.run(request_async()) if async_mode else client.chat({})

    assert result.choices[0].message.content == '{"title":"Пример"}'
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer sk-or-v1-dummy"
