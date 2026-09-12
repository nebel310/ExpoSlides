from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parent.parent

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))


def _ensure_generated() -> None:
    """Генерирует pb-файлы если их ещё нет"""
    have_file_service = (SERVICE_ROOT / "file_service_pb2.py").exists()
    have_parser_service = (SERVICE_ROOT / "parser_service_pb2.py").exists()
    if have_file_service and have_parser_service:
        return
    subprocess.run(
        [
            sys.executable,
            "-m",
            "grpc_tools.protoc",
            "-Iproto",
            "--python_out=.",
            "--grpc_python_out=.",
            "proto/parser_service.proto",
            "proto/file_service.proto",
        ],
        check=True,
        cwd=SERVICE_ROOT,
    )


def pytest_configure(config: pytest.Config) -> None:
    """Гарантирует наличие pb-файлов до сбора тестов"""
    _ensure_generated()