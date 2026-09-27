import json
from pathlib import Path

import pytest

from exposlides import run_config


def test_run_resolves_paths_from_config_directory_and_preserves_materials(tmp_path, monkeypatch):
    (tmp_path/"brief.txt").write_text("Поддержка работает круглосуточно.", encoding="utf-8")
    (tmp_path/"run.toml").write_text('''template = "brand.pptx"
script = "brief.txt"
output_dir = "result"
[generation]
mode = "extractive"
slide_count = 1
''', encoding="utf-8")
    captured = {}

    def execute(args):
        options = dict(zip(args[::2], args[1::2], strict=True))
        captured.update(options)
        request = json.loads(Path(options["--request"]).read_text(encoding="utf-8"))
        assert request["script"] == "Поддержка работает круглосуточно."
        assert request["mode"] == "extractive"
        return 0

    monkeypatch.setattr(run_config, "run_designer", execute)
    monkeypatch.chdir(tmp_path.parent)
    assert run_config.run(tmp_path/"run.toml") == 0
    assert captured["--template"] == str(tmp_path/"brand.pptx")
    assert captured["--output-dir"] == str(tmp_path/"result")
    assert not Path(captured["--request"]).exists()


def test_unknown_config_fields_fail_before_generation(tmp_path, monkeypatch):
    path = tmp_path/"run.toml"
    path.write_text('template="t.pptx"\nscript="s.txt"\noutput_dir="out"\napi_key="forbidden"',
                    encoding="utf-8")
    monkeypatch.setattr(run_config, "run_designer", lambda args: pytest.fail("must not run"))
    with pytest.raises(ValueError):
        run_config.run(path)
