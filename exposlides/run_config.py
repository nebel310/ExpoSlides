"""Полный запуск из одного TOML: uv run python -m exposlides.run_config run.toml."""

from __future__ import annotations

import argparse
import tempfile
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from exposlides.design_cli import main as run_designer
from exposlides.design_models import DesignRequest


class RunConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: Path
    script: Path
    output_dir: Path
    timeout_seconds: float = Field(default=300, ge=1, le=300)
    generation: dict = Field(default_factory=dict)


def run(path: Path) -> int:
    configuration = RunConfiguration.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
    base = path.resolve().parent

    def resolve(value: Path) -> Path:
        return value.resolve() if value.is_absolute() else (base/value).resolve()

    script = resolve(configuration.script).read_text(encoding="utf-8")
    if "script" in configuration.generation:
        raise ValueError("Исходный текст задаётся файлом script, а не полем generation.script")
    request = DesignRequest(script=script, **configuration.generation)
    with tempfile.TemporaryDirectory(prefix="exposlides-config-") as temporary:
        request_file = Path(temporary)/"request.json"
        request_file.write_text(request.model_dump_json(indent=2), encoding="utf-8")
        return run_designer([
            "--template", str(resolve(configuration.template)),
            "--request", str(request_file), "--output-dir", str(resolve(configuration.output_dir)),
            "--timeout", str(configuration.timeout_seconds),
        ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    try:
        return run(args.config)
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
