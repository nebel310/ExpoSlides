from __future__ import annotations

from pathlib import Path

import pytest

from exposlides import preview


def make_runtime(tmp_path: Path, *, wrapper: bool) -> tuple[Path, Path]:
    runtime = tmp_path / "runtime with spaces"
    app = runtime / "native/libreoffice-headless/libreoffice/LibreOfficeDev.app/Contents"
    config = app / "Resources/fontconfig/fonts.conf"
    config.parent.mkdir(parents=True)
    config.write_text("<fontconfig/>", encoding="utf-8")
    executable = runtime / "bin/override/soffice" if wrapper else app / "MacOS/soffice"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.touch()
    return executable, config


@pytest.mark.parametrize("wrapper", [False, True])
def test_bundled_renderer_uses_fontconfig_with_host_font_directories(tmp_path, wrapper):
    executable, config = make_runtime(tmp_path, wrapper=wrapper)
    environment = {"XDG_CACHE_HOME": str(tmp_path / "cache")}

    preview._configure_font_discovery(str(executable), environment)

    assert environment == {
        "FONTCONFIG_FILE": str(config),
        "FONTCONFIG_PATH": str(config.parent),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }


@pytest.mark.parametrize("key", ["FONTCONFIG_FILE", "FONTCONFIG_PATH"])
@pytest.mark.parametrize("value", ["", "/custom/fonts"])
def test_explicit_font_configuration_is_preserved(tmp_path, key, value):
    executable, _ = make_runtime(tmp_path, wrapper=True)
    environment = {key: value}

    preview._configure_font_discovery(str(executable), environment)

    assert environment == {key: value}


def test_system_renderer_without_bundled_config_keeps_default_environment(tmp_path):
    environment = {"XDG_CACHE_HOME": str(tmp_path / "cache")}

    preview._configure_font_discovery(str(tmp_path / "bin/soffice"), environment)

    assert environment == {"XDG_CACHE_HOME": str(tmp_path / "cache")}


def test_symlink_to_bundled_renderer_resolves_fontconfig(tmp_path):
    executable, config = make_runtime(tmp_path, wrapper=False)
    link = tmp_path / "soffice"
    link.symlink_to(executable)
    environment = {}

    preview._configure_font_discovery(str(link), environment)

    assert environment["FONTCONFIG_FILE"] == str(config)


def test_render_passes_fontconfig_to_both_converters_without_changing_process_env(
    tmp_path, monkeypatch,
):
    executable, config = make_runtime(tmp_path, wrapper=True)
    monkeypatch.delenv("FONTCONFIG_FILE", raising=False)
    monkeypatch.delenv("FONTCONFIG_PATH", raising=False)
    monkeypatch.setattr(preview.shutil, "which", lambda name: (
        str(executable) if name == "soffice" else "/tools/pdftoppm"
    ))
    source = tmp_path / "input.pptx"
    calls = []

    def convert(command, environment):
        calls.append(environment.copy())
        if "--convert-to" in command:
            output = Path(command[command.index("--outdir") + 1])
            (output / "input.pdf").write_bytes(b"PDF")
        else:
            Path(f"{command[-1]}-1.png").write_bytes(preview.PNG_SIGNATURE)

    renderer = preview.PreviewRenderer()
    monkeypatch.setattr(renderer, "_run", convert)
    images = renderer.render(source, tmp_path / "images", 1)

    assert len(images) == 1
    assert len(calls) == 2
    assert all(call["FONTCONFIG_FILE"] == str(config) for call in calls)
    assert all(call["FONTCONFIG_PATH"] == str(config.parent) for call in calls)
    assert "FONTCONFIG_FILE" not in preview.os.environ
    assert "FONTCONFIG_PATH" not in preview.os.environ
