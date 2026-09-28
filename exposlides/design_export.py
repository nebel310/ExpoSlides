"""Автономный HTML и PDF из той же версии готового PPTX."""

from __future__ import annotations

import base64
import html
import os
import shutil
from pathlib import Path

from exposlides.design_models import DeckPlan
from exposlides.preview import PreviewRenderer


def export_deck(
    pptx: Path, plan: DeckPlan, directory: Path, renderer: PreviewRenderer,
) -> dict:
    pptx, directory = pptx.resolve(), directory.resolve()
    if not renderer.available:
        raise RuntimeError("Для PDF, HTML и визуального аудита установите LibreOffice и Poppler")
    pdf = directory / "presentation.pdf"
    images = renderer.render(pptx, directory / "slides", len(plan.slides), pdf_output=pdf)
    cairo = shutil.which("pdftocairo")
    sections = []
    vector = bool(cairo)
    for index, (image, slide) in enumerate(zip(images, plan.slides, strict=True), 1):
        picture = image
        mime = "image/png"
        if cairo:
            picture = directory / "slides" / f"slide-{index}.svg"
            renderer._run([
                cairo, "-svg", "-f", str(index), "-l", str(index), str(pdf), str(picture),
            ], os.environ.copy())
            if not picture.is_file():
                raise RuntimeError("Не удалось создать векторный HTML-экспорт")
            mime = "image/svg+xml"
        encoded = base64.b64encode(picture.read_bytes()).decode("ascii")
        text = "\n".join(
            "\n".join([b.text, *b.items]) for b in slide.blocks if b.kind != "page_number"
        )
        data_tables = []
        for block in slide.blocks:
            if block.dataset_id:
                dataset = next(d for d in plan.datasets if d.id == block.dataset_id)
                header = "".join(f"<th>{html.escape(c)}</th>" for c in dataset.columns)
                rows = "".join("<tr>"+"".join(
                    f"<td>{html.escape(str(v))}</td>" for v in row
                )+"</tr>" for row in dataset.rows)
                data_tables.append(f"<table><thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table>")
        sections.append(
            f'<section id="slide-{index}" aria-label="Слайд {index}">'
            f'<img alt="Слайд {index}" src="data:{mime};base64,{encoded}">'
            f'<details><summary>Текст и данные слайда {index}</summary>'
            f'<pre>{html.escape(text)}</pre>{"".join(data_tables)}</details></section>'
        )
    document = (
        '<!doctype html><html lang="ru"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        'img-src data:; style-src \'unsafe-inline\'">'
        f'<title>{html.escape(plan.name)}</title>'
        '<style>body{margin:0;background:#17191d;color:#eee;font:16px system-ui}'
        'main{max-width:1200px;margin:auto;padding:24px}section{margin-bottom:32px}'
        'img{width:100%;height:auto}details{padding:12px}pre{white-space:pre-wrap}'
        'table{border-collapse:collapse}td,th{border:1px solid #777;padding:8px}'
        '@media print{body{background:white}section{break-after:page}details{display:none}}'
        '</style><main>' + "".join(sections) + '</main></html>'
    )
    (directory / "presentation.html").write_text(document, encoding="utf-8")
    return {
        "images": [str(p.relative_to(directory)) for p in images],
        "html_visual": "svg" if vector else "png",
        "files": {"pptx": pptx.name, "pdf": pdf.name, "html": "presentation.html"},
    }
