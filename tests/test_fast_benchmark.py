from __future__ import annotations

import importlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

EVAL_ROOT = Path(__file__).resolve().parents[1] / "evals"


@pytest.fixture
def benchmark(monkeypatch):
    monkeypatch.syspath_prepend(str(EVAL_ROOT))
    return importlib.import_module("benchmark_fast")


def test_benchmark_saves_score_and_runs_isolated_stages_without_printing_logs(
    benchmark, tmp_path, monkeypatch, capsys,
):
    directory = tmp_path / "run"
    commands = []
    case = benchmark.load_case()

    class Process:
        def __init__(self, command, **kwargs):
            commands.append((command, kwargs))
            kwargs["stdout"].write("PRIVATE_LOG_CONTENT\n")
            service = kwargs["cwd"].name
            if service == "parsing-service":
                (directory / "template.json").write_text("{}", encoding="utf-8")
            elif service == "content-service":
                content = {
                    "content": {
                        str(index): {"placeholders": {"0": section["title"], "1": section["text"]}}
                        for index, section in enumerate(case["sections"], start=1)
                    },
                    "validation_report": {"ok": True, "issues": []},
                }
                (directory / "content.json").write_text(json.dumps(content), encoding="utf-8")
            else:
                shutil.copyfile(directory / "template.pptx", directory / "result.pptx")

        def wait(self, timeout):
            assert 0 < timeout <= 300
            return 0

    monkeypatch.setattr(benchmark.subprocess, "Popen", Process)
    assert benchmark.main(["--output-dir", str(directory)]) == 0
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    assert summary["success"]
    assert summary["slides"] == 15
    assert summary["quality"]["score"] == 100
    assert list(summary["stages"]) == ["parser", "content", "builder"]
    assert "PRIVATE_LOG_CONTENT" not in capsys.readouterr().out
    assert len(json.loads((directory / "mapping.json").read_text(encoding="utf-8"))) == 15
    command, options = commands[1]
    assert command[command.index("--generation-mode") + 1] == "fast"
    assert options["env"]["LOG_LEVEL"] == "INFO"
    assert options["env"]["LOG_FILE"] == str(directory / "content.log")
    assert [options["cwd"].name for _, options in commands] == [
        "parsing-service", "content-service", "builder-service",
    ]


def test_benchmark_timeout_stops_its_process_group_and_does_not_run_next_stage(
    benchmark, tmp_path, monkeypatch,
):
    calls, signals = [], []

    class Process:
        pid = 12345

        def __init__(self, command, **kwargs):
            calls.append(command)

        def wait(self, timeout):
            raise subprocess.TimeoutExpired("fake", timeout)

        def kill(self):
            signals.append("kill")

    monkeypatch.setattr(benchmark.subprocess, "Popen", Process)
    monkeypatch.setattr(benchmark.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    summary = benchmark.run_benchmark(tmp_path / "run")
    assert not summary["success"]
    assert summary["error"] == "time_budget_exceeded"
    assert summary["stages"]["parser"]["timed_out"]
    assert len(calls) == 1
    assert signals


def test_benchmark_rejects_nonempty_output_directory(benchmark, tmp_path, monkeypatch):
    existing = tmp_path / "result.pptx"
    existing.write_bytes(b"previous result")
    monkeypatch.setattr(
        benchmark.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("unexpected process"),
    )
    assert benchmark.main(["--output-dir", str(tmp_path)]) == 1
    assert existing.read_bytes() == b"previous result"
    assert not (tmp_path / "summary.json").exists()
