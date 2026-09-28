"""Export boundary: canonical paths and untrusted source text in standalone HTML."""

from PIL import Image

from exposlides.design_export import export_deck
from exposlides.design_models import Box, DeckPlan, PlacedBlock, SlideInstance, TextStyle


def test_export_handles_symlinked_output_and_escapes_text(tmp_path, monkeypatch):
    target = tmp_path/"real"
    target.mkdir()
    alias = tmp_path/"alias"
    alias.symlink_to(target, target_is_directory=True)
    pptx = alias/"presentation.pptx"
    pptx.write_bytes(b"fake-renderer-input")
    plan = DeckPlan(variant_id="story", name="<script>name</script>", description="Example",
                    width=1000000, height=800000, slides=[SlideInstance(
                        id="s1", story_slide_id="s1", source_slide_index=1,
                        blocks=[PlacedBlock(id="text", kind="text", text="<script>alert(1)</script>",
                            box=Box(left=0, top=0, width=1000000, height=800000), style=TextStyle())],
                    )])

    class Renderer:
        available = True

        def render(self, source, directory, count, *, pdf_output):
            directory = directory.resolve()
            directory.mkdir()
            image = directory/"slide-1.png"
            Image.new("RGB", (10, 8), "white").save(image)
            pdf_output.write_bytes(b"%PDF-fake")
            return [image]

    monkeypatch.setattr("exposlides.design_export.shutil.which", lambda command: None)
    result = export_deck(pptx, plan, alias, Renderer())
    assert result["images"] == ["slides/slide-1.png"]
    assert result["html_visual"] == "png"
    document = (target/"presentation.html").read_text(encoding="utf-8")
    assert "<script>" not in document
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in document
    assert "Content-Security-Policy" in document
