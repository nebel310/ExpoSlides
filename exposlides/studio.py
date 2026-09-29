"""Локальная студия: проверяемый план, три варианта, выбор правок и экспорт."""

from __future__ import annotations

import argparse
import base64
import binascii
import errno
import hmac
import json
import mimetypes
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exposlides.design_content import source_excerpts, story_reference_issues, validate_story
from exposlides.design_models import ContentPlan, DesignRequest, TemplateProfile
from exposlides.design_pipeline import (
    ROOT,
    CancelledError,
    DesignContentError,
    DesignPipeline,
    save_model,
)
from exposlides.template_compat import prepare_template
from exposlides.web import (
    EXAMPLE_SCRIPT,
    MAX_REQUEST_BYTES,
    MAX_TEMPLATE_BYTES,
    APIError,
    make_example,
)

STATIC = Path(__file__).parent / "studio_static"
IDENTIFIER = re.compile(r"^[a-f0-9]{32}$")
VARIANTS = {"story", "evidence", "cards"}


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_id: str
    request: DesignRequest


class BuildInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    story: ContentPlan


class FixInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    issue_ids: list[str] = Field(min_length=1, max_length=100)


class Studio:
    """Ограниченная очередь и атомарные метаданные; без неограниченного запуска потоков."""

    MAX_ACTIVE_JOBS = 8

    def __init__(self, root: Path, *, workers: int = 2, pipeline_factory=DesignPipeline):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "templates").mkdir(exist_ok=True)
        (self.root / "jobs").mkdir(exist_ok=True)
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.render_lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="exposlides")
        self.jobs = {}
        self.cancels = {}
        self.pipelines = {}
        self.pipeline_factory = pipeline_factory
        self.closed = False
        self.example_ids = {}
        self.capability_flags = None
        for path in (self.root / "jobs").glob("*/job.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if not IDENTIFIER.fullmatch(job["id"]):
                    continue
                if job["status"] in {"queued", "running", "cancelling"}:
                    if job.get("operation") in {"build", "generate"} and not job.get("variants"):
                        try:
                            published = json.loads(
                                (path.parent / "variants.json").read_text(encoding="utf-8"),
                            )
                            if isinstance(published, list) and all(
                                isinstance(variant, dict)
                                and variant.get("id") in VARIANTS
                                and type(variant.get("revision")) is int
                                and variant["revision"] >= 1
                                and isinstance(variant.get("exports"), dict)
                                and all(isinstance(value, str)
                                        for value in variant["exports"].values())
                                and isinstance(variant.get("preview_urls"), list)
                                and all(isinstance(value, str)
                                        for value in variant["preview_urls"])
                                for variant in published
                            ):
                                job["variants"] = published
                        except (ValueError, OSError):
                            pass
                    recoverable = job.get("operation") == "fix" and bool(job.get("variants"))
                    job.update(status="completed" if recoverable else "failed",
                               error="Сервер перезапущен во время выполнения")
                    save_model(path, job)
                self.jobs[job["id"]] = job
            except (ValueError, KeyError, OSError):
                continue

    def directory(self, job_id):
        if not IDENTIFIER.fullmatch(job_id):
            raise HTTPException(404, "Задание не найдено")
        return self.root / "jobs" / job_id

    def _save(self, job):
        save_model(self.directory(job["id"]) / "job.json", job)

    def get(self, job_id, owner_id: str | None = None):
        with self.lock:
            if job_id not in self.jobs:
                raise HTTPException(404, "Задание не найдено")
            if owner_id is not None and self.jobs[job_id].get("_owner_id") != owner_id:
                raise HTTPException(404, "Задание не найдено")
            job = json.loads(json.dumps(self.jobs[job_id]))
        job.pop("_owner_id", None)
        if job.get("template"):
            job["template"].pop("_owner_id", None)
        for variant in job.get("variants", []):
            prefix = f"/api/design/jobs/{job_id}/"
            variant["preview_urls"] = [prefix+p for p in variant["preview_urls"]]
            variant["exports"] = {k: prefix+p for k, p in variant["exports"].items()}
        return job

    def template(self, template_id, owner_id: str | None = None):
        if not IDENTIFIER.fullmatch(template_id):
            raise HTTPException(404, "Шаблон не найден")
        path = self.root / "templates" / f"{template_id}.pptx"
        if not path.is_file():
            raise HTTPException(404, "Шаблон не найден")
        if owner_id is not None:
            metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
            if metadata.get("_owner_id") != owner_id:
                raise HTTPException(404, "Шаблон не найден")
        return path

    def _require_disk_space(self, extra_bytes: int = 0) -> None:
        if shutil.disk_usage(self.root).free < 256 * 1024 * 1024 + extra_bytes:
            raise HTTPException(507, "На сервере недостаточно места. Материалы сохранены в форме; "
                                "повторите попытку после освобождения места.")

    def add_template(self, name: str, data: bytes, owner_id: str | None = None):
        if len(data) > MAX_TEMPLATE_BYTES:
            raise HTTPException(413, "Шаблон превышает 25 МБ")
        self._require_disk_space(len(data) * 3)
        try:
            working, metadata = prepare_template(data, name)
        except (ValueError, APIError) as error:
            raise HTTPException(422, str(error)) from error
        template_id = uuid4().hex
        path = self.root / "templates" / f"{template_id}.pptx"
        path.write_bytes(data)
        if working != data:
            path.with_suffix(".compatible.pptx").write_bytes(working)
        metadata["id"] = template_id
        metadata["_owner_id"] = owner_id
        save_model(path.with_suffix(".json"), metadata)
        return {key: value for key, value in metadata.items() if key != "_owner_id"}

    def example(self, owner_id: str):
        with self.lock:
            if owner_id not in self.example_ids:
                metadata = self.add_template("Квартальный обзор.pptx", make_example(), owner_id)
                self.example_ids[owner_id] = metadata["id"]
            else:
                path = self.template(self.example_ids[owner_id], owner_id).with_suffix(".json")
                metadata = json.loads(path.read_text(encoding="utf-8"))
                metadata.pop("_owner_id", None)
        return {"template_id": metadata["id"], "script": EXAMPLE_SCRIPT, "template": metadata}

    def capabilities(self, *, refresh: bool = False):
        with self.lock:
            if refresh or self.capability_flags is None:
                flags = {"generated_image": False, "contextual_audit": False, "story": False}
                try:
                    result = subprocess.run(
                        [sys.executable, "-m", "app.design_capabilities"],
                        cwd=ROOT / "services/content-service", capture_output=True,
                        timeout=5, check=True,
                    )
                    payload = json.loads(result.stdout)
                    flags = {key: payload.get(key) is True for key in flags}
                except (subprocess.SubprocessError, ValueError, OSError):
                    pass
                self.capability_flags = flags
            return dict(self.capability_flags)

    def start(self, payload: PlanInput, owner_id: str | None = None, *, auto_build: bool = False):
        template = self.template(payload.template_id, owner_id)
        self._require_disk_space()
        if payload.request.mode == "llm" and not self.capabilities(refresh=True)["story"]:
            if auto_build:
                raise HTTPException(422, "Сервис генерации временно недоступен. Попробуйте позже.")
            raise HTTPException(422, (
                "Модель не подключена или её настройки не подходят для генерации. "
                "Настройте доступ к модели либо выберите «Проверочный · без модели». "
                "Материалы сохранены в форме."
            ))
        with self.lock:
            self._require_queue_capacity()
            identifier = uuid4().hex
            directory = self.directory(identifier)
            directory.mkdir()
            compatible = template.with_suffix(".compatible.pptx")
            shutil.copyfile(
                compatible if compatible.is_file() else template, directory / "template.pptx",
            )
            save_model(directory / "request.json", payload.request)
            job = {"id": identifier, "template_id": payload.template_id, "_owner_id": owner_id,
                   "created_at": time.time(),
                   "status": "queued", "stage": "template", "active_seconds": 0,
                   "variants": [], "error": None,
                   "request": payload.request.model_dump(mode="json"),
                   "template": json.loads(template.with_suffix(".json").read_text(encoding="utf-8"))}
            self.jobs[identifier] = job
            self._save(job)
            self._submit(identifier, "generate" if auto_build else "plan", payload.request)
        return self.get(identifier)

    def build(self, job_id, story):
        with self.lock:
            self.get(job_id)
            job = self.jobs[job_id]
            if job["status"] != "awaiting_review":
                raise HTTPException(409, "План уже запущен или ещё не готов")
            request = DesignRequest.model_validate_json(
                (self.directory(job_id) / "request.json").read_text(encoding="utf-8"),
            )
            errors = story_reference_issues(story, request)
            if request.mode != "llm":
                errors.extend(validate_story(story, request, source_excerpts(request.script)))
            if errors:
                raise HTTPException(422, "; ".join(errors))
            self._require_disk_space()
            self._require_queue_capacity()
            job.update(status="queued", stage="building", error=None)
            self._save(job)
            self._submit(job_id, "build", story)
        return self.get(job_id)

    def fix(self, job_id, variant, payload):
        with self.lock:
            self.get(job_id)
            job = self.jobs[job_id]
            if job["status"] != "completed":
                raise HTTPException(409, "Дождитесь завершения текущей операции")
            current = next((v for v in job["variants"] if v["id"] == variant), None)
            if current is None or current["revision"] != payload.revision:
                raise HTTPException(409, "Версия изменилась. Обновите результат")
            self._require_disk_space()
            self._require_queue_capacity()
            job.update(status="queued", stage="fixing", error=None)
            self._save(job)
            self._submit(job_id, "fix", (variant, payload))
        return self.get(job_id)

    def _require_queue_capacity(self):
        """Вызывать под self.lock до изменения состояния и постановки операции в очередь."""
        if self.closed:
            raise HTTPException(503, "Студия остановлена")
        active = sum(j["status"] in {"queued", "running", "cancelling"} for j in self.jobs.values())
        if active >= self.MAX_ACTIVE_JOBS:
            raise HTTPException(429, "Очередь заполнена. Дождитесь завершения задания")

    def _submit(self, job_id, operation, payload):
        self.jobs[job_id]["operation"] = operation
        self._save(self.jobs[job_id])
        cancel = threading.Event()
        self.cancels[job_id] = cancel
        self.pool.submit(self._run, job_id, operation, payload, cancel)

    def _run(self, job_id, operation, payload, cancel):
        directory = self.directory(job_id)
        started = time.monotonic()
        pipeline = None
        try:
            with self.lock:
                job = self.jobs[job_id]
                if cancel.is_set():
                    raise CancelledError()
                job["status"] = "running"
                self._save(job)
                remaining = 300-job["active_seconds"] if operation != "fix" else 120
            if remaining <= 0:
                raise TimeoutError("Общий лимит генерации исчерпан")

            def progress(stage):
                with self.lock:
                    self.jobs[job_id]["stage"] = stage
                    self._save(self.jobs[job_id])

            pipeline = self.pipeline_factory(directory, timeout=remaining, cancel=cancel, progress=progress)
            with self.lock:
                self.pipelines[job_id] = pipeline
            template = directory / "template.pptx"
            if operation in {"plan", "generate"}:
                profile, story = pipeline.plan(template, payload)
                update = {"profile": profile.model_dump(mode="json"),
                          "story": story.model_dump(mode="json"), "status": "awaiting_review"}
                if operation == "generate":
                    pipeline.check()
                    errors = story_reference_issues(story, payload)
                    if payload.mode != "llm":
                        errors.extend(validate_story(story, payload, source_excerpts(payload.script)))
                    if errors:
                        raise ValueError("; ".join(errors))
                    # План доступен в истории даже при последующей ошибке сборки.
                    with self.lock:
                        self.jobs[job_id].update(
                            profile=update["profile"], story=update["story"], stage="building",
                        )
                        self._save(self.jobs[job_id])
            if operation != "plan":
                if operation != "generate":
                    profile = TemplateProfile.model_validate_json((directory / "profile.json").read_text(encoding="utf-8"))
                # Конвертеры сериализованы: параллельная генерация не создаёт десятки офисных процессов.
                while not self.render_lock.acquire(timeout=0.2):
                    pipeline.check()
                try:
                    if operation in {"build", "generate"}:
                        if operation == "generate":
                            pipeline.check()
                            request, content = payload, story
                        else:
                            request = DesignRequest.model_validate_json((directory / "request.json").read_text(encoding="utf-8"))
                            content = payload
                        variants = pipeline.build(template, request, profile, content)
                        update = {"variants": variants, "story": content.model_dump(mode="json"),
                                  "status": "completed"}
                    else:
                        variant, fixing = payload
                        updated = pipeline.fix(template, profile, variant, fixing.revision, fixing.issue_ids)
                        with self.lock:
                            variants = [updated if v["id"] == variant else v for v in self.jobs[job_id]["variants"]]
                        update = {"variants": variants, "status": "completed"}
                finally:
                    self.render_lock.release()
            with self.lock:
                if cancel.is_set() and operation == "plan":
                    raise CancelledError()
                self.jobs[job_id].update(update, stage="review", error=None)
        except CancelledError:
            with self.lock:
                recoverable = operation == "fix" and bool(self.jobs[job_id].get("variants"))
                self.jobs[job_id].update(status="completed" if recoverable else "cancelled",
                                        error="Операция отменена; опубликованные версии сохранены")
        except Exception as error:
            with self.lock:
                recoverable = operation == "fix" and bool(self.jobs[job_id].get("variants"))
                message = str(error) if isinstance(
                    error, (ValueError, TimeoutError, DesignContentError),
                ) else (
                    "Не удалось выполнить этап. Проверьте настройки модели, конвертеры и материалы."
                )
                if isinstance(error, OSError) and error.errno == errno.ENOSPC:
                    message = "На сервере закончилось место. Повторите после освобождения места."
                status = "cancelled" if cancel.is_set() else (
                    "completed" if recoverable else "failed"
                )
                self.jobs[job_id].update(status=status, error=(
                    "Задание отменено" if cancel.is_set() else message
                ))
        finally:
            if pipeline is not None:
                pipeline.close()
            with self.lock:
                published = directory / "variants.json"
                if operation in {"build", "generate"} and not self.jobs[job_id].get("variants") and published.is_file():
                    self.jobs[job_id]["variants"] = json.loads(published.read_text(encoding="utf-8"))
                self.jobs[job_id]["active_seconds"] += round(time.monotonic()-started, 3)
                self._save(self.jobs[job_id])
                self.pipelines.pop(job_id, None)
                self.cancels.pop(job_id, None)

    def cancel(self, job_id):
        with self.lock:
            self.get(job_id)
            if job_id not in self.cancels:
                raise HTTPException(409, "Задание уже завершено")
            self.cancels[job_id].set()
            self.jobs[job_id]["status"] = "cancelling"
            pipeline = self.pipelines.get(job_id)
            if pipeline is not None:
                pipeline.close()
            self._save(self.jobs[job_id])
        return self.get(job_id)

    def close(self):
        with self.lock:
            self.closed = True
            for event in self.cancels.values():
                event.set()
            for pipeline in self.pipelines.values():
                pipeline.close()
        self.pool.shutdown(wait=True)


def create_app(root: Path, *, pipeline_factory=DesignPipeline) -> FastAPI:
    studio = Studio(root, pipeline_factory=pipeline_factory)

    @asynccontextmanager
    async def lifespan(app):
        yield
        studio.close()

    app = FastAPI(title="ExpoSlides Studio", lifespan=lifespan)
    app.state.studio = studio

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        hostname = host.split(":")[0]
        if hostname not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"detail": "Недопустимый адрес сервера"}, 403)
        origin = request.headers.get("origin")
        if origin and origin not in {f"http://{host}", f"https://{host}"}:
            return JSONResponse({"detail": "Недопустимый источник запроса"}, 403)
        owner_id = request.cookies.get("studio_owner", "")
        new_owner = not IDENTIFIER.fullmatch(owner_id)
        if new_owner:
            owner_id = secrets.token_hex(16)
        request.state.owner_id = owner_id
        if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
            if not hmac.compare_digest(request.headers.get("x-session-token", ""), studio.token):
                return JSONResponse({"detail": "Сессия устарела. Обновите страницу"}, 403)
            try:
                size = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"detail": "Неверный размер запроса"}, 400)
            if size < 0:
                return JSONResponse({"detail": "Неверный размер запроса"}, 400)
            if size > MAX_REQUEST_BYTES:
                return JSONResponse({"detail": "Запрос слишком большой"}, 413)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > MAX_REQUEST_BYTES:
                    return JSONResponse({"detail": "Запрос слишком большой"}, 413)
            request._body = bytes(body)
        response = await call_next(request)
        if new_owner:
            response.set_cookie("studio_owner", owner_id, httponly=True, samesite="strict",
                                secure=request.url.scheme == "https", max_age=31_536_000)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.get("/api/session")
    def session():
        return {"token": studio.token}

    @app.get("/api/example")
    def example(request: Request):
        return studio.example(request.state.owner_id)

    @app.get("/api/capabilities")
    def capabilities():
        return studio.capabilities(refresh=True)

    @app.post("/api/templates", status_code=201)
    def upload(payload: dict, request: Request):
        name = payload.get("name", "")
        if not isinstance(name, str) or not name.lower().endswith(".pptx"):
            raise HTTPException(422, "Выберите PPTX")
        try:
            data = base64.b64decode(payload.get("data", ""), validate=True)
        except (ValueError, TypeError, binascii.Error) as error:
            raise HTTPException(422, "Некорректный файл") from error
        return studio.add_template(Path(name.replace("\\", "/")).name[:180], data, request.state.owner_id)

    @app.post("/api/design/plan", status_code=202)
    def plan(payload: PlanInput, request: Request):
        return studio.start(payload, request.state.owner_id)

    @app.post("/api/design/generate", status_code=202)
    def generate(payload: PlanInput, request: Request):
        return studio.start(payload, request.state.owner_id, auto_build=True)

    @app.get("/api/design/jobs")
    def jobs(request: Request):
        with studio.lock:
            keys = [key for key, job in studio.jobs.items()
                    if job.get("_owner_id") == request.state.owner_id]
        return {"jobs": [studio.get(key, request.state.owner_id) for key in keys]}

    @app.get("/api/design/jobs/{job_id}")
    def job(job_id: str, request: Request):
        return studio.get(job_id, request.state.owner_id)

    @app.post("/api/design/jobs/{job_id}/build", status_code=202)
    def build(job_id: str, payload: BuildInput, request: Request):
        studio.get(job_id, request.state.owner_id)
        return studio.build(job_id, payload.story)

    @app.post("/api/design/jobs/{job_id}/variants/{variant}/fix", status_code=202)
    def fix(job_id: str, variant: str, payload: FixInput, request: Request):
        studio.get(job_id, request.state.owner_id)
        if variant not in VARIANTS:
            raise HTTPException(404, "Вариант не найден")
        return studio.fix(job_id, variant, payload)

    @app.post("/api/design/jobs/{job_id}/cancel")
    def cancel(job_id: str, request: Request):
        studio.get(job_id, request.state.owner_id)
        return studio.cancel(job_id)

    @app.get("/api/design/jobs/{job_id}/variants/{variant}/files/{revision}/{filename:path}")
    def download(job_id: str, variant: str, revision: int, filename: str, request: Request):
        studio.get(job_id, request.state.owner_id)
        if variant not in VARIANTS or revision < 1:
            raise HTTPException(404, "Файл не найден")
        if not re.fullmatch(r"presentation\.(pptx|pdf|html)|slides/slide-\d+\.(png|svg)", filename):
            raise HTTPException(404, "Файл не найден")
        directory = studio.directory(job_id) / "variants" / variant / str(revision)
        target = directory / filename
        if not target.is_file() or not target.resolve().is_relative_to(directory.resolve()):
            raise HTTPException(404, "Файл не найден")
        media = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        return FileResponse(target, media_type=media,
                            filename=target.name if filename.startswith("presentation") else None)

    @app.get("/{path:path}")
    def static(path: str):
        name = path or "index.html"
        target = STATIC / name
        if not target.is_file() or not target.resolve().is_relative_to(STATIC.resolve()):
            raise HTTPException(404, "Страница не найдена")
        return FileResponse(target)

    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description="ExpoSlides Studio")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path,
                        default=Path.home()/".local/share/exposlides/studio")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Некорректный порт")
    uvicorn.run(create_app(args.data_dir), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
