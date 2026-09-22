"""Состояние одной браузерной сессии поверх локального пайплайна."""

from __future__ import annotations

import atexit
import hashlib
import threading
import weakref
from copy import deepcopy
from typing import Any

from exposlides.web import APIError, Workspace

_sessions: weakref.WeakSet[PresentationSession] = weakref.WeakSet()
_sessions_lock = threading.RLock()


def _close_sessions() -> None:
    with _sessions_lock:
        sessions = list(_sessions)
    for session in sessions:
        try:
            session.close()
        except Exception:
            # Ошибка одной сессии не должна оставлять процессы остальных.
            continue


atexit.register(_close_sessions)


class PresentationSession:
    """Изолировать загрузки, сборку и просмотр от повторных запусков интерфейса."""

    def __init__(self, *, workspace: Workspace | None = None) -> None:
        self._workspace = workspace if workspace is not None else Workspace()
        self._template_id: str | None = None
        self._job_id: str | None = None
        self._templates_by_digest: dict[str, str] = {}
        self._closed = False
        # Callback удерживает только Workspace, поэтому сессия может быть собрана GC.
        self._finalizer = weakref.finalize(self, self._workspace.close)
        self._finalizer.atexit = False
        with _sessions_lock:
            _sessions.add(self)

    def _ensure_open(self) -> None:
        if self._closed or self._workspace.closed:
            raise APIError("Сессия завершена. Перезапустите интерфейс.", 503)

    def _ensure_idle(self) -> None:
        if self._job_id is not None:
            if self._workspace.get_job(self._job_id).status == "running":
                raise APIError("Дождитесь завершения текущей презентации.", 409)

    def _select(self, template_id: str) -> None:
        if template_id != self._template_id:
            self._ensure_idle()
            self._template_id = template_id
            self._job_id = None

    def select_template(self, name: str, data: bytes) -> dict[str, Any]:
        """Повторная передача того же PPTX не создаёт новую загрузку или сборку."""
        if not isinstance(name, str) or not name.lower().endswith(".pptx"):
            raise APIError("Выберите файл с расширением .pptx.")
        if not isinstance(data, bytes):
            raise APIError("Не удалось прочитать загруженный файл.")
        name = name.replace("\\", "/").rsplit("/", 1)[-1][:180]
        digest = hashlib.sha256(data).hexdigest()
        with self._workspace.lock:
            self._ensure_open()
            template_id = self._templates_by_digest.get(digest)
            if template_id != self._template_id or template_id is None:
                self._ensure_idle()
                if template_id is None:
                    metadata = self._workspace.add_template(name, data)
                    template_id = metadata["id"]
                    self._templates_by_digest[digest] = template_id
                self._select(template_id)
            return deepcopy(self._workspace.templates[template_id])

    def load_example(self) -> dict[str, Any]:
        with self._workspace.lock:
            self._ensure_open()
            if self._template_id != self._workspace.example_id:
                self._ensure_idle()
            example = self._workspace.example()
            self._select(example["id"])
            return deepcopy(example)

    def clear_template(self) -> None:
        with self._workspace.lock:
            self._ensure_open()
            self._ensure_idle()
            self._template_id = None
            self._job_id = None

    def start(self, script: str, max_slides: int | None = None) -> dict[str, Any]:
        with self._workspace.lock:
            self._ensure_open()
            self._ensure_idle()
            job = self._workspace.create_job({
                "template_id": self._template_id,
                "script": script,
                "max_slides": max_slides,
            })
            self._job_id = job["id"]
            return deepcopy(job)

    def snapshot(self) -> dict[str, Any]:
        """Вернуть согласованный снимок без процессов, путей и внутренних логов."""
        with self._workspace.lock:
            self._ensure_open()
            template = self._workspace.templates.get(self._template_id)
            job = self._workspace.get_job(self._job_id) if self._job_id is not None else None
            completed = job is not None and job.status == "completed"
            return deepcopy({
                "template": template,
                "job": job.public() if job is not None else None,
                "presentation": job.presentation if completed else template,
                "view": "result" if completed else ("template" if template is not None else None),
            })

    def get_slide(self, index: int) -> bytes | None:
        with self._workspace.lock:
            snapshot = self.snapshot()
            presentation = snapshot["presentation"]
            if (
                presentation is None or type(index) is not int
                or not 1 <= index <= presentation["slide_count"]
                or presentation["preview"]["status"] != "ready"
            ):
                return None
            try:
                if snapshot["view"] == "result":
                    return self._workspace.get_job_preview_image(self._job_id, index)
                return self._workspace.get_preview_image(self._template_id, index)
            except OSError:
                # Готовый PPTX остаётся доступным даже при потере файла предпросмотра.
                return None

    def download(self) -> bytes:
        with self._workspace.lock:
            self._ensure_open()
            job = self._workspace.get_job(self._job_id) if self._job_id is not None else None
            if job is None or job.status != "completed":
                raise APIError("Презентация ещё не готова.", 409)
            try:
                return (job.directory / "result.pptx").read_bytes()
            except OSError as error:
                raise APIError("Не удалось открыть презентацию. Запустите сборку ещё раз.") from error

    def close(self) -> None:
        with self._workspace.lock:
            if self._closed:
                return
            self._closed = True
        with _sessions_lock:
            _sessions.discard(self)
        # Workspace.close ждёт рабочие потоки: его нельзя вызывать под их блокировкой.
        self._finalizer()
