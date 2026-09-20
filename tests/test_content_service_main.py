from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTENT_SERVICE_ROOT = REPOSITORY_ROOT / "services" / "content-service"


def _write_template(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "slide_width": 12_192_000,
                "slide_height": 6_858_000,
                "slides": [
                    {
                        "index": 1,
                        "layout_type": "title",
                        "layout_name": "Title",
                        "elements": [
                            {
                                "type": "text",
                                "placeholder_type": "TITLE",
                                "placeholder_idx": 0,
                                "placeholder_name": "Title 1",
                                "text": {"full_text": "Исходный заголовок презентации"},
                            }
                        ],
                    }
                ],
                "layouts": [],
                "theme": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_content_run_writes_only_validated_result(
    tmp_path: Path,
    monkeypatch,
    service_importer,
) -> None:
    main = service_importer(CONTENT_SERVICE_ROOT, "app.main")
    graph_state = importlib.import_module("app.models.graph_state")
    template = tmp_path / "template.json"
    script = tmp_path / "script.txt"
    output = tmp_path / "generated.json"
    _write_template(template)
    script.write_text("Команда готовит запуск продукта", encoding="utf-8")

    class FakeGraph:
        async def ainvoke(self, state):
            return state.model_copy(
                update={
                    "content": {
                        1: graph_state.GeneratedSlideContent(
                            placeholders={"0": "Команда готовит запуск продукта"}
                        )
                    },
                    "validation": graph_state.ValidationReport(ok=True, issues=[]),
                }
            ).model_dump()

    monkeypatch.setattr(main, "build_graph", FakeGraph)

    result = asyncio.run(main.run(template, script, output))

    assert result == output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["content"]["1"]["placeholders"]["0"] == (
        "Команда готовит запуск продукта"
    )
    assert payload["validation_report"] == {"ok": True, "issues": []}
    assert payload["error"] is None


def test_content_run_preserves_previous_output_on_pipeline_error(
    tmp_path: Path,
    monkeypatch,
    service_importer,
) -> None:
    main = service_importer(CONTENT_SERVICE_ROOT, "app.main")
    errors = importlib.import_module("app.errors")
    template = tmp_path / "template.json"
    script = tmp_path / "script.txt"
    output = tmp_path / "generated.json"
    _write_template(template)
    script.write_text("Команда готовит запуск продукта", encoding="utf-8")
    output.write_text("previous result", encoding="utf-8")

    class FailingGraph:
        async def ainvoke(self, _state):
            raise errors.ContentValidationError("контент не прошёл проверку")

    monkeypatch.setattr(main, "build_graph", FailingGraph)

    with pytest.raises(errors.ContentValidationError, match="не прошёл проверку"):
        asyncio.run(main.run(template, script, output))

    assert output.read_text(encoding="utf-8") == "previous result"


def test_content_run_cannot_overwrite_input(
    tmp_path: Path,
    service_importer,
) -> None:
    main = service_importer(CONTENT_SERVICE_ROOT, "app.main")
    template = tmp_path / "template.json"
    script = tmp_path / "script.txt"
    _write_template(template)
    script.write_text("Команда готовит запуск продукта", encoding="utf-8")
    original_template = template.read_bytes()

    with pytest.raises(ValueError, match="должен отличаться"):
        asyncio.run(main.run(template, script, template))

    assert template.read_bytes() == original_template


def test_content_cli_returns_nonzero_without_writing_error_payload(
    tmp_path: Path,
    monkeypatch,
    service_importer,
) -> None:
    main = service_importer(CONTENT_SERVICE_ROOT, "app.main")
    output = tmp_path / "generated.json"
    monkeypatch.setattr(main, "setup_logging", lambda: None)

    exit_code = main.main(
        [
            "--cli",
            "--template-json",
            str(tmp_path / "missing.json"),
            "--script",
            str(tmp_path / "missing.txt"),
            "--output-json",
            str(output),
        ]
    )

    assert exit_code == 1
    assert not output.exists()


def test_content_cli_cannot_overwrite_user_mapping(
    tmp_path: Path,
    monkeypatch,
    service_importer,
) -> None:
    main = service_importer(CONTENT_SERVICE_ROOT, "app.main")
    mapping = tmp_path / "mapping.json"
    mapping.write_text('{"1": {"0": "Пользовательский текст"}}', encoding="utf-8")
    original_mapping = mapping.read_bytes()
    monkeypatch.setattr(main, "setup_logging", lambda: None)

    exit_code = main.main(
        [
            "--cli",
            "--template-json",
            str(tmp_path / "missing.json"),
            "--script",
            str(tmp_path / "missing.txt"),
            "--user-mapping",
            str(mapping),
            "--output-json",
            str(mapping),
        ]
    )

    assert exit_code == 1
    assert mapping.read_bytes() == original_mapping
