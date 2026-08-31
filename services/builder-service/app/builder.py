import asyncio
from pathlib import Path

from pptx import Presentation as PPTXPresentation

from app.models.presentation import Presentation
from app.models.content import GeneratedContent
from app.utils.text import replace_placeholder_text




class PPTXBuilder:
    """Сборка итоговой презентации из шаблона и контента"""

    @classmethod
    async def build(
        cls,
        template_pptx_path: str | Path,
        template_data: Presentation,
        content_data: GeneratedContent,
        output_path: str | Path,
    ) -> Path:
        """Создаёт result.pptx на основе шаблона и контента"""
        template_pptx_path = Path(template_pptx_path)
        output_path = Path(output_path)

        prs = await asyncio.to_thread(PPTXPresentation, str(template_pptx_path))

        # индексы слайдов, которые нужно оставить (порядок важен)
        slide_indices_to_keep = list(content_data.content.keys())

        # собираем список всех слайдов с их исходными индексами
        slides_with_indices = []
        for i, slide in enumerate(prs.slides):
            original_index = i + 1
            if original_index in slide_indices_to_keep:
                slides_with_indices.append((slide, original_index))

        # удаляем все слайды, которые не нужно оставить
        xml_slides = prs.slides._sldIdLst
        # собираем sldId для удаления (те, чей индекс не в списке keep)
        sldId_list = list(xml_slides)
        to_remove = []
        for i, sldId in enumerate(sldId_list):
            original_index = i + 1
            if original_index not in slide_indices_to_keep:
                to_remove.append(sldId)

        for sldId in to_remove:
            rId = sldId.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            prs.part.drop_rel(rId)
            xml_slides.remove(sldId)

        # теперь заменяем текст в оставшихся слайдах
        for slide, original_index in slides_with_indices:
            slide_content = content_data.content[original_index]
            for placeholder_key, text in slide_content.placeholders.items():
                await asyncio.to_thread(replace_placeholder_text, slide, placeholder_key, text)

        await asyncio.to_thread(prs.save, str(output_path))
        return output_path