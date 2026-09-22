"""Общие фикстуры для тестов parsing-service."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from pptx import Presentation as PPTXPresentation
from pptx.util import Emu

from app.parsers.pptx.assets import AssetBlob


# ---------- Генераторы pptx-файлов ----------


def _new_presentation(width: int = 9144000, height: int = 6858000) -> PPTXPresentation:
    """Создаёт пустую презентацию с заданным размером слайда"""
    prs = PPTXPresentation()
    prs.slide_width = Emu(width)
    prs.slide_height = Emu(height)
    return prs


@pytest.fixture
def empty_pptx_path(tmp_path: Path) -> Path:
    """Пустой pptx без слайдов"""
    prs = _new_presentation()
    path = tmp_path / "empty.pptx"
    prs.save(str(path))
    return path


@pytest.fixture
def simple_pptx_path(tmp_path: Path) -> Path:
    """Минимальный pptx: один титульный слайд с текстом"""
    prs = _new_presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Hello world"
    path = tmp_path / "simple.pptx"
    prs.save(str(path))
    return path


@pytest.fixture
def text_pptx_path(tmp_path: Path) -> Path:
    """Pptx со слайдом, где есть заголовок и список буллетов"""
    prs = _new_presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])  # Title and Content
    slide.shapes.title.text = "Заголовок"
    body = slide.placeholders[1]
    tf = body.text_frame
    tf.text = "Первый пункт"
    p = tf.add_paragraph()
    p.text = "Второй пункт"
    p.level = 1
    path = tmp_path / "text.pptx"
    prs.save(str(path))
    return path


@pytest.fixture
def table_pptx_path(tmp_path: Path) -> Path:
    """Pptx со слайдом и таблицей 2x2"""
    prs = _new_presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # Blank
    rows, cols = 2, 2
    left = Emu(914400)
    top = Emu(914400)
    width = Emu(4572000)
    height = Emu(2286000)
    table_shape = slide.shapes.add_table(rows, cols, left, top, width, height)
    table = table_shape.table
    table.cell(0, 0).text = "A"
    table.cell(0, 1).text = "B"
    table.cell(1, 0).text = "C"
    table.cell(1, 1).text = "D"
    path = tmp_path / "table.pptx"
    prs.save(str(path))
    return path


@pytest.fixture
def picture_pptx_path(tmp_path: Path) -> Path:
    """Pptx со слайдом и одной картинкой (PNG 1x1)"""
    prs = _new_presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    # минимальный PNG 1x1 (валидный)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    img_path = tmp_path / "tiny.png"
    img_path.write_bytes(png_bytes)

    slide.shapes.add_picture(
        str(img_path),
        left=Emu(914400),
        top=Emu(914400),
        width=Emu(914400),
        height=Emu(914400),
    )
    path = tmp_path / "picture.pptx"
    prs.save(str(path))
    return path


@pytest.fixture
def group_pptx_path(tmp_path: Path) -> Path:
    """Pptx со слайдом и одной группой из двух фигур"""
    prs = _new_presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    shape1 = slide.shapes.add_textbox(Emu(0), Emu(0), Emu(914400), Emu(914400))
    shape1.text_frame.text = "inside-1"
    shape2 = slide.shapes.add_textbox(
        Emu(914400), Emu(0), Emu(914400), Emu(914400)
    )
    shape2.text_frame.text = "inside-2"

    # python-pptx не умеет создавать группы напрямую,
    # обернём элементы в group через XML трюк
    # для теста используем add_group_shape если доступно
    try:
        group = slide.shapes.add_group_shape()
        group.shapes.add_textbox(Emu(0), Emu(0), Emu(914400), Emu(914400))
    except Exception:
        # в некоторых версиях python-pptx метод отсутствует — тогда
        # тест на группы будет пропущен
        pytest.skip("add_group_shape недоступен в текущей версии python-pptx")

    path = tmp_path / "group.pptx"
    prs.save(str(path))
    return path


# ---------- Моки внешних зависимостей ----------


class FakeFileServiceClient:
    """Фейковый gRPC-клиент file-service, хранящий файлы в памяти"""

    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}
        self._counter = 0
        self.upload_calls: list[dict] = []
        self.download_calls: list[dict] = []
        self.delete_calls: list[dict] = []

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def download_file(self, file_id: str, version: int = 0) -> bytes:
        self.download_calls.append({"file_id": file_id, "version": version})
        if file_id not in self._files:
            raise FileNotFoundError(file_id)
        return self._files[file_id]

    async def upload_file(
        self,
        filename: str,
        content: bytes,
        content_type: str,
        task_id: str,
        file_id: str | None = None,
    ) -> str:
        self._counter += 1
        new_id = file_id or f"file-{self._counter}"
        self._files[new_id] = content
        self.upload_calls.append(
            {
                "filename": filename,
                "content": content,
                "content_type": content_type,
                "task_id": task_id,
                "file_id": file_id,
            }
        )
        return new_id

    async def delete_file(self, file_id: str) -> None:
        self.delete_calls.append({"file_id": file_id})
        self._files.pop(file_id, None)

    def put(self, file_id: str, content: bytes) -> None:
        """Ручная закладка файла в фейковый сервис"""
        self._files[file_id] = content


class FakeKafkaProducer:
    """Фейковый Kafka-продюсер, пишущий в список"""

    def __init__(self) -> None:
        self.messages: list[tuple[str, bytes]] = []
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    async def publish(self, topic: str, envelope) -> None:
        payload = envelope.model_dump_json().encode("utf-8")
        self.messages.append((topic, payload))


@pytest.fixture
def fake_file_client() -> FakeFileServiceClient:
    return FakeFileServiceClient()


@pytest.fixture
def fake_producer() -> FakeKafkaProducer:
    return FakeKafkaProducer()


# ---------- Вспомогательные фикстуры для ассетов ----------


@pytest.fixture
def fake_asset_blob() -> AssetBlob:
    return AssetBlob(
        asset_id="abc123",
        content_type="image/png",
        data=b"\x89PNG",
        original_name="pic.png",
    )


@pytest.fixture
def assets_dict() -> dict:
    return {}