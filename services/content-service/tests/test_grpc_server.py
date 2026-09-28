from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.grpc.server import ContentServiceServicer, GrpcServer


@pytest.mark.asyncio
async def test_healthcheck_returns_ok():
    """Проверить, что HealthCheck возвращает status=ok"""
    servicer = ContentServiceServicer()
    response = await servicer.HealthCheck(None, None)
    assert response.status == "ok"


@pytest.mark.asyncio
async def test_start_registers_servicer_and_binds_port():
    """Проверить, что start регистрирует сервис и биндит порт"""
    with patch("app.grpc.server.grpc.aio.server") as mock_server_factory, patch(
        "app.grpc.server.add_ContentServiceServicer_to_server"
    ) as mock_add, patch("app.grpc.server.ContentServiceServicer") as mock_servicer_cls:
        mock_server = MagicMock()
        mock_server.start = AsyncMock()
        mock_server.add_insecure_port = MagicMock(return_value=50053)
        mock_server_factory.return_value = mock_server

        server = GrpcServer(port=50053)
        await server.start()

        mock_servicer_cls.assert_called_once()
        mock_add.assert_called_once()
        mock_server.add_insecure_port.assert_called_once_with("[::]:50053")
        mock_server.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_calls_stop_with_grace():
    """Проверить, что stop останавливает сервер с grace-таймаутом"""
    with patch("app.grpc.server.grpc.aio.server") as mock_server_factory, patch(
        "app.grpc.server.add_ContentServiceServicer_to_server"
    ):
        mock_server = MagicMock()
        mock_server.start = AsyncMock()
        mock_server.stop = AsyncMock()
        mock_server.add_insecure_port = MagicMock(return_value=50053)
        mock_server_factory.return_value = mock_server

        server = GrpcServer(port=50053)
        await server.start()
        await server.stop(grace=1.5)
        mock_server.stop.assert_awaited_once_with(1.5)


@pytest.mark.asyncio
async def test_stop_without_start_is_safe():
    """Проверить, что stop без start не падает"""
    server = GrpcServer(port=50053)
    await server.stop()


@pytest.mark.asyncio
async def test_wait_for_termination_without_start_is_safe():
    """Проверить, что wait_for_termination без start не падает"""
    server = GrpcServer(port=50053)
    await server.wait_for_termination()


@pytest.mark.asyncio
async def test_wait_for_termination_delegates_to_server():
    """Проверить, что wait_for_termination вызывает сервер"""
    with patch("app.grpc.server.grpc.aio.server") as mock_server_factory, patch(
        "app.grpc.server.add_ContentServiceServicer_to_server"
    ):
        mock_server = MagicMock()
        mock_server.start = AsyncMock()
        mock_server.wait_for_termination = AsyncMock()
        mock_server.add_insecure_port = MagicMock(return_value=50053)
        mock_server_factory.return_value = mock_server

        server = GrpcServer(port=50053)
        await server.start()
        await server.wait_for_termination()
        mock_server.wait_for_termination.assert_awaited_once()  