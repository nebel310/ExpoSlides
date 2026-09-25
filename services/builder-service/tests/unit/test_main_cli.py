from pathlib import Path

import pytest

from app.main import run as run_pipeline

from tests.helpers import build_content_dict, build_template_dict, make_pptx


def _write_json(path: Path, payload: dict) -> None:
    """Сохраняет dict в JSON-файл"""
    import json
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


async def test_run_cli_success(tmp_path):
    """CLI-сборка создаёт результат"""
    pptx_path = tmp_path / "template.pptx"
    make_pptx(pptx_path)
    template_dict = build_template_dict(pptx_path)
    content_dict = build_content_dict(template_dict)

    template_json = tmp_path / "template.json"
    content_json = tmp_path / "content.json"
    _write_json(template_json, template_dict)
    _write_json(content_json, content_dict)

    output = tmp_path / "out.pptx"
    result = await run_pipeline(pptx_path, template_json, content_json, output)
    assert result == output
    assert output.is_file()


async def test_run_cli_output_overlaps_input(tmp_path):
    """Выход не может совпадать с входом"""
    pptx_path = tmp_path / "template.pptx"
    make_pptx(pptx_path)
    template_dict = build_template_dict(pptx_path)
    content_dict = build_content_dict(template_dict)

    template_json = tmp_path / "template.json"
    content_json = tmp_path / "content.json"
    _write_json(template_json, template_dict)
    _write_json(content_json, content_dict)

    with pytest.raises(ValueError, match="отличаться"):
        await run_pipeline(pptx_path, template_json, content_json, template_json)


async def test_run_cli_missing_input(tmp_path):
    """Отсутствующий входной файл отклоняется"""
    with pytest.raises(FileNotFoundError):
        await run_pipeline(
            tmp_path / "missing.pptx",
            tmp_path / "missing.json",
            tmp_path / "missing2.json",
            tmp_path / "out.pptx",
        )


async def test_run_cli_wrong_suffix(tmp_path):
    """Неверное расширение отклоняется"""
    bad = tmp_path / "not_a_pptx.txt"
    bad.write_text("x")
    template_json = tmp_path / "t.json"
    template_json.write_text("{}")
    content_json = tmp_path / "c.json"
    content_json.write_text("{}")
    with pytest.raises(ValueError, match=".pptx"):
        await run_pipeline(bad, template_json, content_json, tmp_path / "out.pptx")