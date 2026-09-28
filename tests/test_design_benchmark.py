from pathlib import Path

import pytest
from pptx import Presentation

from exposlides.design_content import extractive_plan, source_excerpts, validate_story
from scripts.benchmark_designer import CASES, main, make_request, make_template


@pytest.mark.parametrize("case,count", CASES)
def test_benchmark_sources_are_valid_editable_offline_fixtures(tmp_path, case, count):
    path = tmp_path / "template.pptx"
    make_template(path, case)
    presentation = Presentation(path)
    assert len(presentation.slides) == 1
    assert not list(presentation.slides[0].placeholders)
    request = make_request(count)
    excerpts = source_excerpts(request.script)
    story = extractive_plan(request, excerpts)
    assert len(story.slides) == count
    assert not validate_story(story, request, excerpts)
    assert request.mode == "extractive"
    assert not request.contextual_audit
    assert not request.generated_image.enabled


def test_benchmark_never_overwrites_an_existing_artifact(tmp_path):
    marker = tmp_path / "report.json"
    marker.write_text("keep this result", encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main(["--output-dir", str(tmp_path)])
    assert error.value.code == 2
    assert marker.read_text(encoding="utf-8") == "keep this result"
    assert list(tmp_path.iterdir()) == [Path(marker)]
