import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app import main as main_module


@pytest.mark.asyncio
async def test_serve_starts_and_stops_all_components():
    """Проверить, что serve стартует и останавливает все компоненты"""
    file_client = AsyncMock()
    producer = AsyncMock()
    consumer = AsyncMock()
    grpc_server = AsyncMock()
    pipeline = MagicMock()

    file_client.start = AsyncMock()
    file_client.stop = AsyncMock()
    producer.start = AsyncMock()
    producer.stop = AsyncMock()
    consumer.start = AsyncMock()
    consumer.stop = AsyncMock()
    consumer.run = AsyncMock()
    grpc_server.start = AsyncMock()
    grpc_server.stop = AsyncMock()

    with patch("app.grpc.file_service_client.FileServiceClient", return_value=file_client), patch(
        "app.kafka.producer.KafkaProducer", return_value=producer
    ), patch("app.kafka.consumer.KafkaConsumer", return_value=consumer), patch(
        "app.grpc.server.GrpcServer", return_value=grpc_server
    ), patch("app.services.content_pipeline.ContentPipeline", return_value=pipeline), patch.object(
        main_module, "setup_logging"
    ):

        task = asyncio.create_task(main_module.serve())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    file_client.start.assert_awaited_once()
    producer.start.assert_awaited_once()
    grpc_server.start.assert_awaited_once()
    consumer.start.assert_awaited_once()


def test_main_routes_to_cli_when_flag_present():
    """Проверить, что main вызывает CLI-режим при флаге --cli"""
    with patch.object(main_module, "_run_cli", return_value=0) as mock_cli:
        result = main_module.main(["--cli"])
    assert result == 0
    mock_cli.assert_called_once()


def test_main_routes_to_serve_by_default():
    """Проверить, что main запускает serve без флага --cli"""
    with patch.object(main_module, "asyncio") as mock_asyncio:
        mock_asyncio.run = MagicMock()
        result = main_module.main([])
    assert result == 0
    mock_asyncio.run.assert_called_once()


def test_parse_args_cli_flag():
    """Проверить, что --cli выставляет args.cli=True"""
    args = main_module._parse_args(["--cli"])
    assert args.cli is True


def test_parse_args_defaults_without_cli():
    """Проверить, что без --cli флаг args.cli=False"""
    args = main_module._parse_args([])
    assert args.cli is False
