"""Ограниченная параллельная генерация разных иллюстраций для слайдов."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.design_image import ImageRequest, ImageResult, generate_image
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SlideImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slide_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    request: ImageRequest


class BatchImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    images: list[SlideImageRequest] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_slides(self):
        if len({item.slide_id for item in self.images}) != len(self.images):
            raise ValueError("Повторный идентификатор слайда")
        if any(not item.request.enabled for item in self.images):
            raise ValueError("Запрос набора должен включать только выбранные иллюстрации")
        return self


async def generate_images(request: BatchImageRequest, output: Path,
                          *, timeout: float = 90) -> dict:
    semaphore = asyncio.Semaphore(3)
    results: dict[str, dict] = {}

    async def one(item: SlideImageRequest):
        async with semaphore:
            destination = output.parent / "images" / item.slide_id / "result.json"
            result = await generate_image(item.request, destination)
            if result.status != "completed":
                raise ValueError("Не удалось создать все иллюстрации")
            results[item.slide_id] = result.model_dump(mode="json")

    tasks = []
    try:
        async with asyncio.timeout(timeout):
            tasks = [asyncio.create_task(one(item)) for item in request.images]
            await asyncio.gather(*tasks)
        # Не выдаём одну и ту же картинку за разные результаты, даже при сбое API.
        hashes = [result["sha256"] for result in results.values()]
        if len(set(hashes)) != len(hashes):
            raise ValueError("Генератор вернул повторяющиеся изображения")
        return {"status": "completed", "images": {
            item.slide_id: results[item.slide_id] for item in request.images
        }}
    except (ValueError, OSError, TimeoutError):
        return {"status": "failed", "images": {}, "error": "image_batch_failed"}
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    try:
        if not 0 < args.timeout <= 90:
            raise ValueError("Некорректный бюджет иллюстраций")
        request = BatchImageRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
        result = asyncio.run(generate_images(request, args.output, timeout=args.timeout))
        # Проверяем каждый результат перед файловой передачей другому процессу.
        for image in result["images"].values():
            ImageResult.model_validate(image)
    except (ValueError, OSError):
        result = {"status": "failed", "images": {}, "error": "invalid_image_batch"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(result["status"] != "completed")


if __name__ == "__main__":
    raise SystemExit(main())
