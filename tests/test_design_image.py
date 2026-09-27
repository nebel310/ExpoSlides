from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


def _load(service_importer, monkeypatch):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_image")
    monkeypatch.setattr(module.settings, "image_api_url", "https://images.example.test/generate")
    monkeypatch.setattr(module.settings, "image_api_key", "test-key")
    return module


def _png():
    buffer = io.BytesIO()
    Image.new("RGB", (32, 16), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_optional_image_saves_verified_bytes_and_provenance(
    service_importer, monkeypatch, tmp_path,
):
    module = _load(service_importer, monkeypatch)
    calls = []
    image = _png()

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=image, headers={"content-type": "image/png"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await module.generate_image(module.ImageRequest(
                enabled=True, prompt="Облачная инфраструктура", seed=7,
                palette=["0077FF"], source_ids=["source-1"],
            ), tmp_path / "illustration.json", client)

    result = asyncio.run(run())
    assert result.status == "completed"
    assert Path(result.path).read_bytes() == image
    assert result.model == "black-forest-labs/FLUX.1-schnell"
    assert result.license == "Apache-2.0"
    assert result.seed == 7 and result.source_ids == ["source-1"]
    assert (result.width, result.height) == (32, 16)
    payload = json.loads(calls[0].content)
    assert payload["parameters"]["num_inference_steps"] == 4
    assert payload["parameters"]["seed"] == 7
    assert "0077FF" in payload["inputs"]
    assert "test-key" not in result.model_dump_json()


def test_disabled_image_generation_makes_no_request(service_importer, monkeypatch, tmp_path):
    module = _load(service_importer, monkeypatch)

    def handler(request):
        pytest.fail("Disabled adapter must not make a request")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await module.generate_image(module.ImageRequest(), tmp_path / "image.json", client)

    assert asyncio.run(run()).status == "not_run"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("body", [b"not an image", b'{"error":"private provider error"}'])
def test_invalid_provider_response_is_not_saved(
    service_importer, monkeypatch, tmp_path, body,
):
    module = _load(service_importer, monkeypatch)

    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body))
        async with httpx.AsyncClient(transport=transport) as client:
            return await module.generate_image(
                module.ImageRequest(enabled=True, prompt="Иллюстрация"),
                tmp_path / "image.json", client,
            )

    result = asyncio.run(run())
    assert result.status == "failed"
    assert "private" not in result.model_dump_json()
    assert not list(tmp_path.iterdir())


def test_unapproved_model_is_rejected_without_provider_call(
    service_importer, monkeypatch, tmp_path,
):
    module = _load(service_importer, monkeypatch)
    monkeypatch.setattr(module.settings, "image_model", "black-forest-labs/FLUX.1-dev")

    def handler(request):
        pytest.fail("Unapproved model must not reach the provider")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await module.generate_image(
                module.ImageRequest(enabled=True, prompt="Иллюстрация"),
                tmp_path / "image.json", client,
            )

    assert asyncio.run(run()).status == "failed"


def test_endpoint_cannot_be_controlled_by_request(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_image")
    with pytest.raises(ValueError):
        module.ImageRequest(enabled=True, prompt="Иллюстрация", url="https://untrusted.test")


def test_remote_plain_http_endpoint_is_rejected(service_importer, monkeypatch, tmp_path):
    module = _load(service_importer, monkeypatch)
    monkeypatch.setattr(module.settings, "image_api_url", "http://images.example.test/generate")
    result = asyncio.run(module.generate_image(
        module.ImageRequest(enabled=True, prompt="Иллюстрация"), tmp_path / "image.json",
    ))
    assert result.status == "failed"


def test_auth_failure_is_not_retried_or_exposed(service_importer, monkeypatch, tmp_path):
    module = _load(service_importer, monkeypatch)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, text="private API key failure")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await module.generate_image(
                module.ImageRequest(enabled=True, prompt="Иллюстрация"),
                tmp_path / "image.json", client,
            )

    result = asyncio.run(run())
    assert result.status == "failed"
    assert len(calls) == 1
    assert "private" not in result.model_dump_json()


def test_oversized_response_is_not_saved(service_importer, monkeypatch, tmp_path):
    module = _load(service_importer, monkeypatch)
    monkeypatch.setattr(module, "MAX_IMAGE_BYTES", 10)

    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=_png()))
        async with httpx.AsyncClient(transport=transport) as client:
            return await module.generate_image(
                module.ImageRequest(enabled=True, prompt="Иллюстрация"),
                tmp_path / "image.json", client,
            )

    assert asyncio.run(run()).status == "failed"
    assert not list(tmp_path.iterdir())


def test_request_timeout_is_bounded(service_importer, monkeypatch, tmp_path):
    module = _load(service_importer, monkeypatch)
    monkeypatch.setattr(module.settings, "image_api_timeout", 0.02)

    async def handler(request):
        await asyncio.sleep(10)
        return httpx.Response(200, content=_png())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await module.generate_image(
                module.ImageRequest(enabled=True, prompt="Иллюстрация"),
                tmp_path / "image.json", client,
            )

    assert asyncio.run(run()).status == "failed"
    assert not list(tmp_path.iterdir())


def test_corrupt_png_checksum_returns_failed_without_partial_file(
    service_importer, monkeypatch, tmp_path,
):
    module = _load(service_importer, monkeypatch)
    body = bytearray(_png())
    chunk = body.index(b"IDAT")
    length = int.from_bytes(body[chunk-4:chunk], "big")
    body[chunk+4+length] ^= 1

    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=bytes(body)))
        async with httpx.AsyncClient(transport=transport) as client:
            return await module.generate_image(
                module.ImageRequest(enabled=True, prompt="Иллюстрация"),
                tmp_path / "image.json", client,
            )

    assert asyncio.run(run()).status == "failed"
    assert not list(tmp_path.iterdir())
