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
    def import_module(service_root: Path, module_name: str):
        _clear_service_modules()
        sys.path.insert(0, str(service_root))
        try:
            return importlib.import_module(module_name)
        finally:
            sys.path.pop(0)

    yield import_module
    _clear_service_modules()
