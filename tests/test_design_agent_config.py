from copy import deepcopy
from pathlib import Path

import pytest

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


@pytest.mark.parametrize("role", ["story", "contextual_auditor", "image_illustrator"])
def test_versioned_role_has_external_prompt_and_approved_model(service_importer, role):
    config = service_importer(CONTENT_SERVICE_ROOT, "app.design_config")
    model = config.model_for_role(role)
    assert model["license"] in {"Apache-2.0", "MIT"}
    assert model["parameters_billions"] <= (20 if role == "image_illustrator" else 35)
    assert "{payload}" in config.role_prompt(role)
    metadata = config.role_metadata(role)
    assert metadata["workflow_version"] == "1.2.0"
    assert len(metadata["prompt_sha256"]) == 64


def test_unregistered_language_model_is_not_silently_substituted(service_importer):
    config = service_importer(CONTENT_SERVICE_ROOT, "app.design_config")
    with pytest.raises(ValueError, match="реестре"):
        config.model_for_role("story", "closed-or-unknown-model")


@pytest.mark.parametrize("field,value", [
    ("license", "non-commercial"), ("parameters_billions", 21), ("tasks", ["text"]),
])
def test_image_role_rejects_registry_entries_outside_competition_constraints(
    service_importer, monkeypatch, field, value,
):
    config = service_importer(CONTENT_SERVICE_ROOT, "app.design_config")
    workflow, registry = deepcopy(config._configs())
    registry["models"][workflow["roles"]["image_illustrator"]["model"]][field] = value
    monkeypatch.setattr(config, "_configs", lambda: (workflow, registry))
    with pytest.raises(ValueError):
        config.model_for_role("image_illustrator")


@pytest.mark.parametrize('role,timeout,allowed', [
    ('story', 240, True), ('story', 241, False),
    ('contextual_auditor', 181, False), ('image_illustrator', 181, False),
])
def test_story_budget_keeps_a_reserve_inside_total_job_limit(
    service_importer, monkeypatch, role, timeout, allowed,
):
    config = service_importer(CONTENT_SERVICE_ROOT, 'app.design_config')
    workflow, registry = deepcopy(config._configs())
    workflow['roles'][role]['timeout_seconds'] = timeout
    monkeypatch.setattr(config, '_configs', lambda: (workflow, registry))
    if allowed:
        assert config.role_config(role)['timeout_seconds'] <= 240
    else:
        with pytest.raises(ValueError):
            config.role_config(role)


def test_named_repair_prompts_share_role_path_restrictions(service_importer, monkeypatch):
    config = service_importer(CONTENT_SERVICE_ROOT, "app.design_config")
    names = {"correction", "correction_patch", "correction_full",
             "repair_requirements", "editorial_repair"}
    assert set(config.role_config("story")["prompts"]) == names
    for name in names:
        assert config.role_prompt("story", name).strip()
    workflow, registry = deepcopy(config._configs())
    workflow["roles"]["story"]["prompts"]["correction"] = "../outside.md"
    monkeypatch.setattr(config, "_configs", lambda: (workflow, registry))
    with pytest.raises(ValueError, match="внутри репозитория"):
        config.role_prompt("story", "correction")
