import io
import sys
from pathlib import Path

import grpc
import pytest
from google.protobuf.empty_pb2 import Empty
from pptx import Presentation
sys.path.insert(0, str(Path(__file__).parent.parent))

from file_service_pb2 import (
    DeleteFileRequest,
    DownloadFileRequest,
    UploadFileRequest,
)


TMP_DIR = Path(__file__).parent / "tmp_file"


def create_valid_pptx() -> bytes:
    """Создать валидный pptx в памяти и вернуть bytes"""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Test"
    buffer = io.BytesIO()
    prs.save(buffer)
    return buffer.getvalue()


@pytest.fixture(scope="module")
def uploaded_file_id(file_service_stub):
    """Загрузить валидный pptx и вернуть file_id"""
    content = create_valid_pptx()
    response = file_service_stub.UploadFile(
        UploadFileRequest(
            filename="test.pptx",
            content=content,
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    )
    yield response.file_id

    try:
        file_service_stub.DeleteFile(DeleteFileRequest(file_id=response.file_id))
    except grpc.RpcError:
        pass


def test_health_check(file_service_stub):
    """Проверить что healthcheck возвращает статус ok"""
    response = file_service_stub.HealthCheck(Empty())
    assert response.status == "ok"


def test_upload_valid_pptx(file_service_stub):
    """Проверить успешную загрузку валидного pptx"""
    content = create_valid_pptx()
    response = file_service_stub.UploadFile(
        UploadFileRequest(
            filename="valid.pptx",
            content=content,
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    )
    assert response.file_id
    assert response.original_name == "valid.pptx"
    assert response.size == len(content)

    file_service_stub.DeleteFile(DeleteFileRequest(file_id=response.file_id))


def test_upload_invalid_file_rejected(file_service_stub):
    """Проверить что невалидный файл отклоняется с ошибкой"""
    with pytest.raises(grpc.RpcError) as exc_info:
        file_service_stub.UploadFile(
            UploadFileRequest(
                filename="bad.txt",
                content=b"not a pptx",
                content_type="text/plain",
            )
        )
    assert exc_info.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_download_uploaded_file(file_service_stub, uploaded_file_id):
    """Проверить скачивание ранее загруженного файла"""
    response = file_service_stub.DownloadFile(DownloadFileRequest(file_id=uploaded_file_id))
    assert response.filename == "test.pptx"
    assert response.content_type.startswith("application/")
    assert len(response.content) > 0

    tmp_file_path = TMP_DIR / "downloaded_test.pptx"
    tmp_file_path.write_bytes(response.content)
    assert tmp_file_path.exists()


def test_download_nonexistent_file(file_service_stub):
    """Проверить что скачивание несуществующего файла возвращает NOT_FOUND"""
    with pytest.raises(grpc.RpcError) as exc_info:
        file_service_stub.DownloadFile(DownloadFileRequest(file_id="nonexistent"))
    assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND


def test_delete_file(file_service_stub):
    """Проверить удаление файла"""
    content = create_valid_pptx()
    upload_resp = file_service_stub.UploadFile(
        UploadFileRequest(
            filename="to_delete.pptx",
            content=content,
            content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    )
    file_service_stub.DeleteFile(DeleteFileRequest(file_id=upload_resp.file_id))
    with pytest.raises(grpc.RpcError) as exc_info:
        file_service_stub.DownloadFile(DownloadFileRequest(file_id=upload_resp.file_id))
    assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND