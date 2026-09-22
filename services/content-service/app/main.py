from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
from pathlib import Path
from uuid import uuid4

from app.chains.llm import fast_llm_client
from app.config import settings, setup_logging
from app.errors import CONTENT_ERROR_EXIT_CODES, ContentValidationError, content_error_code
from app.graph.builder import build_graph
from app.models.graph_state import ContentGraphState
from app.models.request import GenerationSettings
from app.models.response import GenerationResponse, SlideContentResponse
from app.utils.presentation_parser import PresentationParser

logger = logging.getLogger(__name__)

SERVICE_ROOT = Path(__file__).resolve().parent.parent


async def serve() -> None:
    """Запустить gRPC-сервер и Kafka consumer в одном asyncio-loop"""
    from app.grpc.file_service_client import FileServiceClient
    from app.grpc.server import GrpcServer
    from app.kafka.consumer import KafkaConsumer
    from app.kafka.producer import KafkaProducer
    from app.services.content_pipeline import ContentPipeline

    setup_logging()

    file_client = FileServiceClient()
    producer = KafkaProducer()
    pipeline = ContentPipeline(file_client=file_client, producer=producer)
    consumer = KafkaConsumer(handler=pipeline.handle)
    grpc_server = GrpcServer(port=settings.content_service_port)

    stop_event = asyncio.Event()

    def _request_stop(*_: object) -> None:
        """Обработать сигнал остановки"""
        logger.info("Получен сигнал остановки")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            signal.signal(sig, _request_stop)

    logger.info("Запуск content-service")
    await file_client.start()
    await producer.start()
    await grpc_server.start()
    await consumer.start()

    consumer_task = asyncio.create_task(consumer.run(), name="kafka-consumer")

    try:
        await stop_event.wait()
    finally:
        logger.info("Остановка content-service")
        consumer_task.cancel()
        try:
            await consumer_task
        except (asyncio.CancelledError, Exception):
            pass
        await consumer.stop()
        await grpc_server.stop()
        await producer.stop()
        await file_client.stop()


async def run(
    template_json: str | Path,
    script_file: str | Path,
    output_json: str | Path,
    generation_settings: GenerationSettings | None = None,
    user_mapping: dict | None = None,
) -> Path:
    """Сгенерировать и атомарно сохранить контент презентации"""
    template_path = Path(template_json).expanduser().resolve()
    script_path = Path(script_file).expanduser().resolve()
    output_path = Path(output_json).expanduser().resolve()

    if output_path in {template_path, script_path}:
        raise ValueError("Путь результата должен отличаться от путей входных файлов")

    if not template_path.is_file():
        raise FileNotFoundError(f"Presentation JSON не найден: {template_path}")
    if not script_path.is_file():
        raise FileNotFoundError(f"Файл исходного текста не найден: {script_path}")
    if template_path.suffix.casefold() != ".json":
        raise ValueError(f"Ожидался входной файл .json: {template_path}")
    if script_path.suffix.casefold() != ".txt":
        raise ValueError(f"Ожидался файл сценария .txt: {script_path}")
    if output_path.suffix.casefold() != ".json":
        raise ValueError(f"Ожидался выходной файл .json: {output_path}")

    logger.info("Чтение входных данных")
    template = json.loads(template_path.read_text(encoding="utf-8"))
    script = script_path.read_text(encoding="utf-8")
    if not script.strip():
        raise ValueError("Исходный текст презентации пуст")

    logger.info("Парсинг презентации из JSON")
    presentation = PresentationParser.parse(template)
    if not presentation.slides:
        raise ValueError("Presentation JSON не содержит слайдов")
    logger.debug(
        "Распарсенная презентация: %d слайдов, %d макетов",
        len(presentation.slides),
        len(presentation.layouts),
    )

    initial_state = ContentGraphState(
        presentation=presentation,
        script=script,
        user_mapping=user_mapping,
        settings=generation_settings or GenerationSettings(),
    )

    logger.info("Построение графа")
    graph = build_graph()

    logger.info("Запуск графа")
    try:
        result = await graph.ainvoke(initial_state)
    finally:
        if initial_state.settings.generation_mode == "fast":
            await fast_llm_client.aclose()
    result_state = ContentGraphState(**result)
    logger.info("Граф завершил работу")

    if not result_state.validation or not result_state.validation.ok:
        issues = result_state.validation.issues if result_state.validation else []
        raise ContentValidationError(
            "Граф завершился без успешной валидации"
            + (": " + "; ".join(issues) if issues else "")
        )
    if not result_state.content:
        raise ContentValidationError("Граф не сгенерировал ни одного слайда")

    response_content = {
        idx: SlideContentResponse(placeholders=slide.placeholders, notes=None)
        for idx, slide in result_state.content.items()
    }
    response = GenerationResponse(
        content=response_content,
        validation_report=result_state.validation.model_dump(),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
    try:
        payload = json.dumps(response.model_dump(), ensure_ascii=False, indent=2)
        await asyncio.to_thread(temporary_path.write_text, payload, encoding="utf-8")
        await asyncio.to_thread(temporary_path.replace, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    logger.info("Результат сохранён в %s", output_path)
    return output_path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Content-service: Kafka pipeline или CLI-генерация")
    parser.add_argument("--cli", action="store_true", help="Запустить CLI-режим генерации")
    parser.add_argument("--template-json", type=Path, default=SERVICE_ROOT / "template.json")
    parser.add_argument("--script", type=Path, default=SERVICE_ROOT / "script.txt")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=SERVICE_ROOT / "generated_content.json",
    )
    parser.add_argument("--user-mapping", type=Path)
    parser.add_argument("--language", default="ru")
    parser.add_argument("--tone", default="professional")
    parser.add_argument("--complexity", default="medium")
    parser.add_argument("--max-slides", type=int)
    parser.add_argument("--generation-mode", choices=("standard", "fast"), default="standard")
    return parser.parse_args(argv)


def _load_user_mapping(path: Path | None) -> dict | None:
    if path is None:
        return None
    mapping_path = path.expanduser().resolve()
    if not mapping_path.is_file():
        raise FileNotFoundError(f"Файл пользовательской разметки не найден: {mapping_path}")
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    if not isinstance(mapping, dict):
        raise ValueError("Пользовательская разметка должна быть JSON-объектом")
    return mapping


def _run_cli(args: argparse.Namespace) -> int:
    """Запустить CLI-режим ручной генерации"""
    setup_logging()
    try:
        if (
            args.user_mapping is not None
            and args.output_json.expanduser().resolve()
            == args.user_mapping.expanduser().resolve()
        ):
            raise ValueError(
                "Путь результата должен отличаться от пути пользовательской разметки"
            )
        generation_settings = GenerationSettings(
            language=args.language,
            tone=args.tone,
            complexity=args.complexity,
            max_slides=args.max_slides,
            generation_mode=args.generation_mode,
        )
        user_mapping = _load_user_mapping(args.user_mapping)
        asyncio.run(
            run(
                args.template_json,
                args.script,
                args.output_json,
                generation_settings,
                user_mapping,
            )
        )
    except Exception as error:
        logger.error("Content-service завершился с ошибкой: %s", error)
        logger.debug("Детали ошибки content-service", exc_info=True)
        code = content_error_code(error, credentials_configured=bool(settings.llm_api_key.strip()))
        return CONTENT_ERROR_EXIT_CODES.get(code, 1)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Точка входа: CLI-режим или Kafka-пайплайн"""
    args = _parse_args(argv)
    if args.cli:
        return _run_cli(args)
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
