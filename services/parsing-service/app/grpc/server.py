from __future__ import annotations

import logging

import grpc
from google.protobuf import empty_pb2

import parser_service_pb2
import parser_service_pb2_grpc

logger = logging.getLogger(__name__)


class ParserServiceServicer(parser_service_pb2_grpc.ParserServiceServicer):
    """Реализация ParserService для healthcheck"""

    async def HealthCheck(
        self,
        request: empty_pb2.Empty,
        context: grpc.aio.ServicerContext,
    ) -> parser_service_pb2.HealthCheckResponse:
        """Возвращает статус ok"""
        return parser_service_pb2.HealthCheckResponse(status="ok")


class GrpcServer:
    """Обёртка над grpc.aio.Server с lifecycle"""

    def __init__(self, port: int) -> None:
        """Сохраняет порт и готовит пустой сервер"""
        self._port = port
        self._server: grpc.aio.Server | None = None

    async def start(self) -> None:
        """Создаёт сервер, регистрирует сервис и слушает порт"""
        self._server = grpc.aio.server()
        parser_service_pb2_grpc.add_ParserServiceServicer_to_server(
            ParserServiceServicer(), self._server
        )
        self._server.add_insecure_port(f"[::]:{self._port}")
        await self._server.start()
        logger.info("Parser gRPC-сервер слушает порт %s", self._port)

    async def stop(self) -> None:
        """Останавливает сервер с grace-периодом"""
        if self._server is not None:
            await self._server.stop(grace=5)
            self._server = None