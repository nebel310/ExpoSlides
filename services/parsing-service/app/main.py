import asyncio
from pathlib import Path

from app.parsers.pptx_parser import PPTXParser




async def main() -> None:
    """Точка входа для локального тестирования парсера"""
    parser = PPTXParser
    pptx_path = Path(__file__).resolve().parent.parent / "test.pptx"

    presentation = await parser.parse(pptx_path)
    output = presentation.model_dump_json(indent=2)

    await asyncio.to_thread(
        Path("output.json").write_text,
        output,
        encoding="utf-8",
    )
    print("JSON сохранён в output.json")


if __name__ == "__main__":
    asyncio.run(main())