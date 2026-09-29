"""Единый файловый pipeline: профиль → история → варианты → аудит → экспорт."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
import tomllib
from pathlib import Path
from typing import Callable
from uuid import uuid4

from exposlides.cli import CONTENT_ERROR_CODES
from exposlides.design_audit import apply_fixes, audit_deck, audit_saved_pptx
from exposlides.design_content import (
    extractive_plan,
    source_excerpts,
    story_reference_issues,
    validate_story,
)
from exposlides.design_diversity import variant_diversity
from exposlides.design_export import export_deck
from exposlides.design_layout import create_variants, story_layout_issues
from exposlides.design_models import (
    AuditIssue,
    AuditReport,
    ContentPlan,
    DeckPlan,
    DesignRequest,
    TemplateProfile,
)
from exposlides.design_repetition import image_identity, repeated_content_images
from exposlides.preview import PreviewRenderer
from exposlides.template_catalog import prepare_template_catalog, resolve_template_catalog
from exposlides.template_profile import profile_from_json

ROOT = Path(__file__).resolve().parents[1]

STORY_ERRORS = {
    "invalid_response": "Модель вернула план в неподходящем формате. Попробуйте ещё раз.",
    "content_validation": (
        "План не прошёл проверку фактов и полноты исходных материалов. "
        "Попробуйте ещё раз или уточните материалы."
    ),
    "timeout": "Модель не успела составить план. Попробуйте ещё раз.",
    "auth": (
        "Нет доступа к модели. Проверьте ключ провайдера и права на выбранную модель."
    ),
    "network": (
        "Сервис модели недоступен или ограничил частоту запросов. Попробуйте позже."
    ),
    "configuration": (
        "Настройки модели не подходят для генерации. Проверьте адрес сервиса "
        "и выбранную модель в конфигурации."
    ),
}


class DesignContentError(RuntimeError):
    """Публичная причина сбоя: только фиксированные сообщения, без ответа провайдера."""

    def __init__(self, code: str):
        self.code = code if code in STORY_ERRORS else "unknown"
        super().__init__(STORY_ERRORS.get(self.code, "Не удалось составить план презентации."))


def save_model(path: Path, value) -> None:
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class CancelledError(RuntimeError):
    pass


class DesignPipeline:
    def __init__(self, directory: Path, *, timeout: float = 300,
                 cancel: threading.Event | None = None,
                 progress: Callable[[str], None] | None = None):
        self.directory = directory.resolve()
        self.timeout = timeout
        self.deadline = time.monotonic()+timeout
        self.cancel = cancel or threading.Event()
        self.progress = progress or (lambda stage: None)
        self.renderer = PreviewRenderer(timeout=min(90, timeout), deadline=self.deadline)

    def check(self):
        if self.cancel.is_set():
            raise CancelledError("Задание отменено")
        if time.monotonic() >= self.deadline:
            raise TimeoutError("Превышен общий лимит выполнения задания")

    def command(self, command: list[str], cwd: Path, *, allow_failure: bool = False,
                content_stage: bool = False) -> int:
        self.check()
        with (self.directory / "pipeline.log").open("ab") as log:
            env = os.environ.copy()
            env["LOG_LEVEL"] = "INFO"
            env["LOG_FILE"] = str(self.directory / "content.log")
            process = subprocess.Popen(
                command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=log, start_new_session=os.name == "posix",
            )
            try:
                while process.poll() is None:
                    self.check()
                    self.cancel.wait(0.1)
            except BaseException:
                if process.poll() is None:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait(timeout=5)
                raise
            if process.returncode != 0 and not allow_failure:
                if content_stage:
                    raise DesignContentError(CONTENT_ERROR_CODES.get(process.returncode, "unknown"))
                raise RuntimeError("Этап завершился с ошибкой. Проверьте материалы и настройки модели.")
            return process.returncode

    def plan(self, template: Path, request: DesignRequest) -> tuple[TemplateProfile, ContentPlan]:
        self.directory.mkdir(parents=True, exist_ok=True)
        save_model(self.directory / "request.json", request)
        self.progress("template")
        template = prepare_template_catalog(template, self.directory)
        parsed = self.directory / "template.json"
        self.command([
            sys.executable, "-m", "app.main", "--input-pptx", str(template.resolve()),
            "--output-json", str(parsed.resolve()),
        ], ROOT / "services/parsing-service")
        profile = profile_from_json(json.loads(parsed.read_text(encoding="utf-8")), template)
        save_model(self.directory / "profile.json", profile)
        self.progress("story")
        if request.mode == "extractive":
            story = extractive_plan(request, source_excerpts(request.script))
        else:
            self.command([
                sys.executable, "-m", "app.design_main", "--request",
                str((self.directory / "request.json").resolve()), "--output",
                str((self.directory / "story.json").resolve()),
                "--profile", str((self.directory / "profile.json").resolve()),
            ], ROOT / "services/content-service", content_stage=True)
            story = ContentPlan.model_validate_json((self.directory / "story.json").read_text(encoding="utf-8"))
        self.validate_plan(request, profile, story)
        save_model(self.directory / "story.json", story)
        versioned_files = [
            *sorted((ROOT / "prompts").rglob("*.md")),
            *sorted((ROOT / "config").rglob("*.toml")),
            *sorted((ROOT / "agents").rglob("*.toml")),
        ]
        prompt_hashes = {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in versioned_files
        }
        workflow = tomllib.loads((ROOT / "agents/designer.toml").read_text(encoding="utf-8"))
        registry = tomllib.loads((ROOT / "config/models.toml").read_text(encoding="utf-8"))
        story_model = None
        if request.mode == "llm":
            metadata = json.loads(
                (self.directory / "story-provenance.json").read_text(encoding="utf-8")
            )
            story_model = {key: metadata[key] for key in (
                "workflow_id", "workflow_version", "role", "model", "endpoint_model",
                "license", "parameters_billions", "registry_version", "prompt_sha256",
            )}
        save_model(self.directory / "manifest.json", {
            "schema_version": "1.0", "template_sha256": profile.template_sha256,
            "source_sha256": hashlib.sha256(request.script.encode()).hexdigest(),
            "request_sha256": hashlib.sha256(
                (self.directory / "request.json").read_bytes()
            ).hexdigest(),
            "story_model": story_model,
            "mode": request.mode, "versioned_resources": prompt_hashes,
            "contextual_audit_requested": request.contextual_audit,
            "workflow": {"id": workflow["id"], "version": workflow["version"]},
            "model_registry_version": registry["registry_version"],
            "declared_models": {key: {field: model[field] for field in (
                "id", "license", "parameters_billions", "live_endpoint_verified",
            )} for key, model in registry["models"].items()},
            "limits": {"seconds": self.timeout, "slides": request.slide_count},
        })
        return profile, story

    def validate_plan(self, request: DesignRequest, profile: TemplateProfile,
                      story: ContentPlan) -> None:
        blocking = story_reference_issues(story, request)
        errors = validate_story(story, request, source_excerpts(request.script))
        errors.extend(story_layout_issues(profile, story, request.datasets))
        if blocking or (errors and request.mode != "llm"):
            raise ValueError("; ".join(blocking or errors))
        # Пересчитываем и при ручной правке: старые замечания не переживают исправление.
        save_model(self.directory / "story-validation.json", {"issues": errors})

    def build(self, template: Path, request: DesignRequest, profile: TemplateProfile,
              story: ContentPlan) -> list[dict]:
        # Сохранённый профиль мог быть создан старой версией анализатора.
        # Пересчитываем слоты до валидации и выбора макетов, а не пропускаем
        # отсутствующие текстовые фигуры при сборке (это потеряло бы контент).
        parsed = self.directory / "template.json"
        if parsed.is_file():
            source = resolve_template_catalog(template, self.directory, profile.template_sha256)
            if hashlib.sha256(source.read_bytes()).hexdigest() != profile.template_sha256:
                raise ValueError("Шаблон не соответствует сохранённому профилю")
            # Старый parser помечал картинки-placeholder как обычные фигуры.
            # Повторный разбор восстанавливает и текстовые, и фотообласти.
            self.command([
                sys.executable, "-m", "app.main", "--input-pptx", str(source.resolve()),
                "--output-json", str(parsed.resolve()),
            ], ROOT / "services/parsing-service")
            profile = profile_from_json(json.loads(parsed.read_text(encoding="utf-8")), source)
            save_model(self.directory / "profile.json", profile)
        self.validate_plan(request, profile, story)
        save_model(self.directory / "story.json", story)
        diversity = variant_diversity(profile, create_variants(profile, story, request.datasets))
        save_model(self.directory / "variant-diversity.json", diversity)
        if not diversity["sufficient"]:
            message = "В шаблоне недостаточно композиций: варианты могут быть похожи."
            if request.mode != "llm":
                raise ValueError(
                    "В шаблоне недостаточно подходящих композиций для трёх различимых версий. "
                    "Добавьте разные макеты или сократите текст; одинаковые варианты не опубликованы."
                )
            validation = self.directory / "story-validation.json"
            findings = json.loads(validation.read_text(encoding="utf-8"))
            findings["issues"].append(message)
            save_model(validation, findings)
        generated_images = self.generate_images(request, profile, story)
        variants = create_variants(
            profile, story, request.datasets, generated_images=generated_images,
            template_images_only=not request.generated_image.enabled,
        )
        results = []
        for plan in variants:
            self.check()
            results.append(self.publish_variant(template, profile, plan, revision=1))
            save_model(self.directory / "variants.json", results)
        return results

    def generate_images(self, request: DesignRequest, profile: TemplateProfile,
                        story: ContentPlan) -> dict[str, Path | list[Path]]:
        specification = request.generated_image
        if specification.enabled:
            image = self.generate_image(request, profile, story)
            return {specification.slide_id or story.slides[0].id: image} if image else {}
        if not specification.auto or os.environ.get("IMAGE_GENERATION_ENABLED", "false").lower() != "true":
            return {}
        # Сначала композиции шаблона; изображение не диктует выбор макета.
        variants = create_variants(profile, story, request.datasets)
        patterns = {pattern.source_slide_index: pattern for pattern in profile.patterns}
        image_counts = {}
        for plan in variants:
            for slide in plan.slides:
                pattern = patterns[slide.source_slide_index]
                count = len(pattern.replaceable_images) + len(pattern.layout_images)
                if count and all(block.source_shape_id is not None for block in slide.blocks):
                    image_counts[slide.story_slide_id] = max(
                        image_counts.get(slide.story_slide_id, 0), count,
                    )
        candidates = story.slides[1:] if len(story.slides) > 1 else story.slides
        targets = [slide for slide in candidates if slide.id in image_counts and not slide.visual]
        if not targets:
            return {}
        images, bindings = [], {}
        for slide in targets:
            for slot in range(image_counts[slide.id]):
                key = slide.id if slot == 0 else "image-" + hashlib.sha256(
                    f"{slide.id}:{slot}".encode("utf-8"),
                ).hexdigest()[:32]
                if key in bindings or (slot and key in {s.id for s in story.slides}):
                    raise ValueError("Конфликт идентификаторов иллюстраций")
                payload = specification.model_dump(mode="json", exclude={"slide_id", "auto"})
                prompt = "\n".join([slide.title, *slide.paragraphs])[:3000]
                if image_counts[slide.id] > 1:
                    prompt += (f"\nИллюстрация {slot + 1} из {image_counts[slide.id]}: "
                               + (slide.paragraphs[slot % len(slide.paragraphs)])[:400]
                               + " Покажи отдельный аспект темы, с другой сценой и композицией.")
                payload.update(
                    enabled=True, prompt=prompt, source_ids=slide.source_ids,
                    seed=(specification.seed + len(images)) % (2**32),
                    palette=specification.palette or profile.patterns[0].palette[:8],
                )
                images.append({"slide_id": key, "request": payload})
                bindings[key] = slide
        if len(images) > 50:
            raise ValueError("В презентации больше 50 фотообластей: сократите число слайдов")
        budget = min(90, self.deadline - time.monotonic() - 30)
        if budget <= 0:
            raise TimeoutError("Недостаточно времени для иллюстраций и сборки")
        input_path, output_path = self.directory / "images-request.json", self.directory / "images-result.json"
        save_model(input_path, {"images": images})
        self.progress("illustration")
        self.command([
            sys.executable, "-m", "app.design_images", "--request", str(input_path.resolve()),
            "--output", str(output_path.resolve()), "--timeout", str(budget),
        ], ROOT / "services/content-service", allow_failure=True)
        if not output_path.is_file():
            raise RuntimeError("Генератор не вернул набор иллюстраций")
        result = json.loads(output_path.read_text(encoding="utf-8"))
        entries = result.get("images", {})
        if result.get("status") != "completed" or set(entries) != set(bindings):
            raise RuntimeError("Не удалось создать разные иллюстрации для всех слайдов")
        paths = {slide.id: [] for slide in targets}
        digests = set()
        for key, slide in bindings.items():
            item = entries[key]
            path = Path(item["path"]).resolve()
            if (item.get("status") != "completed" or not path.is_relative_to(self.directory.resolve())
                    or not path.is_file()):
                raise ValueError("Некорректный путь иллюстрации")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            identity = image_identity(path.read_bytes())
            if digest != item.get("sha256") or identity in digests:
                raise ValueError("Иллюстрации повреждены или повторяются")
            if item.get("source_ids") != slide.source_ids:
                raise ValueError("Иллюстрация привязана к другим материалам")
            paths[slide.id].append(path)
            digests.add(identity)
        return {key: values[0] if len(values) == 1 else values for key, values in paths.items()}

    def generate_image(self, request: DesignRequest, profile: TemplateProfile,
                       story: ContentPlan) -> Path | None:
        specification = request.generated_image
        if (not specification.enabled and specification.auto
                and os.environ.get("IMAGE_GENERATION_ENABLED", "false").lower() == "true"):
            target = next((slide for slide in story.slides[1:] if not slide.visual), story.slides[0])
            specification = specification.model_copy(update={
                "enabled": True, "slide_id": target.id,
                "prompt": "\n".join([target.title, *target.paragraphs])[:3500],
                "source_ids": target.source_ids,
            })
        self.image_slide_id = specification.slide_id
        if not specification.enabled:
            return None
        if specification.slide_id and specification.slide_id not in {s.id for s in story.slides}:
            raise ValueError("Слайд для иллюстрации отсутствует в плане")
        known = {e.id for e in source_excerpts(request.script)}
        if set(specification.source_ids)-known:
            raise ValueError("Иллюстрация ссылается на неизвестные материалы")
        payload = specification.model_dump(mode="json", exclude={"slide_id", "auto"})
        if not payload["palette"]:
            payload["palette"] = profile.patterns[0].palette[:8]
        input_path = self.directory / "image-request.json"
        output_path = self.directory / "image-result.json"
        save_model(input_path, payload)
        self.progress("illustration")
        self.command([
            sys.executable, "-m", "app.design_image", "--request", str(input_path.resolve()),
            "--output", str(output_path.resolve()),
        ], ROOT / "services/content-service", allow_failure=True)
        if not output_path.is_file():
            raise RuntimeError("Генератор иллюстраций не вернул результат")
        result = json.loads(output_path.read_text(encoding="utf-8"))
        if result.get("status") != "completed":
            raise RuntimeError("Не удалось создать иллюстрацию. Проверьте настройки image endpoint")
        image = Path(result["path"]).resolve()
        if not image.is_relative_to(self.directory.resolve()) or not image.is_file():
            raise ValueError("Некорректный путь сгенерированного изображения")
        if hashlib.sha256(image.read_bytes()).hexdigest() != result.get("sha256"):
            raise ValueError("Не совпадает контрольная сумма иллюстрации")
        return image

    def publish_variant(self, template: Path, profile: TemplateProfile,
                        plan: DeckPlan, *, revision: int) -> dict:
        from exposlides.design_builder import build_deck

        self.check()
        template = resolve_template_catalog(template, self.directory, profile.template_sha256)
        self.progress(f"building:{plan.variant_id}")
        final = self.directory / "variants" / plan.variant_id / str(revision)
        if final.exists():
            raise ValueError("Версия уже существует")
        staging = final.with_name(f".pending-{uuid4().hex}")
        staging.mkdir(parents=True)
        try:
            output = staging / "presentation.pptx"
            build_deck(template, plan, output)
            if repeated_content_images(output, plan, profile):
                raise ValueError(
                    "В презентации повторяются содержательные иллюстрации. "
                    "Нужны разные изображения для фотообластей; результат не опубликован."
                )
            self.check()
            self.progress(f"rendering:{plan.variant_id}")
            self.renderer.timeout = max(1, min(90, self.deadline-time.monotonic()))
            exports = export_deck(output, plan, staging, self.renderer)
            self.check()
            self.progress(f"auditing:{plan.variant_id}")
            audit = audit_deck(plan, profile)
            validation_file = self.directory / "story-validation.json"
            if validation_file.is_file():
                findings = json.loads(validation_file.read_text(encoding="utf-8"))["issues"]
                audit.issues.extend(AuditIssue(
                    id=f"story-validation-{index}", rule="story_validation", severity="error",
                    slide_id="", message=message,
                ) for index, message in enumerate(findings, 1))
            saved_audit = audit_saved_pptx(output, template, plan, profile)
            audit.issues.extend(saved_audit.issues)
            audit.checks.extend(saved_audit.checks)
            contextual = self.contextual_audit(plan, staging, exports)
            audit.issues.extend(contextual.issues)
            audit.checks.extend(contextual.checks)
            audit.contextual_status = contextual.contextual_status
            audit.limitations.extend(contextual.limitations)
            save_model(staging / "plan.json", plan)
            save_model(staging / "audit.json", audit)
            save_model(staging / "exports.json", exports)
            self.check()
            staging.replace(final)
        finally:
            if staging.exists():
                import shutil
                shutil.rmtree(staging)
        return self.variant_info(plan.variant_id, revision)

    def contextual_audit(self, plan: DeckPlan, staging: Path, exports: dict) -> AuditReport:
        request_file = self.directory / "request.json"
        if not request_file.is_file():
            return AuditReport(limitations=["Материалы контекстуального аудита не найдены."])
        request = DesignRequest.model_validate_json(request_file.read_text(encoding="utf-8"))
        if not request.contextual_audit:
            return AuditReport(limitations=[
                "Контекстуальный аудит отключён. Для него нужен endpoint с поддержкой изображений.",
            ])
        excerpts = {e.id: e.text for e in source_excerpts(request.script)}
        slides = []
        for slide, image in zip(plan.slides, exports["images"], strict=True):
            source_ids = list(dict.fromkeys(key for b in slide.blocks for key in b.source_ids))
            text = "\n".join("\n".join([b.text, *b.items]) for b in slide.blocks)
            source = "\n".join(excerpts[key] for key in source_ids if key in excerpts)
            for block in slide.blocks:
                if block.dataset_id:
                    dataset = next(d for d in plan.datasets if d.id == block.dataset_id)
                    source += "\n" + dataset.model_dump_json()
            slides.append({
                "id": slide.id, "image_path": str((staging / image).resolve()),
                "text": text, "source_text": source, "source_ids": source_ids,
            })
        payload = staging / "contextual-request.json"
        output = staging / "contextual-audit.json"
        save_model(payload, {
            "enabled": True, "slides": slides,
            "timeout_seconds": max(1, min(45, self.deadline-time.monotonic()-5)),
            "concurrency": 3,
        })
        self.command([
            sys.executable, "-m", "app.design_audit", "--request", str(payload.resolve()),
            "--output", str(output.resolve()),
        ], ROOT / "services/content-service", allow_failure=True)
        if output.is_file():
            return AuditReport.model_validate_json(output.read_text(encoding="utf-8"))
        return AuditReport(contextual_status="failed", limitations=[
            "Контекстуальный аудит не завершился: проверьте модель и поддержку изображений.",
        ])

    def variant_info(self, variant: str, revision: int) -> dict:
        directory = self.directory / "variants" / variant / str(revision)
        plan = DeckPlan.model_validate_json((directory / "plan.json").read_text(encoding="utf-8"))
        audit = AuditReport.model_validate_json((directory / "audit.json").read_text(encoding="utf-8"))
        exports = json.loads((directory / "exports.json").read_text(encoding="utf-8"))
        indices = {s.id: i for i, s in enumerate(plan.slides, 1)}
        issues = []
        for issue in audit.issues:
            box = issue.box
            issues.append(issue.model_dump(mode="json") | {
                "slide_index": indices.get(issue.slide_id), "rule_id": issue.rule,
                "fix_available": issue.fix != "none",
                "bbox": ({"x": box.left/plan.width, "y": box.top/plan.height,
                          "width": box.width/plan.width, "height": box.height/plan.height}
                         if box else None),
            })
        base = f"variants/{variant}/files/{revision}/"
        return {
            "id": variant, "name": plan.name, "description": plan.description,
            "revision": revision, "issues": issues, "audit": audit.model_dump(mode="json"),
            "preview_urls": [base+p for p in exports["images"]],
            "exports": {key: base+name for key, name in exports["files"].items()},
            "html_visual": exports["html_visual"], "slide_count": len(plan.slides),
        }

    def fix(self, template: Path, profile: TemplateProfile, variant: str, revision: int,
            issue_ids: list[str]) -> dict:
        directory = self.directory / "variants" / variant / str(revision)
        plan = DeckPlan.model_validate_json((directory / "plan.json").read_text(encoding="utf-8"))
        report = AuditReport.model_validate_json((directory / "audit.json").read_text(encoding="utf-8"))
        updated = apply_fixes(plan, profile, report, issue_ids)
        return self.publish_variant(template, profile, updated, revision=revision+1)

    def close(self):
        self.renderer.close()
