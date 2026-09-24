import asyncio
import logging
from contextlib import asynccontextmanager

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import close_redis
from app.router import files, session, tasks
from app.router import ws as ws_module
from app.services.file_client import file_client
from app.services.kafka_consumer import kafka_consumer
from app.services.kafka_producer import kafka_producer
from app.services.sio_server import sio


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управляет жизненным циклом сервисов"""
    await file_client.start()
    await kafka_producer.start()
    await kafka_consumer.start()
    consumer_task = asyncio.create_task(kafka_consumer.run(), name="kafka-consumer")
    try:
        yield
    finally:
        await kafka_consumer.stop()
        consumer_task.cancel()
        try:
            await consumer_task
        except (asyncio.CancelledError, Exception):
            pass
        await kafka_producer.stop()
        await file_client.stop()
        await close_redis()


fastapi_app = FastAPI(title="ExpoSlides Gateway", lifespan=lifespan)
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
fastapi_app.include_router(session.router)
fastapi_app.include_router(tasks.router)
fastapi_app.include_router(files.router)


@fastapi_app.get("/health")
async def health() -> dict[str, str]:
    """Проверка живости сервиса"""
    return {"status": "ok"}


asgi_app = socketio.ASGIApp(
    sio,
    other_asgi_app=fastapi_app,
    socketio_path="ws",
)