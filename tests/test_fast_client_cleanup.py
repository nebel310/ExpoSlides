from __future__ import annotations

import asyncio
import importlib
import json
import logging
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


@pytest.mark.parametrize("graph_fails", [False, True])
def test_sdk_close_error_preserves_graph_outcome(
    monkeypatch, service_importer, tmp_path, caplog, graph_fails,
):
    main = service_importer(CONTENT_SERVICE_ROOT, "app.main")
    llm = importlib.import_module("app.chains.llm")
    models = importlib.import_module("app.models.graph_state")
    error = main.ContentValidationError("Ошибка проверки исходного текста")
    closes = []

    class Graph:
        async def ainvoke(self, state):
            if graph_fails:
                raise error
            return state.model_copy(update={
                "content": {1: models.GeneratedSlideContent(placeholders={"0": "Агенты"})},
                "validation": models.ValidationReport(ok=True),
            }).model_dump()

    class BrokenSDK:
        async def aclose(self):
            closes.append(True)
            raise RuntimeError("private close details")

    monkeypatch.setattr(main, "build_graph", Graph)
    client = llm.FastLLMClient()
    client._client = BrokenSDK()
    monkeypatch.setattr(main, "fast_llm_client", client)
    template = tmp_path / "template.json"
    template.write_text(json.dumps({"slides": [{"index": 1, "elements": []}]}), encoding="utf-8")
    script = tmp_path / "script.txt"
    script.write_text("Агенты используют инструменты для решения задач.", encoding="utf-8")
    output = tmp_path / "generated.json"

    with caplog.at_level(logging.WARNING):
        if graph_fails:
            with pytest.raises(main.ContentValidationError) as raised:
                asyncio.run(main.run(
                    template, script, output, main.GenerationSettings(generation_mode="fast"),
                ))
            assert raised.value is error
            assert not output.exists()
        else:
            asyncio.run(main.run(
                template, script, output, main.GenerationSettings(generation_mode="fast"),
            ))
            assert json.loads(output.read_text(encoding="utf-8"))["validation_report"]["ok"]
    assert closes == [True]
    assert client._client is None
    assert "private close details" not in caplog.text


def test_sdk_close_timeout_cancels_cleanup_and_discards_client(monkeypatch, service_importer):
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    monkeypatch.setattr(llm, "_FAST_CLIENT_CLOSE_TIMEOUT", 0.01, raising=False)
    cancelled = []
    client = llm.FastLLMClient()

    class SlowSDK:
        async def aclose(self):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

    client._client = SlowSDK()

    async def run():
        async with asyncio.timeout(0.2):
            await client.aclose()
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]

    asyncio.run(run())
    assert cancelled == [True]
    assert client._client is None


def test_caller_cancellation_propagates_during_cleanup_and_client_is_detached(service_importer):
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    client = llm.FastLLMClient()
    started = asyncio.Event()
    cancelled = []

    class SlowSDK:
        async def aclose(self):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

    client._client = SlowSDK()

    async def run():
        task = asyncio.create_task(client.aclose())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert cancelled == [True]
    assert client._client is None


def test_close_is_idempotent_and_next_request_gets_fresh_sdk(monkeypatch, service_importer):
    llm = service_importer(CONTENT_SERVICE_ROOT, "app.chains.llm")
    instances = []

    class SDK:
        def __init__(self, **kwargs):
            self.close_count = 0
            instances.append(self)

        async def aclose(self):
            self.close_count += 1

    monkeypatch.setattr(llm, "GigaChat", SDK)
    client = llm.FastLLMClient()
    first = client.client

    async def run():
        await client.aclose()
        await client.aclose()

    asyncio.run(run())
    assert first.close_count == 1
    assert client.client is not first
    assert len(instances) == 2
