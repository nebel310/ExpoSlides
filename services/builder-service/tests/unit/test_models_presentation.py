import pytest
from app.models.presentation import (
    BBox,
    DesignTokens,
    LayoutInfo,
    Paragraph,
    Presentation,
    Run,
    Slide,
    SlideElement,
    TableElement,
    TextElement,
    TextStyle,
    ThemeInfo,
)
from pydantic import ValidationError


def _bbox() -> dict:
    return {"left": 0, "top": 0, "width": 100, "height": 50}


def _run(text: str = "hello") -> dict:
    return {"text": text, "style": {}}


def test_bbox_required_fields():
    """BBox требует все координаты"""
    obj = BBox(**_bbox())
    assert obj.width == 100
    with pytest.raises(ValidationError):
        BBox(left=0, top=0)


def test_text_style_defaults():
    """TextStyle заполняется булевыми значениями по умолчанию"""
    obj = TextStyle()
    assert obj.bold is False
    assert obj.italic is False
    assert obj.underline is False


def test_run_requires_style():
    """Run требует текст и стиль"""
    obj = Run(text="hi", style=TextStyle())
    assert obj.text == "hi"
    with pytest.raises(ValidationError):
        Run(text="hi")


def test_paragraph_restores_text_from_runs():
    """Paragraph восстанавливает text из runs, если поле не задано"""
    para = Paragraph(runs=[Run(text="a", style=TextStyle()), Run(text="b", style=TextStyle())])
    assert para.text == "ab"


def test_paragraph_keeps_explicit_text():
    """Явно заданный text не перезаписывается"""
    para = Paragraph(text="x", runs=[Run(text="a", style=TextStyle())])
    assert para.text == "x"


def test_text_element_restores_full_text():
    """TextElement собирает full_text из параграфов"""
    element = TextElement(paragraphs=[
        Paragraph(runs=[Run(text="a", style=TextStyle())]),
        Paragraph(runs=[Run(text="b", style=TextStyle())]),
    ])
    assert element.full_text == "a\nb"


def test_text_element_keeps_explicit_full_text():
    """Явный full_text не перезаписывается"""
    element = TextElement(
        paragraphs=[Paragraph(runs=[Run(text="a", style=TextStyle())])],
        full_text="custom",
    )
    assert element.full_text == "custom"


def test_slide_element_restore_placeholder_type_from_kind():
    """placeholder_type восстанавливается из placeholder_kind"""
    element = SlideElement(
        id="x", type="text", bbox=BBox(**_bbox()),
        placeholder_kind="title",
    )
    assert element.placeholder_type == "TITLE"


def test_slide_element_rejects_unknown_kind():
    """Неизвестный placeholder_kind отклоняется"""
    with pytest.raises(ValidationError):
        SlideElement(
            id="x", type="text", bbox=BBox(**_bbox()),
            placeholder_kind="unknown_kind",
        )


def test_table_element_read_v2_cells():
    """TableElement принимает v2-ячейки-объекты"""
    table = TableElement(
        rows=1, cols=2,
        cells=[[{"text": "A"}, {"text": "B", "row_span": 1, "col_span": 1}]],
    )
    assert table.cells == [["A", "B"]]


def test_table_element_read_v1_cells():
    """TableElement принимает v1-строки"""
    table = TableElement(rows=1, cols=2, cells=[["A", "B"]])
    assert table.cells == [["A", "B"]]


def test_slide_defaults():
    """Slide создаётся с пустыми элементами"""
    obj = Slide(index=1)
    assert obj.elements == []
    assert obj.layout_type == "unknown"


def test_presentation_requires_sizes():
    """Presentation требует ширину и высоту слайда"""
    with pytest.raises(ValidationError):
        Presentation()
    obj = Presentation(slide_width=100, slide_height=100)
    assert obj.file_type == "pptx"


def test_presentation_schema_version_validation():
    """Недопустимая schema_version отклоняется"""
    with pytest.raises(ValidationError):
        Presentation(slide_width=1, slide_height=1, schema_version="3.0.0")


def test_presentation_restores_theme_from_tokens():
    """theme восстанавливается из tokens.theme"""
    obj = Presentation(
        slide_width=1, slide_height=1,
        tokens=DesignTokens(theme=ThemeInfo(colors={"a": "b"})),
    )
    assert obj.theme is not None
    assert obj.theme.colors == {"a": "b"}


def test_presentation_keeps_explicit_theme():
    """Явный theme не перезаписывается"""
    obj = Presentation(
        slide_width=1, slide_height=1,
        theme=ThemeInfo(fonts={"major": "X"}),
        tokens=DesignTokens(theme=ThemeInfo(colors={"a": "b"})),
    )
    assert obj.theme.fonts == {"major": "X"}


def test_layout_info_required_fields():
    """LayoutInfo требует name и index"""
    with pytest.raises(ValidationError):
        LayoutInfo(name="x")
    obj = LayoutInfo(name="x", index=1)
    assert obj.elements == []