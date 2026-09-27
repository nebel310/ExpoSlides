"""Локальный предпросмотр PPTX через LibreOffice и Poppler."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

PDF_EXPORT = (
    'pdf:impress_pdf_Export:{"ExportHiddenSlides":{"type":"boolean","value":"true"}}'
)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PreviewRenderer:
    """Один фоновый рендерер; запуск очереди контролирует веб-приложение."""

    def __init__(self, timeout: float = 90, *, deadline: float | None = None) -> None:
        self.soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if self.soffice is None:
            mac_app = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
            if mac_app.is_file() and os.access(mac_app, os.X_OK):
                self.soffice = str(mac_app)
        self.pdftoppm = shutil.which("pdftoppm")
        self.timeout = timeout
        self.deadline = deadline
        self._lock = threading.Lock()
        self._closed = False
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def available(self) -> bool:
        return self.soffice is not None and self.pdftoppm is not None

    def render(
        self, source: Path, output_dir: Path, slide_count: int, *, pdf_output: Path | None = None,
    ) -> list[Path]:
        """Вернуть кадры всех слайдов, включая скрытые, в исходном порядке."""
        soffice, pdftoppm = self.soffice, self.pdftoppm
        if soffice is None or pdftoppm is None:
            raise RuntimeError("Для предпросмотра нужны LibreOffice и Poppler.")
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".render-", dir=output_dir) as directory:
            work = Path(directory)
            cache = work / "cache"
            cache.mkdir()
            environment = os.environ.copy()
            environment["XDG_CACHE_HOME"] = str(cache)
            self._run(
                [
                    soffice,
                    f"-env:UserInstallation={(work / 'profile').as_uri()}",
                    "--headless",
                    "--convert-to",
                    PDF_EXPORT,
                    "--outdir",
                    str(work),
                    str(source.resolve()),
                ],
                environment,
            )
            pdf = work / f"{source.stem}.pdf"
            if not pdf.is_file() or pdf.stat().st_size == 0:
                raise RuntimeError("Не удалось создать предпросмотр презентации.")
            if pdf_output is not None:
                pdf_output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(pdf, pdf_output)
            self._run(
                [pdftoppm, "-png", "-scale-to", "1400", str(pdf), str(work / "slide")],
                environment,
            )
            images = sorted(work.glob("slide-*.png"), key=lambda path: int(path.stem[6:]))
            if len(images) != slide_count:
                raise RuntimeError("Число кадров предпросмотра не совпадает с числом слайдов.")
            for image in images:
                with image.open("rb") as stream:
                    if stream.read(8) != PNG_SIGNATURE:
                        raise RuntimeError("Получен повреждённый кадр предпросмотра.")
            with self._lock:
                if self._closed:
                    raise RuntimeError("Предпросмотр остановлен.")
                return [
                    image.replace(output_dir / f"slide-{index}.png")
                    for index, image in enumerate(images, start=1)
                ]

    def _run(self, command: list[str], environment: dict[str, str]) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("Предпросмотр остановлен.")
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=environment,
                start_new_session=os.name == "posix",
            )
            self._process = process
        try:
            try:
                remaining = self.timeout if self.deadline is None else min(
                    self.timeout, max(0, self.deadline-time.monotonic()),
                )
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as error:
                self._kill(process)
                raise RuntimeError("Превышено время создания предпросмотра.") from error
            if process.returncode != 0:
                raise RuntimeError("Не удалось создать предпросмотр презентации.")
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None

    @staticmethod
    def _kill(process: subprocess.Popen[bytes]) -> None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    def close(self) -> None:
        """Остановить дочерние процессы и запретить новые запуски."""
        with self._lock:
            self._closed = True
            process = self._process
        if process is not None:
            self._kill(process)
