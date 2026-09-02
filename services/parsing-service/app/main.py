from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from uuid import uuid4

from app.parsers.pptx_parser import PPTXParser

logger = logging.getLogger(__name__)

SERVICE_ROOT = Path(__file__).resolve().parent.parent


async def run(input_pptx: str | Path, output_json: str | Path) -> Path:
    """Разобрать PPTX и атомарно записать его JSON-представление."""
    input_path = Path(input_pptx).expanduser().resolve()
    output_path = Path(output_json).expanduser().resolve()

    if not input_path.is_file():
        raise FileNotFoundError(f"PPTX-шаблон не найден: {input_path}")
    if input_path.suffix.casefold() != ".pptx":
        raise ValueError(f"Ожидался файл .pptx: {input_path}")
    if output_path.suffix.casefold() != ".json":
        raise ValueError(f"Ожидался выходной файл .json: {output_path}")

    presentation = await PPTXParser.parse(input_path)
    payload = presentation.model_dump_json(indent=2)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
    try:
        await asyncio.to_thread(temporary_path.write_text, payload, encoding="utf-8")
        await asyncio.to_thread(temporary_path.replace, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    logger.info("JSON сохранён: %s", output_path)
    return output_path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Разобрать PPTX-шаблон в Presentation JSON")
    parser.add_argument(
        "--input-pptx",
        type=Path,
        default=SERVICE_ROOT / "test.pptx",
        help="Путь к исходному PPTX",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=SERVICE_ROOT / "output.json",
        help="Путь для Presentation JSON",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    args = _parse_args(argv)
    try:
        asyncio.run(run(args.input_pptx, args.output_json))
    except Exception as error:
        logger.error("Parsing-service завершился с ошибкой: %s", error)
        logger.debug("Детали ошибки parsing-service", exc_info=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
