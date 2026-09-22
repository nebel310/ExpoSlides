from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCENARIOS = [
    "completed_result",
    "pending_result",
    "result_preview_polling",
    "result_navigation",
    "template_upload_stays_on_materials",
    "stale_result_metadata",
    "stale_result_preview",
    "stale_template_preview",
    "restore_completed_job",
    "result_metadata_failure",
    "result_preview_failure",
    "result_image_failure",
]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_result_preview_browser_state_offline(scenario):
    """Настоящий app.js работает с DOM и ответами API в памяти, без сервера и LLM."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js нужен для офлайн-проверки браузерного app.js")
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [node, str(root / "tests" / "web_ui_scenarios.js"), scenario],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
