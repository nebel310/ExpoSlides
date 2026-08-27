from pptx.util import Pt




def replace_placeholder_text(slide, placeholder_key, new_text):
    """Заменяет текст в плейсхолдере с указанным ключом"""
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        key = None
        if shape.is_placeholder:
            if shape.placeholder_format.idx is not None:
                key = str(shape.placeholder_format.idx)
            else:
                key = shape.name
        if key == placeholder_key:
            # сохраняем первый run и его стиль
            if shape.text_frame.paragraphs:
                first_para = shape.text_frame.paragraphs[0]
                if first_para.runs:
                    # используем первый run как образец стиля
                    first_run = first_para.runs[0]
                    # очищаем все параграфы и добавляем новый
                    shape.text_frame.clear()
                    p = shape.text_frame.paragraphs[0]
                    run = p.add_run()
                    run.text = new_text
                    # копируем стиль
                    run.font.name = first_run.font.name
                    run.font.size = first_run.font.size
                    run.font.bold = first_run.font.bold
                    run.font.italic = first_run.font.italic
                    run.font.underline = first_run.font.underline
                    if first_run.font.color and first_run.font.color.rgb:
                        run.font.color.rgb = first_run.font.color.rgb
                    return True
                else:
                    shape.text_frame.clear()
                    shape.text_frame.text = new_text
                    return True
            else:
                shape.text_frame.text = new_text
                return True
    return False