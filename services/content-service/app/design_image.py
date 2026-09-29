"""Иллюстрация Z-Image-Turbo через HF/fal с существующим ключом LLM."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from app.chains.hf_images import (
    IMAGE_ENDPOINT,
    ImageGenerationError,
    ImageSettings,
    describe_scene,
)
from app.chains.hf_images import (
    generate_image as generate_hf_image,
)
from app.config import settings
from app.design_config import model_for_role, role_config, role_metadata, role_prompt
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_IMAGE_BYTES = 16 * 1024 * 1024


class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    prompt: str = Field(default="", max_length=4000)
    seed: int = Field(default=0, ge=0, le=2**32 - 1)
    width: int = Field(default=1024, ge=256, le=2048, multiple_of=16)
    height: int = Field(default=576, ge=256, le=2048, multiple_of=16)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    palette: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("palette")
    @classmethod
    def color_codes(cls, values: list[str]) -> list[str]:
        for value in values:
            if len(value) != 6 or any(char not in "0123456789abcdefABCDEF" for char in value):
                raise ValueError("Палитра должна содержать шестизначные HEX-цвета")
        return values

    @model_validator(mode="after")
    def topic_required(self):
        if self.enabled and not self.prompt.strip():
            raise ValueError("Для иллюстрации требуется описание темы")
        return self


class ImageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["not_run", "completed", "failed"]
    path: str | None = None
    model: str | None = None
    license: str | None = None
    seed: int | None = None
    sha256: str | None = None
    width: int | None = None
    height: int | None = None
    source_ids: list[str] = Field(default_factory=list)
    workflow_version: str | None = None
    metadata: dict = Field(default_factory=dict)
    error: str | None = None


def _endpoint() -> str:
    url = settings.image_api_url.strip()
    parsed = urlsplit(url)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if not parsed.hostname or parsed.username or parsed.password or (
        parsed.scheme != "https" and not (parsed.scheme == "http" and local)
    ):
        raise ValueError("IMAGE_API_URL должен быть HTTPS endpoint или локальным HTTP endpoint")
    return url


def _image_info(data: bytes) -> tuple[str, int, int]:
    with Image.open(io.BytesIO(data)) as image:
        if image.format not in {"PNG", "JPEG"}:
            raise ValueError("Endpoint вернул неподдерживаемый формат изображения")
        if not (0 < image.width <= 4096 and 0 < image.height <= 4096):
            raise ValueError("Endpoint вернул недопустимые размеры изображения")
        info = ("png" if image.format == "PNG" else "jpg", image.width, image.height)
        image.verify()
    return info


async def generate_image(
    request: ImageRequest, output: Path, client: httpx.AsyncClient | None = None,
) -> ImageResult:
    if not request.enabled:
        return ImageResult(status="not_run")
    owned_client = client is None
    try:
        model = model_for_role("image_illustrator", settings.image_model)
        config = role_config("image_illustrator")
        endpoint = _endpoint()
        if endpoint != IMAGE_ENDPOINT and not settings.image_api_key.strip():
            raise ValueError("Не настроен IMAGE_API_KEY")
        prompt = role_prompt("image_illustrator").replace("{payload}", json.dumps({
            "topic": request.prompt, "palette": request.palette,
            "source_ids": request.source_ids,
        }, ensure_ascii=False))
        payload = {
            "inputs": prompt,
            "parameters": {
                "width": request.width, "height": request.height, "seed": request.seed,
                "num_inference_steps": config["inference_steps"],
                "guidance_scale": config["guidance_scale"],
            },
        }
        timeout = min(settings.image_api_timeout, config["timeout_seconds"])
        if client is None:
            client = httpx.AsyncClient(timeout=timeout, verify=True, follow_redirects=False)
        if endpoint == IMAGE_ENDPOINT:
            hf_settings = ImageSettings(
                _env_file=None,
                llm_api_key=settings.image_api_key or settings.llm_api_key,
                llm_base_url=settings.llm_base_url,
                llm_fast_model=settings.llm_fast_model,
                image_api_timeout=timeout,
            )
            prompt = await describe_scene(client, hf_settings, prompt)
            raw = await generate_hf_image(
                client, hf_settings, prompt=prompt, width=request.width,
                height=request.height, seed=request.seed,
            )
        else:
            async with asyncio.timeout(timeout):
                async with client.stream(
                    "POST", endpoint, json=payload,
                    headers={"Authorization": f"Bearer {settings.image_api_key}"},
                ) as response:
                    response.raise_for_status()
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_IMAGE_BYTES:
                            raise ValueError("Слишком большой ответ генератора изображений")
            raw = bytes(data)
        extension, width, height = await asyncio.to_thread(_image_info, raw)
        output.parent.mkdir(parents=True, exist_ok=True)
        image_path = output.with_name(f"{output.stem}.{uuid4().hex}.image.{extension}")
        await asyncio.to_thread(image_path.write_bytes, raw)
        metadata = role_metadata("image_illustrator", settings.image_model)
        return ImageResult(
            status="completed", path=str(image_path.resolve()), model=model["id"],
            license=model["license"], seed=request.seed, sha256=hashlib.sha256(raw).hexdigest(),
            width=width, height=height, source_ids=request.source_ids,
            workflow_version=metadata["workflow_version"], metadata=metadata,
        )
    except (
        ValueError, OSError, SyntaxError, httpx.HTTPError, TimeoutError, Image.DecompressionBombError,
        ImageGenerationError,
    ):
        # Ответ провайдера, URL, токен и текст промпта не попадают в публичную ошибку.
        return ImageResult(status="failed", error="image_generation_failed")
    finally:
        if owned_client and client is not None:
            try:
                async with asyncio.timeout(5):
                    await client.aclose()
            except Exception:
                # Закрытие транспорта не отменяет уже проверенный результат.
                pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        request = ImageRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
        result = asyncio.run(generate_image(request, args.output))
    except (ValueError, OSError):
        result = ImageResult(status="failed", error="invalid_image_request")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return 1 if result.status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
