import logging
from concurrent import futures

import grpc
from content_service_pb2 import HealthCheckResponse
from content_service_pb2_grpc import ContentServiceServicer, add_ContentServiceServicer_to_server
from google.protobuf import empty_pb2

logger = logging.getLogger(__name__)


class ContentServiceServicer(ContentServiceServicer):
    """Реализация gRPC-сервиса content-service"""

    async def HealthCheck(self, request: empty_pb2.Empty, context: grpc.aio.ServicerContext) -> HealthCheckResponse:
        """Вернуть статус ok для healthcheck"""
        return HealthCheckResponse(status="ok")


class GrpcServer:
    """Обёртка над асинхронным gRPC-сервером"""

    def __init__(self, port: int) -> None:
        """Создать сервер на указанном порту"""
        self._port = port
        self._server: grpc.aio.Server | None = None

    async def start(self) -> None:
        """Запустить gRPC-сервер и зарегистрировать сервис"""
        logger.info("Запуск gRPC-сервера content-service на порту %d", self._port)
        self._server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=4))
        add_ContentServiceServicer_to_server(ContentServiceServicer(), self._server)
        self._server.add_insecure_port(f"[::]:{self._port}")
        await self._server.start()

    async def stop(self, grace: float = 5.0) -> None:
        """Остановить gRPC-сервер с таймаутом на завершение активных вызовов"""
        if self._server is not None:
            await self._server.stop(grace)
            self._server = None

    async def wait_for_termination(self) -> None:
        """Дождаться остановки сервера"""
        if self._server is not None:
            await self._server.wait_for_termination()