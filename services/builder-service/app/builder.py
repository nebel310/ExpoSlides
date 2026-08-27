import asyncio
from pathlib import Path
from typing import Optional

from pptx import Presentation as PPTXPresentation

from app.models.presentation import Presentation
from app.models.content import GeneratedContent
from app.utils.clone import clone_slide
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

        # открываем исходный шаблон для чтения слайдов
        source_prs = await asyncio.to_thread(PPTXPresentation, str(template_pptx_path))
        # создаём целевую презентацию на основе шаблона
        target_prs = await asyncio.to_thread(PPTXPresentation, str(template_pptx_path))

        # удаляем все существующие слайды из target_prs
        xml_slides = target_prs.slides._sldIdLst
        for sldId in list(xml_slides):
            rId = sldId.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            target_prs.part.drop_rel(rId)
            xml_slides.remove(sldId)

        # получаем порядок слайдов из контента
        slide_indices = list(content_data.content.keys())

        for idx in slide_indices:
            # в текущей схеме idx соответствует индексу слайда в шаблоне (начиная с 1)
            slide_index = idx
            if slide_index < 1 or slide_index > len(source_prs.slides):
                # fallback на первый слайд
                slide_index = 1

            source_slide = source_prs.slides[slide_index - 1]
            new_slide = await asyncio.to_thread(clone_slide, source_prs, target_prs, source_slide)

            # замена текста в плейсхолдерах
            slide_content = content_data.content[idx]
            for placeholder_key, text in slide_content.placeholders.items():
                await asyncio.to_thread(replace_placeholder_text, new_slide, placeholder_key, text)

        # сохраняем результат
        await asyncio.to_thread(target_prs.save, str(output_path))
        return output_path