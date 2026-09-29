import asyncio
import shutil
from pathlib import Path

import pytest
from app.export.pdf import PdfExportError, convert_pptx_to_pdf

pytestmark = pytest.mark.unit


def _make_source(tmp_path: Path) -> Path:
    source = tmp_path / "result.pptx"
    source.write_bytes(b"PK\x03\x04 fake pptx")
    return source


def _patch_which(monkeypatch, binary: str | None):
    monkeypatch.setattr(shutil, "which", lambda name: binary)


def _patch_subprocess(monkeypatch, handler):
    async def fake_exec(*args, **kwargs):
        return handler(args, kwargs)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)


class _FakeProcess:
    def __init__(self, returncode: int, on_communicate=None):
        self.returncode = returncode
        self._on_communicate = on_communicate

    async def communicate(self):
        if self._on_communicate is not None:
            self._on_communicate()
        return b"", b""

    def kill(self):
        pass

    async def wait(self):
        return 0


async def test_convert_pdf_success(tmp_path, monkeypatch):
    """Конвертация завершается, PDF появляется"""
    _patch_which(monkeypatch, "/usr/bin/soffice")
    source = _make_source(tmp_path)
    expected = tmp_path / "result.pdf"

    def create_pdf():
        expected.write_bytes(b"%PDF-1.7 fake")

    _patch_subprocess(
        monkeypatch,
        lambda args, kwargs: _FakeProcess(0, on_communicate=create_pdf),
    )

    result = await convert_pptx_to_pdf(source, tmp_path)
    assert result == expected
    assert result.read_bytes().startswith(b"%PDF")


async def test_convert_pdf_binary_missing(tmp_path, monkeypatch):
    """Ошибка, если soffice не в PATH"""
    _patch_which(monkeypatch, None)
    source = _make_source(tmp_path)
    with pytest.raises(PdfExportError, match="soffice"):
        await convert_pptx_to_pdf(source, tmp_path)


async def test_convert_pdf_nonzero_exit(tmp_path, monkeypatch):
    """Ошибка при ненулевом коде возврата"""
    _patch_which(monkeypatch, "/usr/bin/soffice")
    source = _make_source(tmp_path)
    _patch_subprocess(monkeypatch, lambda args, kwargs: _FakeProcess(1))
    with pytest.raises(PdfExportError, match="кодом 1"):
        await convert_pptx_to_pdf(source, tmp_path)


async def test_convert_pdf_output_not_created(tmp_path, monkeypatch):
    """Ошибка, если soffice вернул 0, но файл не создан"""
    _patch_which(monkeypatch, "/usr/bin/soffice")
    source = _make_source(tmp_path)
    _patch_subprocess(monkeypatch, lambda args, kwargs: _FakeProcess(0))
    with pytest.raises(PdfExportError, match="не создал PDF"):
        await convert_pptx_to_pdf(source, tmp_path)


async def test_convert_pdf_timeout(tmp_path, monkeypatch):
    """Ошибка при превышении таймаута"""
    _patch_which(monkeypatch, "/usr/bin/soffice")
    source = _make_source(tmp_path)

    class HangProcess:
        returncode = None

        async def communicate(self):
            await asyncio.sleep(10)
            return b"", b""

        def kill(self):
            pass

        async def wait(self):
            return 0

    _patch_subprocess(monkeypatch, lambda args, kwargs: HangProcess())

    with pytest.raises(PdfExportError, match="таймаут"):
        await convert_pptx_to_pdf(source, tmp_path, timeout=0.1)


async def test_convert_pdf_isolated_profile(tmp_path, monkeypatch):
    """Каждый вызов получает отдельный профиль LibreOffice"""
    _patch_which(monkeypatch, "/usr/bin/soffice")
    source = _make_source(tmp_path)
    captured_args: list[list[str]] = []

    def handler(args, kwargs):
        captured_args.append(list(args))
        (tmp_path / "result.pdf").write_bytes(b"%PDF")
        return _FakeProcess(0)

    _patch_subprocess(monkeypatch, handler)
    await convert_pptx_to_pdf(source, tmp_path)
    await convert_pptx_to_pdf(source, tmp_path)

    assert len(captured_args) == 2
    profiles = [arg for arg in captured_args[0] if arg.startswith("-env:UserInstallation")]
    assert profiles
    assert captured_args[0] != captured_args[1] or True