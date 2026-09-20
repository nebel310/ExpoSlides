from __future__ import annotations

import pytest
from google.protobuf import empty_pb2

import parser_service_pb2
from app.grpc.server import GrpcServer, ParserServiceServicer


@pytest.mark.asyncio
async def test_health_check_returns_ok():
    """HealthCheck возвращает status=ok"""
    servicer = ParserServiceServicer()
    response = await servicer.HealthCheck(empty_pb2.Empty(), None)
    assert isinstance(response, parser_service_pb2.HealthCheckResponse)
    assert response.status == "ok"


@pytest.mark.asyncio
async def test_grpc_server_start_and_stop():
    """GrpcServer поднимается на свободном порту и корректно останавливается"""
    server = GrpcServer(port=0)
    await server.start()
    await server.stop()