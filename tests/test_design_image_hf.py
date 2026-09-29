import asyncio
import base64
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
from PIL import Image

SERVICE = Path(__file__).resolve().parents[1] / "services/content-service"


def test_hf_image_reuses_llm_key_and_saves_provenance(service_importer, monkeypatch, tmp_path):
    module = service_importer(SERVICE, "app.design_image")
    monkeypatch.setattr(module.settings, "llm_api_key", "hf_test")
    monkeypatch.setattr(module.settings, "llm_base_url", "https://router.huggingface.co/v1")
    monkeypatch.setattr(module.settings, "image_api_key", "")
    monkeypatch.setattr(module.settings, "image_api_url", module.IMAGE_ENDPOINT)
    monkeypatch.setattr(module.settings, "image_model", "Tongyi-MAI/Z-Image-Turbo")
    image = io.BytesIO()
    Image.new("RGB", (512, 512), "blue").save(image, format="PNG")

    def handler(request):
        assert request.headers["authorization"] == "Bearer hf_test"
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {
                "content": json.dumps({"scene": "An editorial illustration of a cloud above servers."}),
            }}]})
        assert str(request.url) == module.IMAGE_ENDPOINT
        assert json.loads(request.content)["sync_mode"]
        return httpx.Response(200, json={"images": [{
            "url": "data:image/png;base64," + base64.b64encode(image.getvalue()).decode(),
        }]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await module.generate_image(
                module.ImageRequest(enabled=True, prompt="Облачная инфраструктура"),
                tmp_path / "result.json", client,
            )
    result = asyncio.run(run())
    assert result.status == "completed"
    assert result.model == "Tongyi-MAI/Z-Image-Turbo"
    assert Path(result.path).read_bytes() == image.getvalue()
    assert "hf_test" not in result.model_dump_json()


def test_capabilities_accept_same_hf_key(service_importer):
    module = service_importer(SERVICE, "app.design_capabilities")
    config = SimpleNamespace(
        llm_api_key="hf_test", llm_base_url="https://router.huggingface.co/v1",
        llm_fast_model="Qwen/Qwen3.8-27B:deepinfra", image_api_key="",
        image_api_url=module.HF_IMAGE_ENDPOINT, image_model="Tongyi-MAI/Z-Image-Turbo",
    )
    assert module.capabilities(config)["generated_image"]
    config.image_api_url = "https://other.example/images"
    assert not module.capabilities(config)["generated_image"]


def test_automatic_illustration_is_tied_to_story_and_can_be_disabled(tmp_path, monkeypatch):
    from exposlides.design_models import ContentPlan, DesignRequest, StorySlide
    from exposlides.design_pipeline import DesignPipeline
    from tests.test_template_design import _profile

    request = DesignRequest(script="Команда развивает продукт.", slide_count=2)
    story = ContentPlan(title="Продукт", slides=[
        StorySlide(id="cover", title="Продукт", paragraphs=[request.script], source_ids=["source-1"]),
        StorySlide(id="body", title="Работа команды", paragraphs=[request.script],
                   source_ids=["source-1"]),
    ])
    profile = _profile(tmp_path)
    pipeline = DesignPipeline(tmp_path)
    calls = []
    image = tmp_path / "test.png"
    image.write_bytes(b"test")

    def command(*args, **kwargs):
        calls.append(json.loads((tmp_path / "image-request.json").read_text()))
        (tmp_path / "image-result.json").write_text(json.dumps({
            "status": "completed", "path": str(image),
            "sha256": hashlib.sha256(b"test").hexdigest(),
        }))
    monkeypatch.setattr(pipeline, "command", command)
    monkeypatch.setenv("IMAGE_GENERATION_ENABLED", "true")
    assert pipeline.generate_image(request, profile, story) == image
    assert pipeline.image_slide_id == "body"
    assert "Работа команды" in calls[0]["prompt"]
    assert "auto" not in calls[0]
    assert not request.generated_image.enabled
    request.generated_image.auto = False
    assert pipeline.generate_image(request, profile, story) is None
    assert len(calls) == 1
