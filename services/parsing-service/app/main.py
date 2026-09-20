from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.grpc.file_service_client import FileServiceClient
from app.grpc.server import GrpcServer
from app.kafka.consumer import TaskCreatedConsumer
from app.kafka.producer import KafkaProducer
from app.parsers.pptx_parser import PPTXParser
from app.services.parser_pipeline import ParserPipeline

logger = logging.getLogger(__name__)

SERVICE_ROOT = Path(__file__).resolve().parent.parent


async def run_cli(input_pptx: str | Path, output_json: str | Path) -> Path:
    """Разобрать PPTX и атомарно записать его JSON-представление"""
    input_path = Path(input_pptx).expanduser().resolve()
    output_path = Path(output_json).expanduser().resolve()

    if not input_path.is_file():
        raise FileNotFoundError(f"PPTX-шаблон не найден: {input_path}")
    if input_path.suffix.casefold() != ".pptx":
        raise ValueError(f"Ожидался файл .pptx: {input_path}")
    if output_path.suffix.casefold() != ".json":
        raise ValueError(f"Ожидался выходной файл .json: {output_path}")

    presentation = await PPTXParser.parse(input_path)
    payload = presentation.model_dump_json(indent=2)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
    try:
        await asyncio.to_thread(temporary_path.write_text, payload, encoding="utf-8")
        await asyncio.to_thread(temporary_path.replace, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    logger.info("JSON сохранён: %s", output_path)
    return output_path


# Совместимость с публичным файловым API до добавления сетевого режима.
run = run_cli


async def run_service() -> None:
    """Запускает gRPC-сервер, Kafka producer и consumer в одном loop"""
    file_client = FileServiceClient(
        host=settings.file_service_grpc_host,
        port=settings.file_service_grpc_port,
    )
    await file_client.connect()

    pipeline = ParserPipeline(file_client)
    producer = KafkaProducer(settings.kafka_bootstrap_servers)
    await producer.start()

    consumer = TaskCreatedConsumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_group_id,
        topic_created=settings.kafka_topic_task_created,
        topic_parsed=settings.kafka_topic_task_parsed,
        topic_failed=settings.kafka_topic_task_failed,
        pipeline=pipeline,
        producer=producer,
    )
    await consumer.start()

    grpc_server = GrpcServer(settings.parser_service_port)
    await grpc_server.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    consumer_task = asyncio.create_task(consumer.run(), name="parser-consumer")
    stop_task = asyncio.create_task(stop_event.wait(), name="parser-stop")

    try:
        await asyncio.wait(
            {consumer_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        await consumer.stop()
        if not consumer_task.done():
            consumer_task.cancel()
            try:
                await consumer_task
            except (asyncio.CancelledError, Exception):
                pass
        stop_task.cancel()
        await grpc_server.stop()
        await producer.stop()
        await file_client.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="parser-service")
    parser.add_argument("--input-pptx", type=Path, default=None)
    parser.add_argument("--output-json", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )
    args = _parse_args(argv)

    if args.input_pptx is not None and args.output_json is not None:
        try:
            asyncio.run(run_cli(args.input_pptx, args.output_json))
        except Exception as error:
            logger.error("CLI-парсинг упал: %s", error)
            logger.debug("Детали", exc_info=True)
            return 1
        return 0

    if args.input_pptx is not None or args.output_json is not None:
        logger.error("Нужно указать и --input-pptx, и --output-json")
        return 2

    try:
        asyncio.run(run_service())
    except KeyboardInterrupt:
        logger.info("parser-service остановлен")
    except Exception as error:
        logger.exception("parser-service упал: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
