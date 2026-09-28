from __future__ import annotations

import errno
import os
import pty
import select
import signal
import subprocess
import termios
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/alex-cloud/set-openrouter-key.sh"
FAKE_KEY = "sk-or-v1-dummy-test-key"


def _run_interactively(
    tmp_path: Path,
    environment_file: Path,
    key: str,
    *,
    restart_status: int = 0,
    trace_shell: bool = False,
) -> tuple[int, str, list[str]]:
    """Использует изолированный терминал и подменённый sudo без внешних вызовов."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    sudo = bin_dir / "sudo"
    sudo.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$*" >> "$TEST_CALLS_FILE"\n'
        'if [[ "$2" == restart ]]; then exit "$TEST_RESTART_STATUS"; fi\n',
        encoding="utf-8",
    )
    sudo.chmod(0o700)
    calls = tmp_path / "calls.log"
    process_env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "TEST_CALLS_FILE": str(calls),
        "TEST_RESTART_STATUS": str(restart_status),
    }
    pid, terminal = pty.fork()
    if pid == 0:
        arguments = ["bash", *(["-x"] if trace_shell else []), str(SCRIPT), str(environment_file)]
        os.execve("/bin/bash", arguments, process_env)

    output = bytearray()
    submitted = False
    deadline = time.monotonic() + 10
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([terminal], [], [], 0.1)
            if ready:
                try:
                    part = os.read(terminal, 4096)
                except OSError as error:
                    if error.errno == errno.EIO:
                        break
                    raise
                if not part:
                    break
                output.extend(part)
            if (
                not submitted
                and "нажмите Enter: " in output.decode("utf-8", errors="replace")
                and not termios.tcgetattr(terminal)[3] & termios.ECHO
            ):
                os.write(terminal, f"{key}\n".encode())
                submitted = True
        else:
            os.kill(pid, signal.SIGKILL)
            pytest.fail("Скрипт не завершился после интерактивного ввода")
    finally:
        os.close(terminal)
        _, status = os.waitpid(pid, 0)
    assert submitted, output.decode("utf-8")
    return (
        os.waitstatus_to_exitcode(status),
        output.decode("utf-8"),
        calls.read_text(encoding="utf-8").splitlines() if calls.exists() else [],
    )


@pytest.mark.parametrize("trace_shell", [False, True])
def test_key_setup_migrates_config_without_exposing_key(
    tmp_path: Path, trace_shell: bool
) -> None:
    environment_file = tmp_path / "content.env"
    environment_file.write_text(
        "# Keep this comment\nLLM_API_TIMEOUT=180\n"
        "LLM_API_KEY=old-dummy\n export LLM_API_KEY = 'duplicate-dummy'\n"
        "LLM_BASE_URL=https://old.example\nLLM_MODEL=old\nLLM_FAST_MODEL=old\n"
        "LLM_FAST_REPAIR_MODEL=old\nexport LLM_SCOPE=old\n"
        " GIGACHAT_CA_BUNDLE_FILE = /old/file\nUNRELATED_SETTING='unchanged'\n",
        encoding="utf-8",
    )
    environment_file.chmod(0o644)

    status, output, calls = _run_interactively(
        tmp_path, environment_file, FAKE_KEY, trace_shell=trace_shell
    )

    assert status == 0, output
    assert FAKE_KEY not in output
    assert "old-dummy" not in output
    assert environment_file.stat().st_mode & 0o777 == 0o600
    assert environment_file.read_text(encoding="utf-8") == (
        "# Keep this comment\nLLM_API_TIMEOUT=180\nUNRELATED_SETTING='unchanged'\n"
        f"LLM_API_KEY={FAKE_KEY}\n"
        "LLM_BASE_URL=https://openrouter.ai/api/v1\n"
        "LLM_MODEL=qwen/qwen3.8-27b:free\n"
        "LLM_FAST_MODEL=qwen/qwen3.8-27b:free\n"
        "LLM_FAST_REPAIR_MODEL=qwen/qwen3.8-27b:free\n"
    )
    assert calls == ["systemctl restart exposlides", "systemctl is-active --quiet exposlides"]
    assert not list(tmp_path.glob("content.env.tmp.*"))


@pytest.mark.parametrize("key", ["", "key with spaces", "key'quote", "key$(command)"])
def test_invalid_key_leaves_config_and_service_unchanged(tmp_path: Path, key: str) -> None:
    environment_file = tmp_path / "content.env"
    original = "UNRELATED_SETTING=unchanged\n"
    environment_file.write_text(original, encoding="utf-8")

    status, output, calls = _run_interactively(tmp_path, environment_file, key)

    assert status == 1
    if key:
        assert key not in output
    assert environment_file.read_text(encoding="utf-8") == original
    assert calls == []
    assert not list(tmp_path.glob("content.env.tmp.*"))


def test_key_setup_creates_missing_file_and_reports_failed_restart(tmp_path: Path) -> None:
    environment_file = tmp_path / "content.env"

    status, output, calls = _run_interactively(
        tmp_path, environment_file, FAKE_KEY, restart_status=1
    )

    assert status == 1
    assert FAKE_KEY not in output
    assert "перезапуск ExpoSlides завершился ошибкой" in output
    assert f"LLM_API_KEY={FAKE_KEY}\n" in environment_file.read_text(encoding="utf-8")
    assert calls == ["systemctl restart exposlides"]


def test_key_setup_rejects_noninteractive_input(tmp_path: Path) -> None:
    environment_file = tmp_path / "content.env"
    result = subprocess.run(
        ["bash", str(SCRIPT), str(environment_file)],
        input=FAKE_KEY,
        capture_output=True,
        text=True,
        start_new_session=True,
        check=False,
    )

    assert result.returncode == 1
    assert FAKE_KEY not in result.stdout + result.stderr
    assert "ssh -t" in result.stderr
    assert not environment_file.exists()
