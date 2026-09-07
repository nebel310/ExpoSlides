import io
import json

import grpc
import pytest
from pptx import Presentation

from file_service_pb2 import (
    DeleteFileRequest,
    UploadFileRequest,
)




def create_valid_pptx() -> bytes:
    """Создать валидный pptx в памяти и вернуть bytes"""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Test"
    buffer = io.BytesIO()
    prs.save(buffer)
    return buffer.getvalue()


def create_valid_pdf() -> bytes:
    """Создать минимальный валидный pdf в памяти и вернуть bytes"""
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


def create_valid_json() -> bytes:
    """Создать валидный json в памяти и вернуть bytes"""
    data = {"key": "value", "list": [1, 2, 3]}
    return json.dumps(data).encode("utf-8")


def create_valid_txt() -> bytes:
    """Создать валидный txt в памяти и вернуть bytes"""
    return "Hello, world!".encode("utf-8")


@pytest.fixture(scope="module")
def valid_files():
    """Вернуть словарь с валидными файлами для загрузки"""
    return {
        "test.pptx": create_valid_pptx(),
        "test.pdf": create_valid_pdf(),
        "test.json": create_valid_json(),
        "test.txt": create_valid_txt(),
    }


@pytest.fixture(scope="module")
def invalid_files():
    """Вернуть список кортежей с невалидными файлами"""
    return [
        ("fake.pptx", b"not a pptx"),
        ("fake.pdf", b"not a pdf"),
        ("fake.json", b"not a json"),
        ("fake.txt", b"\x00\x01\x02\x03"),
        ("no_extension", b"random bytes"),
        ("evil.exe", b"MZ\x90\x00"),
    ]


def test_upload_valid_files(file_service_stub, valid_files):
    """Проверить успешную загрузку файлов допустимых типов"""
    for filename, content in valid_files.items():
        response = file_service_stub.UploadFile(
            UploadFileRequest(
                filename=filename,
                content=content,
                content_type="application/octet-stream",
            )
        )
        assert response.file_id
        assert response.original_name == filename
        assert response.size == len(content)

        file_service_stub.DeleteFile(DeleteFileRequest(file_id=response.file_id))


def test_upload_invalid_files(file_service_stub, invalid_files):
    """Проверить что невалидные файлы отклоняются с ошибкой"""
    for filename, content in invalid_files:
        with pytest.raises(grpc.RpcError) as exc_info:
            file_service_stub.UploadFile(
                UploadFileRequest(
                    filename=filename,
                    content=content,
                    content_type="application/octet-stream",
                )
            )
        assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT