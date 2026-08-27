# services/builder-service/app/main.py
import asyncio
import json
import logging
from pathlib import Path

from app.builder import PPTXBuilder
from app.models.presentation import Presentation
from app.models.content import GeneratedContent




logger = logging.getLogger(__name__)


async def main() -> None:
    """Запуск builder-service"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    base_path = Path(__file__).resolve().parent.parent
    template_pptx = base_path / "template.pptx"
    template_json = base_path / "template.json"
    content_json = base_path / "generated_content.json"
    output_pptx = base_path / "result.pptx"

    logger.info("Чтение входных данных")
    template_data = Presentation.model_validate_json(template_json.read_text(encoding="utf-8"))
    content_data = GeneratedContent.model_validate_json(content_json.read_text(encoding="utf-8"))

    logger.info("Сборка презентации")
    result_path = await PPTXBuilder.build(
        template_pptx_path=template_pptx,
        template_data=template_data,
        content_data=content_data,
        output_path=output_pptx,
    )

    logger.info("Результат сохранён: %s", result_path)


if __name__ == "__main__":
    asyncio.run(main())