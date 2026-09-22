"""Streamlit-интерфейс локальной сборки презентаций."""

from __future__ import annotations

import hashlib
import html
import time
from pathlib import Path
from typing import Any

import streamlit as st

from exposlides.ui_session import PresentationSession
from exposlides.web import MAX_SCRIPT_LENGTH, APIError

ASSETS = Path(__file__).with_name("streamlit_static")


@st.cache_resource(scope="session", on_release=lambda session: session.close(), show_spinner=False)
def get_session() -> PresentationSession:
    return PresentationSession()


def _signature(snapshot: dict[str, Any]) -> tuple:
    job = snapshot.get("job") or {}
    presentation = snapshot.get("presentation") or {}
    return (
        job.get("id"), job.get("status"), presentation.get("id"),
        (presentation.get("preview") or {}).get("status"),
    )


def _running(snapshot: dict[str, Any]) -> bool:
    return (snapshot.get("job") or {}).get("status") == "running"


def _fingerprint(name: str, data: bytes) -> str:
    return hashlib.sha256(name.encode("utf-8") + b"\0" + data).hexdigest()


def _import_text(disabled: bool) -> None:
    with st.expander("Импортировать .txt"):
        uploaded = st.file_uploader(
            "Текст в UTF-8", type=["txt"], disabled=disabled, max_upload_size=1,
            key=f"text_file_{st.session_state.get('upload_epoch', 0)}",
        )
    if uploaded is None:
        st.session_state.pop("text_fingerprint", None)
        return
    data = uploaded.getvalue()
    fingerprint = _fingerprint(uploaded.name, data)
    if fingerprint == st.session_state.get("text_fingerprint"):
        return
    try:
        if len(data) > MAX_SCRIPT_LENGTH * 4:
            raise APIError("Текст слишком длинный. Допускается не больше 100 000 символов.")
        text = data.decode("utf-8-sig")
        if len(text) > MAX_SCRIPT_LENGTH:
            raise APIError("Текст слишком длинный. Допускается не больше 100 000 символов.")
    except UnicodeDecodeError:
        st.error("Не удалось прочитать текст. Сохраните файл в UTF-8.")
    except APIError as error:
        st.error(str(error))
    else:
        st.session_state["script"] = text
        st.session_state["text_fingerprint"] = fingerprint


def _materials(session: PresentationSession, snapshot: dict[str, Any]) -> None:
    running = _running(snapshot)
    st.subheader("Материалы")
    if st.button("Открыть пример", key="example", disabled=running, type="tertiary"):
        try:
            example = session.load_example()
            st.session_state["script"] = example["script"]
            st.session_state["upload_epoch"] = st.session_state.get("upload_epoch", 0) + 1
            st.session_state.pop("had_upload", None)
            st.session_state.pop("text_fingerprint", None)
            st.session_state.pop("input_error", None)
            st.rerun()
        except APIError as error:
            st.error(str(error))

    uploaded = st.file_uploader(
        "Шаблон PPTX", type=["pptx"], max_upload_size=25, disabled=running,
        key=f"template_file_{st.session_state.get('upload_epoch', 0)}",
        help="До 25 МБ. Используем оформление и текстовые заполнители шаблона.",
    )
    upload_error = None
    try:
        if uploaded is not None:
            session.select_template(uploaded.name, uploaded.getvalue())
            st.session_state["had_upload"] = True
        elif st.session_state.pop("had_upload", False):
            session.clear_template()
    except APIError as error:
        upload_error = str(error)
        st.error(upload_error)

    template = session.snapshot().get("template")
    if template:
        st.caption(f"{template['slide_count']} слайдов · PowerPoint")

    _import_text(running)
    script = st.text_area(
        "Исходный текст", key="script", height=260, max_chars=MAX_SCRIPT_LENGTH,
        placeholder="Вставьте текст доклада: основные мысли, факты и выводы.", disabled=running,
    )
    count = template["slide_count"] if template else 1
    limit = st.selectbox(
        "Слайдов", options=[None, *range(1, count + 1)],
        format_func=lambda value: "Автоматически" if value is None else str(value),
        key=f"limit_{template['id'] if template else 'empty'}", disabled=running or not template,
        help="Верхний предел. Не больше, чем в шаблоне.",
    )
    if st.button(
        "Создать презентацию", type="primary", width="stretch", key="generate",
        disabled=running or not template or not script.strip() or bool(upload_error),
    ):
        try:
            session.start(script, limit)
            st.session_state["started_at"] = time.monotonic()
            st.session_state.pop("input_error", None)
            st.rerun()
        except APIError as error:
            st.session_state["input_error"] = str(error)
    if st.session_state.get("input_error"):
        st.error(st.session_state["input_error"])


def _phase(job: dict[str, Any]) -> str:
    if job.get("stage") == "parser":
        return "Читаем шаблон"
    if job.get("stage") == "builder":
        return "Собираем презентацию"
    progress = job.get("progress") or {}
    if progress.get("retrying"):
        return "Уточняем текст после проверки"
    return {
        "analysis": "Разбираем исходный текст",
        "planning": "Составляем план слайдов",
        "slides": "Готовим текст слайдов",
        "validation": "Проверяем содержание",
    }.get(progress.get("phase"), "Готовим презентацию")


def _animation() -> None:
    st.html(
        '<div class="assembly" role="img" aria-label="Сборка слайдов">'
        '<div class="assembly-card back"></div><div class="assembly-card middle"></div>'
        '<div class="assembly-card front"><span class="assembly-label">EXPOSLIDES</span>'
        '<i class="assembly-title"></i><i class="assembly-line one"></i>'
        '<i class="assembly-line two"></i><i class="assembly-line three"></i>'
        '<span class="assembly-accent"></span></div></div>'
    )


def _text_slide(slide: dict[str, Any]) -> None:
    title = slide["title"]
    paragraphs = [text for text in slide.get("texts", []) if text != title]
    body = "".join(f"<p>{html.escape(text)}</p>" for text in paragraphs[:8])
    st.html(
        '<div class="text-slide"><span class="slide-kicker">ТЕКСТ СЛАЙДА</span>'
        f'<h2>{html.escape(title)}</h2><div class="slide-copy">{body}</div></div>'
    )


def _move_slide(key: str, delta: int, count: int) -> None:
    st.session_state[key] = min(count, max(1, st.session_state.get(key, 1) + delta))


def _preview(session: PresentationSession, snapshot: dict[str, Any]) -> None:
    presentation = snapshot.get("presentation")
    job = snapshot.get("job") or {}
    if _running(snapshot):
        st.subheader("Сборка презентации")
        started = st.session_state.get("started_at", time.monotonic())
        elapsed = max(0, int(time.monotonic() - started))
        st.caption(f"{_phase(job)} · {elapsed // 60:02d}:{elapsed % 60:02d}")
        show_template = st.toggle("Показать шаблон", key=f"show_template_{job['id']}")
        if not show_template:
            _animation()
            return
    elif job.get("status") == "failed":
        st.subheader("Сборка остановилась")
        st.error(job.get("error") or "Не удалось собрать презентацию. Попробуйте ещё раз.")
    else:
        st.subheader("Готовая презентация" if snapshot.get("view") == "result" else "Просмотр")

    if presentation is None:
        st.html(
            '<div class="empty-preview"><div class="empty-slide"><i></i><i></i><i></i></div>'
            '<h3>Здесь будут слайды</h3><p>Загрузите шаблон или откройте пример.</p></div>'
        )
        return

    if snapshot.get("view") == "result":
        try:
            result = session.download()
        except APIError as error:
            st.error(str(error))
        else:
            st.download_button(
                "Скачать PPTX", data=result, file_name="Презентация.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                key=f"download_{job['id']}", type="primary", on_click="ignore",
            )

    count = presentation["slide_count"]
    key = f"slide_{snapshot.get('view')}_{presentation['id']}"
    index = min(count, max(1, st.session_state.get(key, 1)))
    st.session_state[key] = index
    previous, navigation, following = st.columns([1, 5, 1], vertical_alignment="center")
    previous.button(
        "←", key=f"prev_{key}", help="Предыдущий слайд", disabled=index == 1,
        on_click=_move_slide, args=(key, -1, count), width="stretch",
    )
    with navigation:
        index = st.selectbox(
            "Слайд", options=range(1, count + 1), key=key, label_visibility="collapsed",
            format_func=lambda number: f"{number:02d} / {count:02d}",
        )
    following.button(
        "→", key=f"next_{key}", help="Следующий слайд", disabled=index == count,
        on_click=_move_slide, args=(key, 1, count), width="stretch",
    )

    preview = presentation.get("preview") or {}
    try:
        picture = session.get_slide(index)
    except APIError:
        picture = None
        st.caption("Изображение слайда недоступно. Ниже — его текст.")
    if picture:
        st.image(picture, width="stretch")
    else:
        _text_slide(presentation["slides"][index - 1])
        if preview.get("status") == "pending":
            st.caption("Готовим изображения слайдов…")
        else:
            st.caption(preview.get("message") or "Текстовый просмотр")


def main() -> None:
    st.set_page_config(page_title="ExpoSlides", page_icon="▤", layout="wide")
    st.html(f"<style>{(ASSETS / 'styles.css').read_text(encoding='utf-8')}</style>")
    st.html('<div class="app-heading"><h1>ExpoSlides</h1><span>Новая презентация</span></div>')
    session = get_session()
    snapshot = session.snapshot()
    materials, preview = st.columns([1, 1.9], gap="large")
    with materials:
        _materials(session, snapshot)
    signature = _signature(snapshot)
    st.session_state["render_signature"] = signature
    needs_updates = _running(snapshot) or (
        ((snapshot.get("presentation") or {}).get("preview") or {}).get("status") == "pending"
    )

    @st.fragment(run_every=1 if needs_updates else None)
    def live_preview() -> None:
        current = session.snapshot()
        if _signature(current) != st.session_state.get("render_signature"):
            st.rerun()
        _preview(session, current)

    with preview:
        live_preview()
