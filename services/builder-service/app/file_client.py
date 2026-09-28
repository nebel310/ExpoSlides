"""gRPC-доступ к file-service для сетевого builder."""

from __future__ import annotations

from typing import TYPE_CHECKING

import grpc
from file_service_pb2 import DownloadFileRequest, UploadFileRequest
from file_service_pb2_grpc import FileServiceStub

if TYPE_CHECKING:
    from app.network import Settings


class FileServiceClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.channel = None
        self.stub = None

    async def start(self) -> None:
        self.channel = grpc.aio.insecure_channel(
            f"{self.settings.file_service_grpc_host}:{self.settings.file_service_grpc_port}",
            options=[
                ("grpc.max_receive_message_length", 64 * 1024 * 1024),
                ("grpc.max_send_message_length", 64 * 1024 * 1024),
            ],
        )
        self.stub = FileServiceStub(self.channel)

    async def stop(self) -> None:
        if self.channel is not None:
            await self.channel.close()
            self.channel = None
            self.stub = None

    async def download_file(self, file_id: str) -> bytes:
        if self.stub is None:
            raise RuntimeError("FileServiceClient не запущен")
        response = await self.stub.DownloadFile(
            DownloadFileRequest(file_id=file_id), timeout=self.settings.file_service_timeout
        )
        return response.content

    async def upload_file(
        self, *, filename: str, content: bytes, content_type: str, task_id: str
    ) -> str:
        if self.stub is None:
            raise RuntimeError("FileServiceClient не запущен")
        response = await self.stub.UploadFile(
            UploadFileRequest(
                filename=filename, content=content, content_type=content_type, task_id=task_id
            ),
            timeout=self.settings.file_service_timeout,
        )
        return response.file_id
