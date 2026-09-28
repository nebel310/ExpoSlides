"""Локальный запуск проверяется без SSH, .env и настоящего LLM."""
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

LAUNCHER = Path(__file__).resolve().parents[1] / "deploy/alex-cloud/run-local-studio.py"


@pytest.fixture
def launcher(monkeypatch):
    spec = importlib.util.spec_from_file_location("local_studio_launcher", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "os", SimpleNamespace(
        environ={"LOG_LEVEL": "DEBUG", "KEEP_LOCAL": "yes"}, chdir=Mock(), execv=Mock(),
    ))
    return module


def valid_payload(module):
    payload = {field.upper(): "1" for field in module.LLM_FIELDS}
    payload.update({
        "LLM_API_KEY": "hf_offline-fake-secret", "LLM_BASE_URL": module.HF_BASE_URL,
        "LLM_MODEL": "Qwen/Qwen3.8-27B:deepinfra",
        "LLM_FAST_MODEL": "Qwen/Qwen3.8-27B:deepinfra",
        "LLM_FAST_REPAIR_MODEL": "Qwen/Qwen3.8-27B:deepinfra",
    })
    return payload


def mock_ssh(module, monkeypatch, *, payload=None, returncode=0, failure=None):
    response = SimpleNamespace(
        stdout=json.dumps(valid_payload(module) if payload is None else payload),
        stderr="private SSH diagnostic and key", returncode=returncode,
    )
    run = Mock(return_value=response, side_effect=failure)
    monkeypatch.setattr(module.subprocess, "run", run)
    return run


def test_launcher_execs_studio_with_in_memory_whitelisted_settings(
    launcher, monkeypatch, tmp_path, capsys,
):
    run = mock_ssh(launcher, monkeypatch)
    data_dir = tmp_path / "studio"
    assert launcher.main(["--data-dir", str(data_dir)]) == 0
    command = run.call_args.args[0]
    assert command[0] == "ssh" and launcher.SSH_ALIAS in command
    assert "BatchMode=yes" in command and "StrictHostKeyChecking=yes" in command
    assert launcher.REMOTE_ROOT + "/.venv/bin/python" in command[-1]
    assert run.call_args.kwargs["capture_output"] is True
    assert run.call_args.kwargs["timeout"] == 30
    assert launcher.REMOTE_ENV in run.call_args.kwargs["input"]
    assert "hf_offline" not in repr(run.call_args)
    assert launcher.os.environ == valid_payload(launcher) | {
        "LOG_LEVEL": "INFO", "KEEP_LOCAL": "yes",
    }
    launcher.os.chdir.assert_called_once_with(launcher.ROOT)
    launcher.os.execv.assert_called_once_with(launcher.sys.executable, [
        launcher.sys.executable, "-m", "exposlides.studio", "--port", "8767",
        "--data-dir", str(data_dir),
    ])
    assert list(tmp_path.iterdir()) == []
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("field,value", [
    ("LLM_API_KEY", "wrong-provider-private-secret"), ("LLM_API_KEY", "hf_"),
    ("LLM_API_KEY", "hf_secret\nprivate"),
    ("LLM_BASE_URL", "https://private-host.example/v1"),
    ("LLM_BASE_URL", "https://router.huggingface.co/v1?private=value"),
    ("LLM_FAST_MODEL", "unregistered-private-model"),
    ("LLM_MODEL", "unregistered-private-model"),
    ("LLM_FAST_REPAIR_MODEL", "unregistered-private-model"),
    ("LLM_MAX_TOKENS", 100), ("UNEXPECTED_SECRET", "private"),
])
def test_launcher_rejects_configuration_before_environment_mutation(
    launcher, monkeypatch, tmp_path, capsys, field, value,
):
    mock_ssh(launcher, monkeypatch, payload=valid_payload(launcher) | {field: value})
    assert launcher.main(["--data-dir", str(tmp_path)]) == 1
    assert launcher.os.environ == {"LOG_LEVEL": "DEBUG", "KEEP_LOCAL": "yes"}
    launcher.os.execv.assert_not_called()
    assert capsys.readouterr() == ("", launcher.SAFE_ERRORS["configuration"] + "\n")


@pytest.mark.parametrize("failure", [
    OSError("private secret"),
    subprocess.TimeoutExpired("private command", 30, output="private secret"),
    subprocess.CalledProcessError(1, "private command", stderr="private secret"),
])
def test_launcher_does_not_expose_ssh_errors(launcher, monkeypatch, tmp_path, capsys, failure):
    mock_ssh(launcher, monkeypatch, failure=failure)
    assert launcher.main(["--data-dir", str(tmp_path)]) == 1
    launcher.os.execv.assert_not_called()
    assert capsys.readouterr() == ("", launcher.SAFE_ERRORS["ssh"] + "\n")


def test_launcher_rejects_failed_remote_process(launcher, monkeypatch, tmp_path, capsys):
    mock_ssh(launcher, monkeypatch, returncode=1)
    assert launcher.main(["--data-dir", str(tmp_path)]) == 1
    launcher.os.execv.assert_not_called()
    assert capsys.readouterr() == ("", launcher.SAFE_ERRORS["ssh"] + "\n")


def test_launcher_does_not_expose_exec_failure(launcher, monkeypatch, tmp_path, capsys):
    mock_ssh(launcher, monkeypatch)
    launcher.os.execv.side_effect = OSError("private secret")
    assert launcher.main(["--port", "8768", "--data-dir", str(tmp_path)]) == 1
    assert "8768" in launcher.os.execv.call_args.args[1]
    assert capsys.readouterr() == ("", launcher.SAFE_ERRORS["launch"] + "\n")


@pytest.mark.parametrize("port", ["0", "65536"])
def test_launcher_rejects_bad_port_before_ssh(launcher, monkeypatch, tmp_path, port):
    run = mock_ssh(launcher, monkeypatch)
    with pytest.raises(SystemExit) as raised:
        launcher.main(["--port", port, "--data-dir", str(tmp_path)])
    assert raised.value.code == 2
    run.assert_not_called()
