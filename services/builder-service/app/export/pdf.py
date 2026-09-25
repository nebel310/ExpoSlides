from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

LIBREOFFICE_BINARY = "soffice"
PDF_SUFFIX = ".pdf"


class PdfExportError(RuntimeError):
    """Не удалось сконвертировать PPTX в PDF"""


async def convert_pptx_to_pdf(
    source_pptx: Path,
    output_dir: Path,
    *,
    timeout: float = 120.0,
) -> Path:
    """Конвертирует PPTX в PDF, возвращает путь к созданному файлу"""
    binary = shutil.which(LIBREOFFICE_BINARY)
    if binary is None:
        raise PdfExportError(
            f"{LIBREOFFICE_BINARY} не найден в PATH; установите LibreOffice"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = output_dir / f".lo-profile-{uuid4().hex}"
    profile_dir.mkdir(parents=True, exist_ok=True)

    command = [
        binary,
        f"-env:UserInstallation=file://{profile_dir}",
        "--headless",
        "--norestore",
        "--nologo",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(source_pptx),
    ]
    logger.info("LibreOffice стартует: %s", " ".join(command))

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as error:
        raise PdfExportError(f"Не удалось запустить soffice: {error}") from error

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as error:
        process.kill()
        await process.wait()
        raise PdfExportError(f"LibreOffice превысил таймаут {timeout} с") from error

    if process.returncode != 0:
        raise PdfExportError(
            f"LibreOffice завершился с кодом {process.returncode}: "
            f"{stderr.decode('utf-8', errors='replace')[:500]}"
        )

    expected = output_dir / (source_pptx.stem + PDF_SUFFIX)
    if not expected.is_file():
        raise PdfExportError(
            f"LibreOffice не создал PDF {expected}; "
            f"stdout={stdout[:300]!r} stderr={stderr[:300]!r}"
        )

    logger.info("PDF создан: %s (%d байт)", expected, expected.stat().st_size)
    return expected