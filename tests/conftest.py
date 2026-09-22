from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def _clear_service_modules() -> None:
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            del sys.modules[module_name]


@pytest.fixture
def service_importer():
    original_path = sys.path[:]
    services_root = Path(__file__).resolve().parents[1] / "services"
    service_roots = {str(path) for path in services_root.iterdir() if (path / "app").is_dir()}

    def import_module(service_root: Path, module_name: str):
        _clear_service_modules()
        # Namespace-пакет app пересчитывает пути при последующих импортах.
        # Держим выбранный сервис активным до следующего переключения, исключая
        # другие app roots, в том числе заданный в pytest.pythonpath parser.
        sys.path[:] = [
            str(service_root), *[path for path in original_path if path not in service_roots]
        ]
        return importlib.import_module(module_name)

    try:
        yield import_module
    finally:
        _clear_service_modules()
        sys.path[:] = original_path
