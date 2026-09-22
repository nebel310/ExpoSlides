from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable
from uuid import uuid4

import grpc
import pytest
import pytest_asyncio
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient
from google.protobuf import empty_pb2

import file_service_pb2_grpc
import parser_service_pb2_grpc

from app.grpc.file_service_client import FileServiceClient


# ---------- Env ----------


FILE_SERVICE_HOST = os.environ.get("FILE_SERVICE_GRPC_HOST", "localhost")
FILE_SERVICE_PORT = int(os.environ.get("FILE_SERVICE_GRPC_PORT", "50051"))
FILE_SERVICE_TARGET = f"{FILE_SERVICE_HOST}:{FILE_SERVICE_PORT}"

PARSER_SERVICE_HOST = os.environ.get("PARSER_SERVICE_GRPC_HOST", "localhost")
PARSER_SERVICE_PORT = int(os.environ.get("PARSER_SERVICE_GRPC_PORT", "50052"))
PARSER_SERVICE_TARGET = f"{PARSER_SERVICE_HOST}:{PARSER_SERVICE_PORT}"

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_EXTERNAL_BOOTSTRAP", "localhost:9093")

TOPIC_CREATED = os.environ.get("KAFKA_TOPIC_TASK_CREATED", "task.created")
TOPIC_PARSED = os.environ.get("KAFKA_TOPIC_TASK_PARSED", "task.parsed")
TOPIC_FAILED = os.environ.get("KAFKA_TOPIC_TASK_FAILED", "task.failed")

PPTX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)

MESSAGE_TIMEOUT_SEC = 30.0


# ---------- Healthchecks ----------


async def _file_service_alive() -> bool:
    channel = grpc.aio.insecure_channel(FILE_SERVICE_TARGET)
    try:
        stub = file_service_pb2_grpc.FileServiceStub(channel)
        await asyncio.wait_for(stub.HealthCheck(empty_pb2.Empty()), timeout=3.0)
        return True
    except Exception:
        return False
    finally:
        await channel.close()


async def _parser_service_alive() -> bool:
    channel = grpc.aio.insecure_channel(PARSER_SERVICE_TARGET)
    try:
        stub = parser_service_pb2_grpc.ParserServiceStub(channel)
        await asyncio.wait_for(stub.HealthCheck(empty_pb2.Empty()), timeout=3.0)
        return True
    except Exception:
        return False
    finally:
        await channel.close()


async def _kafka_alive() -> bool:
    try:
        admin = AIOKafkaAdminClient(bootstrap_servers=KAFKA_BOOTSTRAP)
        await asyncio.wait_for(admin.start(), timeout=5.0)
        await admin.close()
        return True
    except Exception:
        return False


# ---------- Base fixtures ----------


@pytest_asyncio.fixture
async def file_client() -> AsyncIterator[FileServiceClient]:
    """Реальный клиент file-service (skip, если сервис лежит)"""
    if not await _file_service_alive():
        pytest.skip(f"file-service недоступен на {FILE_SERVICE_TARGET}")

    client = FileServiceClient(FILE_SERVICE_HOST, FILE_SERVICE_PORT)
    await client.connect()
    try:
        yield client
    finally:
        await client.close()


@pytest_asyncio.fixture
async def parser_service_ready() -> None:
    """Skip, если parser-service или Kafka недоступны"""
    if not await _parser_service_alive():
        pytest.skip(f"parser-service недоступен на {PARSER_SERVICE_TARGET}")
    if not await _kafka_alive():
        pytest.skip(f"Kafka недоступна на {KAFKA_BOOTSTRAP}")


@pytest_asyncio.fixture
async def kafka_producer() -> AsyncIterator[AIOKafkaProducer]:
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
    await producer.start()
    try:
        yield producer
    finally:
        await producer.stop()


# ---------- Фабрики ----------


UploadFactory = Callable[..., Awaitable[str]]
ConsumerFactory = Callable[[list[str]], Awaitable[AIOKafkaConsumer]]


@pytest_asyncio.fixture
async def uploaded_pptx_factory(
    file_client: FileServiceClient,
) -> AsyncIterator[UploadFactory]:
    """Фабрика: загружает pptx и удаляет после теста"""
    created: list[str] = []

    async def _upload(
        content: bytes,
        task_id: str = "e2e-test",
        filename: str = "template.pptx",
    ) -> str:
        file_id = await file_client.upload_file(
            filename=filename,
            content=content,
            content_type=PPTX_CONTENT_TYPE,
            task_id=task_id,
        )
        created.append(file_id)
        return file_id

    try:
        yield _upload
    finally:
        for file_id in created:
            try:
                await file_client.delete_file(file_id)
            except Exception:
                pass


@pytest_asyncio.fixture
async def kafka_consumer_factory() -> AsyncIterator[ConsumerFactory]:
    """Фабрика: создаёт consumer с уникальной группой на нужные топики"""
    consumers: list[AIOKafkaConsumer] = []

    async def _make(topics: list[str]) -> AIOKafkaConsumer:
        consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id=f"parser-e2e-{uuid4().hex}",
            auto_offset_reset="latest",
            enable_auto_commit=False,
        )
        await consumer.start()
        consumers.append(consumer)
        return consumer

    try:
        yield _make
    finally:
        for consumer in consumers:
            try:
                await consumer.stop()
            except Exception:
                pass


@pytest_asyncio.fixture
async def structure_file_cleanup(
    file_client: FileServiceClient,
) -> AsyncIterator[Callable[[str], Awaitable[None]]]:
    """Позволяет тесту зарегистрировать file_id структуры для удаления"""
    created: list[str] = []

    async def _track(file_id: str) -> None:
        created.append(file_id)

    try:
        yield _track
    finally:
        for file_id in created:
            try:
                await file_client.delete_file(file_id)
            except Exception:
                pass