from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from app.builder import PPTXBuilder
from app.models.content import GeneratedContent
from app.models.presentation import Presentation

logger = logging.getLogger(__name__)

SERVICE_ROOT = Path(__file__).resolve().parent.parent


async def run(
    template_pptx: str | Path,
    template_json: str | Path,
    content_json: str | Path,
    output_pptx: str | Path,
) -> Path:
    """Собрать презентацию из файлов межсервисного контракта."""
    template_pptx_path = Path(template_pptx).expanduser().resolve()
    template_json_path = Path(template_json).expanduser().resolve()
    content_json_path = Path(content_json).expanduser().resolve()
    output_pptx_path = Path(output_pptx).expanduser().resolve()

    input_paths = (template_pptx_path, template_json_path, content_json_path)
    if output_pptx_path in input_paths:
        raise ValueError("Путь результата должен отличаться от путей входных файлов")

    for input_path in input_paths:
        if not input_path.is_file():
            raise FileNotFoundError(f"Входной файл не найден: {input_path}")
    if template_pptx_path.suffix.casefold() != ".pptx":
        raise ValueError(f"Ожидался PPTX-шаблон: {template_pptx_path}")
    if template_json_path.suffix.casefold() != ".json":
        raise ValueError(f"Ожидался Presentation JSON: {template_json_path}")
    if content_json_path.suffix.casefold() != ".json":
        raise ValueError(f"Ожидался Generated Content JSON: {content_json_path}")
    if output_pptx_path.suffix.casefold() != ".pptx":
        raise ValueError(f"Ожидался выходной файл .pptx: {output_pptx_path}")

    logger.info("Чтение входных данных")
    template_data = Presentation.model_validate_json(
        template_json_path.read_text(encoding="utf-8")
    )
    content_data = GeneratedContent.model_validate_json(
        content_json_path.read_text(encoding="utf-8")
    )

    logger.info("Сборка презентации")
    result_path = await PPTXBuilder.build(
        template_pptx_path=template_pptx_path,
        template_data=template_data,
        content_data=content_data,
        output_path=output_pptx_path,
    )

    logger.info("Результат сохранён: %s", result_path)
    return result_path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Собрать итоговый PPTX")
    parser.add_argument("--template-pptx", type=Path, default=SERVICE_ROOT / "template.pptx")
    parser.add_argument("--template-json", type=Path, default=SERVICE_ROOT / "template.json")
    parser.add_argument(
        "--content-json",
        type=Path,
        default=SERVICE_ROOT / "generated_content.json",
    )
    parser.add_argument("--output-pptx", type=Path, default=SERVICE_ROOT / "result.pptx")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    args = _parse_args(argv)
    try:
        asyncio.run(
            run(
                args.template_pptx,
                args.template_json,
                args.content_json,
                args.output_pptx,
            )
        )
    except Exception as error:
        logger.error("Builder-service завершился с ошибкой: %s", error)
        logger.debug("Детали ошибки builder-service", exc_info=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
