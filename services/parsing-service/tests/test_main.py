from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import main as main_module


@pytest.mark.asyncio
async def test_run_cli_writes_json(tmp_path: Path):
    """CLI-режим парсит pptx и пишет валидный JSON-файл"""
    from io import BytesIO

    from pptx import Presentation as PPTXPresentation

    prs = PPTXPresentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Hi"
    pptx_path = tmp_path / "in.pptx"
    prs.save(pptx_path)

    output_path = tmp_path / "out.json"
    result = await main_module.run_cli(pptx_path, output_path)

    assert result == output_path
    assert output_path.is_file()
    assert "slides" in output_path.read_text(encoding="utf-8")


def test_main_with_partial_cli_args_returns_2():
    """main с одним CLI-аргументом возвращает код 2"""
    code = main_module.main(["--input-pptx", "x.pptx"])
    assert code == 2


def test_main_cli_failure_returns_1(tmp_path: Path):
    """main с несуществующим pptx возвращает код 1"""
    code = main_module.main(
        [
            "--input-pptx",
            str(tmp_path / "missing.pptx"),
            "--output-json",
            str(tmp_path / "out.json"),
        ]
    )
    assert code == 1