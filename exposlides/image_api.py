"""Генерация через Hugging Face/fal с тем же токеном, что и у LLM."""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json

import httpx
from PIL import Image, UnidentifiedImageError
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

IMAGE_MODEL = "Tongyi-MAI/Z-Image-Turbo"
IMAGE_ENDPOINT = "https://router.huggingface.co/fal-ai/fal-ai/z-image/turbo"
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_RESPONSE_BYTES = 18 * 1024 * 1024


class ImageGenerationError(RuntimeError):
    """Безопасная для журнала ошибка без токена, промпта или ответа провайдера."""


class ImageSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "https://router.huggingface.co/v1"
    llm_fast_model: str = "Qwen/Qwen3.8-27B:deepinfra"
    image_generation_enabled: bool = True
    image_api_timeout: float = Field(default=60, gt=0, le=120)
    image_generation_timeout: float = Field(default=120, gt=0, le=240)
    image_concurrency: int = Field(default=2, ge=1, le=4)
    image_max_count: int = Field(default=20, ge=1, le=50)

    def token(self) -> str:
        token = self.llm_api_key.get_secret_value().strip()
        if self.llm_base_url.rstrip("/") != "https://router.huggingface.co/v1":
            raise ImageGenerationError(
                "Генерация изображений требует LLM_BASE_URL=https://router.huggingface.co/v1"
            )
        if not token.startswith("hf_"):
            raise ImageGenerationError(
                "Для изображений нужен существующий LLM_API_KEY Hugging Face "
                "с разрешением Inference Providers."
            )
        return token


async def describe_scene(client: httpx.AsyncClient, settings: ImageSettings, context: str) -> str:
    """Перевести тему в визуальный сюжет: не передавать текст слайда генератору."""
    from pathlib import Path

    instructions = (Path(__file__).parent / "prompts" / "image_scene.md").read_text(encoding="utf-8")
    try:
        async with asyncio.timeout(min(45, settings.image_api_timeout)):
            response = await client.post(
                settings.llm_base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {settings.token()}"},
                json={
                    "model": settings.llm_fast_model,
                    "messages": [
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": context},
                    ],
                    "temperature": 0.2, "max_tokens": 350, "reasoning_effort": "none",
                    "response_format": {"type": "json_schema", "json_schema": {
                        "name": "visual_scene", "strict": True, "schema": {
                            "type": "object", "properties": {"scene": {"type": "string"}},
                            "required": ["scene"], "additionalProperties": False,
                        },
                    }},
                },
            )
            if response.status_code != 200:
                raise ImageGenerationError(
                    f"Не удалось подготовить сюжет иллюстрации (HTTP {response.status_code})."
                )
            content = response.json()["choices"][0]["message"]["content"]
            scene = json.loads(content)["scene"]
            if not isinstance(scene, str) or not 20 <= len(scene.strip()) <= 1400:
                raise ValueError("invalid scene")
            return (
                scene.strip() + "\nSingle standalone illustration, full bleed. "
                "Absolutely no text, letters, numbers, labels, words, typography, "
                "palette swatches, logos, watermarks, slide mockups or infographics. "
                "Any screens and paper surfaces are blank."
            )
    except (TimeoutError, httpx.HTTPError) as error:
        raise ImageGenerationError("Не удалось получить сюжет иллюстрации от LLM.") from error
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise ImageGenerationError("LLM вернула некорректное описание иллюстрации.") from error


def decode_image(payload: dict) -> bytes:
    """Принимаем только inline-изображение: ключ не уходит на сторонний URL."""
    try:
        if any(payload.get("has_nsfw_concepts", [])):
            raise ImageGenerationError("Провайдер отклонил изображение по правилам контента.")
        url = payload["images"][0]["url"]
        header, encoded = url.split(",", 1)
        if header not in {"data:image/png;base64", "data:image/jpeg;base64"}:
            raise ValueError("unsupported image")
        if len(encoded) > MAX_IMAGE_BYTES * 4 // 3 + 4:
            raise ValueError("image too large")
        data = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"PNG", "JPEG"}:
                raise ValueError("unsupported format")
            if not (128 <= image.width <= 4096 and 128 <= image.height <= 4096):
                raise ValueError("invalid dimensions")
            image.verify()
        return data
    except (KeyError, IndexError, TypeError, ValueError, AttributeError, binascii.Error,
            OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ImageGenerationError("API изображений вернул некорректное изображение.") from error


async def generate_image(
    client: httpx.AsyncClient,
    settings: ImageSettings,
    *,
    prompt: str,
    width: int,
    height: int,
    seed: int,
) -> bytes:
    headers = {"Authorization": f"Bearer {settings.token()}"}
    payload = {
        "prompt": prompt,
        "image_size": {"width": width, "height": height},
        "num_inference_steps": 8,
        "num_images": 1,
        "seed": seed,
        "sync_mode": True,
        "output_format": "png",
        "enable_safety_checker": True,
        "enable_prompt_expansion": False,
    }
    try:
        async with asyncio.timeout(settings.image_api_timeout):
            for attempt in range(2):
                async with client.stream("POST", IMAGE_ENDPOINT, headers=headers, json=payload) as r:
                    if r.status_code == 429 and attempt == 0:
                        await asyncio.sleep(1)
                        continue
                    if r.status_code in {401, 403}:
                        raise ImageGenerationError(
                            "HF отклонил доступ к изображениям: проверьте права "
                            "Inference Providers у LLM_API_KEY."
                        )
                    if r.status_code == 402:
                        raise ImageGenerationError("Недостаточно средств Hugging Face для изображений.")
                    if r.status_code != 200:
                        raise ImageGenerationError(f"API изображений недоступен (HTTP {r.status_code}).")
                    body = bytearray()
                    async for chunk in r.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise ImageGenerationError("Ответ API изображений превышает лимит размера.")
                try:
                    result = json.loads(body)
                except (ValueError, UnicodeError) as error:
                    raise ImageGenerationError("API изображений вернул некорректный JSON.") from error
                return await asyncio.to_thread(decode_image, result)
    except (TimeoutError, httpx.TimeoutException) as error:
        raise ImageGenerationError("Истекло время ожидания API изображений.") from error
    except httpx.HTTPError as error:
        raise ImageGenerationError("Не удалось соединиться с API изображений.") from error
    raise ImageGenerationError("Исчерпаны попытки API изображений.")
