from pathlib import Path
from types import SimpleNamespace

CONTENT_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "services" / "content-service"


def _config(**changes):
    return SimpleNamespace(**({
        "llm_api_key": "hf_test_key", "llm_base_url": "https://router.huggingface.co/v1",
        "llm_fast_model": "Qwen/Qwen3.8-27B:deepinfra", "image_api_url": "",
        "image_api_key": "", "image_model": "Tongyi-MAI/Z-Image-Turbo",
    } | changes))


def test_capabilities_exposes_only_booleans_for_configured_models(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_capabilities")
    result = module.capabilities(_config(
        image_api_url="https://images.example.test/generate", image_api_key="private-test-key",
    ))
    assert result == {"generated_image": True, "contextual_audit": True, "story": True}
    assert all(isinstance(value, bool) for value in result.values())


def test_missing_credentials_hide_model_actions(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_capabilities")
    assert module.capabilities(_config(llm_api_key="")) == {
        "generated_image": False, "contextual_audit": False, "story": False,
    }


def test_unregistered_models_are_not_advertised(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_capabilities")
    assert module.capabilities(_config(
        llm_fast_model="closed-model", image_model="black-forest-labs/FLUX.1-dev",
        image_api_key="private-test-key", image_api_url="https://images.example.test",
    )) == {"generated_image": False, "contextual_audit": False, "story": False}


def test_invalid_provider_token_is_not_advertised(service_importer):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_capabilities")
    assert not module.capabilities(_config(llm_api_key="wrong-prefix"))["story"]


def test_cli_outputs_only_json_flags(service_importer, monkeypatch, capsys):
    module = service_importer(CONTENT_SERVICE_ROOT, "app.design_capabilities")
    monkeypatch.setattr(module, "capabilities", lambda: {
        "generated_image": False, "contextual_audit": True, "story": True,
    })
    assert module.main() == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == (
        '{"generated_image": false, "contextual_audit": true, "story": true}'
    )
    assert captured.err == ""
