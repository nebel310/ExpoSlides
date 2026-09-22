from __future__ import annotations

import importlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
preview = importlib.import_module("exposlides.preview")


@pytest.fixture
def renderer(monkeypatch):
    monkeypatch.setattr(preview.shutil, "which", lambda name: f"/tools/{name}")
    renderer = preview.PreviewRenderer(timeout=7)
    yield renderer
    renderer.close()


def install_fake_tools(monkeypatch, *, count=12, failure=None):
    """Подменить оба конвертера: без запуска программ и внешних сервисов."""
    calls = []
    killed = []

    class FakeProcess:
        pid = 123456

        def __init__(self, command, **kwargs):
            calls.append((command, kwargs))
            self.returncode = None
            self.command = command

        def wait(self, timeout):
            if failure == "timeout" and timeout != 5:
                raise subprocess.TimeoutExpired(self.command, timeout)
            if self.returncode is not None:
                return self.returncode
            self.returncode = 1 if failure == "exit" else 0
            if self.returncode:
                return self.returncode
            if "--convert-to" in self.command:
                folder = Path(self.command[self.command.index("--outdir") + 1])
                if failure != "missing_pdf":
                    (folder / f"{Path(self.command[-1]).stem}.pdf").write_bytes(b"PDF")
            else:
                prefix = Path(self.command[-1])
                for index in range(1, count + 1):
                    image = prefix.with_name(f"{prefix.name}-{index}.png")
                    signature = b"bad" if failure == "invalid_png" else preview.PNG_SIGNATURE
                    image.write_bytes(signature + str(index).encode())
            return 0

        def kill(self):
            killed.append(self.pid)
            self.returncode = -9

    monkeypatch.setattr(preview.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(preview.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    return calls, killed


def test_optional_renderer_requires_both_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(preview.shutil, "which", lambda name: None)
    monkeypatch.setattr(preview.Path, "is_file", lambda path: False)
    renderer = preview.PreviewRenderer()
    assert not renderer.available
    with pytest.raises(RuntimeError, match="LibreOffice и Poppler"):
        renderer.render(tmp_path / "input.pptx", tmp_path / "images", 1)
    renderer.close()


def test_render_preserves_page_order_and_exports_hidden_slides(renderer, monkeypatch, tmp_path):
    calls, _ = install_fake_tools(monkeypatch)
    source = tmp_path / "template with spaces.pptx"
    output = tmp_path / "images"

    images = renderer.render(source, output, 12)

    assert [image.name for image in images] == [f"slide-{index}.png" for index in range(1, 13)]
    assert [image.read_bytes()[8:] for image in images] == [
        str(index).encode() for index in range(1, 13)
    ]
    assert sorted(output.iterdir()) == sorted(images)
    command, options = calls[0]
    export_filter = command[command.index("--convert-to") + 1]
    assert json.loads(export_filter.split(":", 2)[2])["ExportHiddenSlides"] == {
        "type": "boolean", "value": "true"
    }
    assert command[-1] == str(source)
    assert any(arg.startswith("-env:UserInstallation=file://") for arg in command)
    assert options["start_new_session"] == (os.name == "posix")
    assert "XDG_CACHE_HOME" in options["env"]
    assert calls[1][0][1:4] == ["-png", "-scale-to", "1400"]


@pytest.mark.parametrize("failure", ["exit", "missing_pdf", "invalid_png"])
def test_failed_converter_does_not_publish_images(renderer, monkeypatch, tmp_path, failure):
    install_fake_tools(monkeypatch, count=2, failure=failure)
    output = tmp_path / "images"
    with pytest.raises(RuntimeError):
        renderer.render(tmp_path / "input.pptx", output, 2)
    assert not list(output.iterdir())


def test_missing_slide_does_not_shift_later_previews(renderer, monkeypatch, tmp_path):
    install_fake_tools(monkeypatch, count=2)
    with pytest.raises(RuntimeError, match="Число кадров"):
        renderer.render(tmp_path / "input.pptx", tmp_path / "images", 3)
    assert not list((tmp_path / "images").iterdir())


def test_timeout_kills_entire_process_group(renderer, monkeypatch, tmp_path):
    calls, killed = install_fake_tools(monkeypatch, failure="timeout")
    with pytest.raises(RuntimeError, match="Превышено время"):
        renderer.render(tmp_path / "input.pptx", tmp_path / "images", 1)
    expected = [(123456, signal.SIGKILL)] if os.name == "posix" else [123456]
    assert killed == expected
    assert len(calls) == 1
    assert not list((tmp_path / "images").iterdir())


def test_close_stops_running_conversion_and_prevents_next_step(renderer, monkeypatch, tmp_path):
    calls, killed = install_fake_tools(monkeypatch)
    fake_process = preview.subprocess.Popen

    class ClosingProcess(fake_process):
        def wait(self, timeout):
            if timeout != 5:
                renderer.close()
            return super().wait(timeout)

    monkeypatch.setattr(preview.subprocess, "Popen", ClosingProcess)
    with pytest.raises(RuntimeError, match="остановлен"):
        renderer.render(tmp_path / "input.pptx", tmp_path / "images", 12)
    expected = [(123456, signal.SIGKILL)] if os.name == "posix" else [123456]
    assert killed == expected
    assert len(calls) == 1
    renderer.close()
    with pytest.raises(RuntimeError, match="остановлен"):
        renderer.render(tmp_path / "input.pptx", tmp_path / "images", 12)
    assert len(calls) == 1
