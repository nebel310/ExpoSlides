"""Запуск локальной студии с настройками LLM из памяти SSH-процесса."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SSH_ALIAS = "alex-cloud-1"
REMOTE_ROOT = "/home/alex/exposlides/current"
REMOTE_ENV = "/home/alex/exposlides/shared/content.env"
HF_BASE_URL = "https://router.huggingface.co/v1"
LLM_FIELDS = (
    "llm_api_key", "llm_base_url", "llm_model", "llm_fast_model", "llm_fast_repair_model",
    "llm_api_timeout", "llm_fast_api_timeout", "fast_generation_timeout",
    "llm_reasoning_effort", "llm_temperature", "llm_max_tokens", "llm_response_retries",
    "content_validation_retries",
)
SAFE_ERRORS = {
    "ssh": "Не удалось получить настройки через SSH. Проверьте доступ к alex-cloud-1.",
    "configuration": "Серверные настройки LLM не подходят для этого запуска студии.",
    "launch": "Не удалось запустить локальную студию. Проверьте окружение проекта.",
}


class LauncherError(Exception):
    """Только фиксированная публичная категория, без содержимого ответа SSH."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


def remote_program() -> str:
    # Программа не содержит секретов; stdout захватывает только вызывающий процесс.
    return f"""
import contextlib
import io
import json
import sys

try:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        sys.path.insert(0, {REMOTE_ROOT + '/services/content-service'!r})
        from app.config import Settings
        config = Settings(_env_file={REMOTE_ENV!r})
        payload = {{name.upper(): str(getattr(config, name)) for name in {LLM_FIELDS!r}}}
    print(json.dumps(payload))
except Exception:
    raise SystemExit(1)
"""


def validate_environment(payload: object) -> dict[str, str]:
    expected = {name.upper() for name in LLM_FIELDS}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise LauncherError("configuration")
    if any(not isinstance(value, str) or any(c in value for c in "\r\n\0")
           for value in payload.values()):
        raise LauncherError("configuration")
    key = payload["LLM_API_KEY"]
    if payload["LLM_BASE_URL"] != HF_BASE_URL or not (
        key.startswith("hf_") and len(key) > 3 and not any(c.isspace() for c in key)
    ):
        raise LauncherError("configuration")
    try:
        registry = tomllib.loads((ROOT / "config/models.toml").read_text(encoding="utf-8"))
        model = registry["models"]["qwen_3_8_27b"]
        approved = set(model["endpoint_aliases"])
        valid_model = model["id"] == "Qwen/Qwen3.8-27B" and all(
            payload[name] in approved
            for name in ("LLM_MODEL", "LLM_FAST_MODEL", "LLM_FAST_REPAIR_MODEL")
        )
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise LauncherError("configuration") from error
    if not valid_model:
        raise LauncherError("configuration")
    return dict(payload)


def fetch_environment() -> dict[str, str]:
    remote_command = (
        f"cd {shlex.quote(REMOTE_ROOT)} && "
        f"{shlex.quote(REMOTE_ROOT + '/.venv/bin/python')} -"
    )
    try:
        result = subprocess.run(
            ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
             "-o", "StrictHostKeyChecking=yes", SSH_ALIAS, remote_command],
            input=remote_program(), capture_output=True, text=True, encoding="utf-8",
            timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise LauncherError("ssh") from error
    if result.returncode:
        raise LauncherError("ssh")
    if len(result.stdout) > 32768:
        raise LauncherError("configuration")
    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError) as error:
        raise LauncherError("configuration") from error
    return validate_environment(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("Некорректный порт")
    try:
        data_dir = args.data_dir.expanduser().resolve()
        environment = fetch_environment()
        # Только память процесса: ключ не попадает в аргументы, файлы или вывод.
        os.environ.update(environment)
        os.environ["LOG_LEVEL"] = "INFO"
        os.chdir(ROOT)
        os.execv(sys.executable, [
            sys.executable, "-m", "exposlides.studio", "--port", str(args.port),
            "--data-dir", str(data_dir),
        ])
    except LauncherError as error:
        print(SAFE_ERRORS[error.category], file=sys.stderr)
        return 1
    except Exception:
        print(SAFE_ERRORS["launch"], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
