import io
import json
import uuid

import grpc
import pytest
from pptx import Presentation

from file_service_pb2 import (
    DeleteFileRequest,
    DownloadFileRequest,
    GetFileInfoRequest,
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


def create_valid_pptx_with_text(text: str) -> bytes:
    """Создать валидный pptx с заданным текстом заголовка"""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = text
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
        assert response.file_type in ("pptx", "pdf", "json", "txt")
        assert response.version == 1

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


def test_upload_and_get_file_info(file_service_stub):
    """Проверить сохранение метаданных в БД после загрузки"""
    content = create_valid_pptx()
    task_id = str(uuid.uuid4())
    response = file_service_stub.UploadFile(
        UploadFileRequest(
            filename="info_test.pptx",
            content=content,
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            task_id=task_id,
        )
    )
    file_id = response.file_id
    try:
        info = file_service_stub.GetFileInfo(GetFileInfoRequest(file_id=file_id))
        assert info.file_id == file_id
        assert info.original_name == "info_test.pptx"
        assert info.size == len(content)
        assert info.task_id == task_id
        assert info.version == 1
        assert f"/v1.pptx" in info.object_key
    finally:
        file_service_stub.DeleteFile(DeleteFileRequest(file_id=file_id))


def test_upload_without_task_id(file_service_stub):
    """Проверить что task_id может быть пустым"""
    content = create_valid_txt()
    response = file_service_stub.UploadFile(
        UploadFileRequest(
            filename="no_task.txt",
            content=content,
            content_type="text/plain",
        )
    )
    file_id = response.file_id
    try:
        info = file_service_stub.GetFileInfo(GetFileInfoRequest(file_id=file_id))
        assert info.task_id == ""
    finally:
        file_service_stub.DeleteFile(DeleteFileRequest(file_id=file_id))


def test_delete_removes_db_record(file_service_stub):
    """Проверить что после удаления файла запись в БД удаляется"""
    content = create_valid_json()
    response = file_service_stub.UploadFile(
        UploadFileRequest(
            filename="delete_test.json",
            content=content,
            content_type="application/json",
        )
    )
    file_id = response.file_id

    file_service_stub.DeleteFile(DeleteFileRequest(file_id=file_id))

    with pytest.raises(grpc.RpcError) as exc_info:
        file_service_stub.GetFileInfo(GetFileInfoRequest(file_id=file_id))
    assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND


def test_download_after_upload(file_service_stub):
    """Проверить скачивание файла после загрузки"""
    content = create_valid_pptx()
    response = file_service_stub.UploadFile(
        UploadFileRequest(
            filename="download_test.pptx",
            content=content,
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    )
    file_id = response.file_id
    try:
        download = file_service_stub.DownloadFile(DownloadFileRequest(file_id=file_id))
        assert download.filename == "download_test.pptx"
        assert download.content == content
        assert download.version == 1
    finally:
        file_service_stub.DeleteFile(DeleteFileRequest(file_id=file_id))


def test_upload_new_version(file_service_stub):
    """Проверить что загрузка с существующим file_id создаёт новую версию"""
    content_v1 = create_valid_pptx_with_text("Version 1")
    content_v2 = create_valid_pptx_with_text("Version 2")

    response_v1 = file_service_stub.UploadFile(
        UploadFileRequest(
            filename="versioned.pptx",
            content=content_v1,
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    )
    file_id = response_v1.file_id
    assert response_v1.version == 1

    try:
        response_v2 = file_service_stub.UploadFile(
            UploadFileRequest(
                filename="versioned.pptx",
                content=content_v2,
                content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                file_id=file_id,
            )
        )
        assert response_v2.file_id == file_id
        assert response_v2.version == 2

        info_latest = file_service_stub.GetFileInfo(GetFileInfoRequest(file_id=file_id, version=0))
        assert info_latest.version == 2

        info_v1 = file_service_stub.GetFileInfo(GetFileInfoRequest(file_id=file_id, version=1))
        assert info_v1.version == 1

        info_v2 = file_service_stub.GetFileInfo(GetFileInfoRequest(file_id=file_id, version=2))
        assert info_v2.version == 2
        assert info_v1.object_key != info_v2.object_key
    finally:
        file_service_stub.DeleteFile(DeleteFileRequest(file_id=file_id))


def test_download_specific_version(file_service_stub):
    """Проверить скачивание конкретной версии файла"""
    content_v1 = create_valid_pptx_with_text("Content V1")
    content_v2 = create_valid_pptx_with_text("Content V2")

    response_v1 = file_service_stub.UploadFile(
        UploadFileRequest(
            filename="dl_versioned.pptx",
            content=content_v1,
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    )
    file_id = response_v1.file_id

    try:
        file_service_stub.UploadFile(
            UploadFileRequest(
                filename="dl_versioned.pptx",
                content=content_v2,
                content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                file_id=file_id,
            )
        )

        download_v1 = file_service_stub.DownloadFile(DownloadFileRequest(file_id=file_id, version=1))
        assert download_v1.version == 1
        assert download_v1.content == content_v1

        download_v2 = file_service_stub.DownloadFile(DownloadFileRequest(file_id=file_id, version=2))
        assert download_v2.version == 2
        assert download_v2.content == content_v2

        download_latest = file_service_stub.DownloadFile(DownloadFileRequest(file_id=file_id, version=0))
        assert download_latest.version == 2
        assert download_latest.content == content_v2
    finally:
        file_service_stub.DeleteFile(DeleteFileRequest(file_id=file_id))


def test_upload_new_version_for_nonexistent_file(file_service_stub):
    """Проверить что загрузка с несуществующим file_id отклоняется"""
    content = create_valid_pptx()
    fake_file_id = str(uuid.uuid4())
    with pytest.raises(grpc.RpcError) as exc_info:
        file_service_stub.UploadFile(
            UploadFileRequest(
                filename="fake.pptx",
                content=content,
                content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                file_id=fake_file_id,
            )
        )
    assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND


def test_delete_removes_all_versions(file_service_stub):
    """Проверить что удаление убирает все версии файла"""
    content_v1 = create_valid_pptx_with_text("V1")
    content_v2 = create_valid_pptx_with_text("V2")

    response_v1 = file_service_stub.UploadFile(
        UploadFileRequest(
            filename="multi_version.pptx",
            content=content_v1,
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    )
    file_id = response_v1.file_id

    file_service_stub.UploadFile(
        UploadFileRequest(
            filename="multi_version.pptx",
            content=content_v2,
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            file_id=file_id,
        )
    )

    file_service_stub.DeleteFile(DeleteFileRequest(file_id=file_id))

    with pytest.raises(grpc.RpcError) as exc_info:
        file_service_stub.GetFileInfo(GetFileInfoRequest(file_id=file_id, version=0))
    assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND

    with pytest.raises(grpc.RpcError) as exc_info:
        file_service_stub.GetFileInfo(GetFileInfoRequest(file_id=file_id, version=1))
    assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND

    with pytest.raises(grpc.RpcError) as exc_info:
        file_service_stub.GetFileInfo(GetFileInfoRequest(file_id=file_id, version=2))
    assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND