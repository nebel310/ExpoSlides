"""Изолированные офлайн suites: uv run python scripts/test_services.py [--service gateway]."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = {"parser": "parsing-service", "content": "content-service", "gateway": "gateway-service"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", action="append", choices=SERVICES)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="exposlides-service-tests-") as directory:
        temporary = Path(directory)
        generated = temporary / "proto"
        generated.mkdir()
        command = [
            sys.executable, "-m", "grpc_tools.protoc", f"-I{ROOT / 'proto'}",
            f"--python_out={generated}", f"--grpc_python_out={generated}",
            *map(str, sorted((ROOT / "proto").glob("*.proto"))),
        ]
        subprocess.run(command, check=True, cwd=temporary)
        failed = False
        for name in args.service or SERVICES:
            service = ROOT / "services" / SERVICES[name]
            environment = os.environ.copy()
            environment["PYTHONPATH"] = os.pathsep.join((str(generated), str(service)))
            environment["LLM_API_KEY"] = "offline-test-key"
            environment["LOG_FILE"] = str(temporary / f"{name}.log")
            command = [
                sys.executable, "-m", "pytest", str(service / "tests"),
                "-c", str(ROOT / "pyproject.toml"),
                "-o", "asyncio_mode=auto", "-o", f"pythonpath={service}",
                "-o", f"cache_dir={temporary / 'pytest-cache'}",
                f"--ignore={service / 'tests/integration'}",
                f"--ignore={service / 'tests/e2e'}",
            ]
            print(f"Офлайн-проверки: {name}", flush=True)
            result = subprocess.run(command, cwd=temporary, env=environment, check=False)
            failed = failed or result.returncode != 0
        return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
