from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.grpc.server import GrpcServer, ParserServiceServicer
from google.protobuf import empty_pb2


@pytest.mark.asyncio
async def test_healthcheck_returns_ok() -> None:
    servicer = ParserServiceServicer()
    response = await servicer.HealthCheck(empty_pb2.Empty(), MagicMock())
    assert response.status == "ok"


@pytest.mark.asyncio
async def test_server_start_creates_grpc_server() -> None:
    server = GrpcServer(50052)
    fake_server = MagicMock()
    fake_server.start = AsyncMock()
    fake_server.add_insecure_port = MagicMock()

    with patch("app.grpc.server.grpc.aio.server", return_value=fake_server):
        with patch("app.grpc.server.parser_service_pb2_grpc.add_ParserServiceServicer_to_server"):
            await server.start()

    fake_server.add_insecure_port.assert_called_once_with("[::]:50052")
    fake_server.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_server_stop_calls_stop() -> None:
    server = GrpcServer(50052)
    fake_server = MagicMock()
    fake_server.stop = AsyncMock()

    server._server = fake_server
    await server.stop()

    fake_server.stop.assert_awaited_once()
    assert server._server is None


@pytest.mark.asyncio
async def test_server_stop_without_start() -> None:
    server = GrpcServer(50052)
    await server.stop()  # не должно падать