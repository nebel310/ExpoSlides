from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from pptx import Presentation as PPTXPresentation

from exposlides.image_api import ImageGenerationError
from exposlides.images import illustrate_presentation

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
SERVICE_DIRECTORIES = {
    "parser": REPOSITORY_ROOT / "services" / "parsing-service",
    "content": REPOSITORY_ROOT / "services" / "content-service",
    "builder": REPOSITORY_ROOT / "services" / "builder-service",
}
STAGE_LABELS = {
    "parser": "парсинг шаблона",
    "content": "генерация контента",
    "builder": "сборка презентации",
    "images": "генерация изображений",
}
CONTENT_ERROR_CODES = {
    20: "invalid_response",
    21: "content_validation",
    22: "timeout",
    23: "auth",
    24: "network",
}
CONTENT_ERROR_MARKER = "EXPOSLIDES_CONTENT_ERROR="


class PipelineError(RuntimeError):
    """Ошибка входных данных, отдельного этапа или итоговой проверки pipeline."""

    def __init__(
        self, message: str, *, stage: str | None = None, error_code: str | None = None,
    ) -> None:
        self.stage = stage
        self.error_code = error_code if error_code in CONTENT_ERROR_CODES.values() else "unknown"
        if stage is not None:
            message = f"Этап «{STAGE_LABELS.get(stage, stage)}»: {message}"
        super().__init__(message)


@dataclass(frozen=True)
class PipelineResult:
    """Успешный результат одного запуска pipeline."""

    output_path: Path
    artifacts_path: Path | None = None


def _absolute_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _validate_input_file(path: str | Path, *, label: str, suffix: str) -> Path:
    resolved = _absolute_path(path)
    if not resolved.is_file():
        raise PipelineError(f"{label} не найден или не является файлом: {resolved}")
    if resolved.suffix.lower() != suffix:
        raise PipelineError(f"{label} должен иметь расширение {suffix}: {resolved}")
    return resolved


def _validate_script(path: str | Path) -> Path:
    script_path = _validate_input_file(path, label="Файл сценария", suffix=".txt")
    try:
        script = script_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise PipelineError(
            f"Не удалось прочитать сценарий как UTF-8: {script_path}: {error}"
        ) from error
    if not script.strip():
        raise PipelineError(f"Файл сценария пуст: {script_path}")
    return script_path


def _validate_output_path(
    path: str | Path,
    *,
    template_path: Path,
    force: bool,
) -> Path:
    output_path = _absolute_path(path)
    if output_path.suffix.lower() != ".pptx":
        raise PipelineError(f"Результат должен иметь расширение .pptx: {output_path}")
    if output_path == template_path:
        raise PipelineError("Путь результата не должен совпадать с PPTX-шаблоном")
    if output_path.exists():
        if not output_path.is_file():
            raise PipelineError(f"Путь результата существует и не является файлом: {output_path}")
        if not force:
            raise PipelineError(
                f"Файл результата уже существует: {output_path}. "
                "Передайте --force для перезаписи."
            )
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PipelineError(
            f"Не удалось создать каталог результата {output_path.parent}: {error}"
        ) from error
    return output_path


@contextmanager
def _working_directory(artifacts_dir: str | Path | None) -> Iterator[tuple[Path, Path | None]]:
    if artifacts_dir is None:
        with tempfile.TemporaryDirectory(prefix="exposlides-") as temporary_directory:
            yield Path(temporary_directory), None
        return

    artifacts_root = _absolute_path(artifacts_dir)
    if artifacts_root.exists() and not artifacts_root.is_dir():
        raise PipelineError(
            f"Путь для артефактов существует и не является каталогом: {artifacts_root}"
        )
    try:
        artifacts_root.mkdir(parents=True, exist_ok=True)
        run_directory = Path(tempfile.mkdtemp(prefix="exposlides-", dir=artifacts_root))
    except OSError as error:
        raise PipelineError(
            f"Не удалось создать каталог промежуточных артефактов: {error}"
        ) from error
    yield run_directory, run_directory


def _run_stage(
    stage: str,
    arguments: Sequence[str],
    *,
    expected_output: Path,
    env: dict[str, str] | None = None,
) -> None:
    service_directory = SERVICE_DIRECTORIES[stage]
    if not service_directory.is_dir():
        raise PipelineError(
            f"каталог сервиса не найден: {service_directory}",
            stage=stage,
        )

    command = [sys.executable, "-m", "app.main", *arguments]
    try:
        completed = subprocess.run(
            command,
            cwd=service_directory,
            env=env,
            check=False,
        )
    except OSError as error:
        raise PipelineError(f"не удалось запустить процесс: {error}", stage=stage) from error

    if completed.returncode != 0:
        raise PipelineError(
            f"процесс завершился с кодом {completed.returncode}",
            stage=stage,
            error_code=CONTENT_ERROR_CODES.get(completed.returncode) if stage == "content" else None,
        )
    try:
        output_is_valid = expected_output.is_file() and expected_output.stat().st_size > 0
    except OSError as error:
        raise PipelineError(
            f"не удалось проверить выходной файл {expected_output}: {error}",
            stage=stage,
        ) from error
    if not output_is_valid:
        raise PipelineError(
            f"процесс не создал непустой файл {expected_output}",
            stage=stage,
        )


def _validate_template_json(path: Path) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PipelineError(f"сервис создал некорректный JSON: {error}", stage="parser") from error
    if not isinstance(data, dict):
        raise PipelineError("верхний уровень template JSON должен быть объектом", stage="parser")


def _read_content_slide_count(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PipelineError(f"сервис создал некорректный JSON: {error}", stage="content") from error
    if not isinstance(data, dict):
        raise PipelineError("верхний уровень content JSON должен быть объектом", stage="content")

    error_message = data.get("error")
    if error_message:
        raise PipelineError(f"сервис вернул ошибку: {error_message}", stage="content")
    content = data.get("content")
    if not isinstance(content, dict) or not content:
        raise PipelineError("сервис вернул пустой content", stage="content")
    return len(content)


def _create_staged_output(output_path: Path) -> Path:
    try:
        descriptor, staged_name = tempfile.mkstemp(
            prefix=f".{output_path.stem}-",
            suffix=".pptx",
            dir=output_path.parent,
        )
        os.close(descriptor)
    except OSError as error:
        raise PipelineError(f"Не удалось создать временный файл результата: {error}") from error
    return Path(staged_name)


def _publish_staged_output(staged_output: Path, output_path: Path, *, force: bool) -> None:
    """Атомарно публикует результат, не затирая конкурентный файл без --force."""
    try:
        if force:
            os.replace(staged_output, output_path)
        else:
            os.link(staged_output, output_path)
    except FileExistsError as error:
        raise PipelineError(
            f"Файл результата появился во время выполнения: {output_path}. "
            "Повторите запуск с --force, если его можно заменить."
        ) from error
    except OSError as error:
        raise PipelineError(
            f"Не удалось опубликовать результат {output_path}: {error}"
        ) from error

    if not force:
        try:
            staged_output.unlink(missing_ok=True)
        except OSError:
            # Итог уже опубликован атомарной hard-link операцией; оставшийся
            # временный файл не должен превращать успешный запуск в ошибку.
            pass


def _validate_built_pptx(path: Path, *, expected_slide_count: int) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            corrupt_member = archive.testzip()
    except (OSError, zipfile.BadZipFile) as error:
        raise PipelineError(f"создан некорректный PPTX/ZIP: {error}", stage="builder") from error
    if corrupt_member is not None:
        raise PipelineError(
            f"созданный PPTX содержит повреждённый файл: {corrupt_member}",
            stage="builder",
        )

    try:
        presentation = PPTXPresentation(str(path))
        actual_slide_count = len(presentation.slides)
    except Exception as error:
        raise PipelineError(
            f"созданный PPTX не открывается через python-pptx: {error}",
            stage="builder",
        ) from error
    if actual_slide_count != expected_slide_count:
        raise PipelineError(
            "число слайдов в результате не совпадает с generated content: "
            f"ожидалось {expected_slide_count}, получено {actual_slide_count}",
            stage="builder",
        )


def run_pipeline(
    *,
    template: str | Path,
    script: str | Path,
    output: str | Path,
    max_slides: int | None = None,
    artifacts_dir: str | Path | None = None,
    force: bool = False,
    generation_mode: str = "standard",
    image_mode: str = "auto",
) -> PipelineResult:
    """Запустить parser, content и builder последовательно в изолированных процессах."""
    template_path = _validate_input_file(template, label="PPTX-шаблон", suffix=".pptx")
    script_path = _validate_script(script)
    output_path = _validate_output_path(output, template_path=template_path, force=force)
    if max_slides is not None and max_slides < 1:
        raise PipelineError("max_slides должен быть положительным целым числом")
    if generation_mode not in {"standard", "fast"}:
        raise PipelineError("generation_mode должен быть standard или fast")
    if image_mode not in {"auto", "off"}:
        raise PipelineError("image_mode должен быть auto или off")

    staged_output: Path | None = None
    try:
        with _working_directory(artifacts_dir) as (work_directory, persisted_artifacts):
            template_json = work_directory / "template.json"
            content_json = work_directory / "generated_content.json"

            print("[1/3] Парсинг PPTX-шаблона", flush=True)
            _run_stage(
                "parser",
                [
                    "--input-pptx",
                    str(template_path),
                    "--output-json",
                    str(template_json),
                ],
                expected_output=template_json,
            )
            _validate_template_json(template_json)

            content_arguments = [
                "--cli",
                "--template-json",
                str(template_json),
                "--script",
                str(script_path),
                "--output-json",
                str(content_json),
                "--language",
                "ru",
                "--tone",
                "professional",
                "--complexity",
                "medium",
            ]
            if max_slides is not None:
                content_arguments.extend(["--max-slides", str(max_slides)])
            if generation_mode == "fast":
                content_arguments.extend(["--generation-mode", "fast"])

            content_environment = os.environ.copy()
            content_environment["LOG_FILE"] = str(work_directory / "content-service.log")
            content_environment["LOG_LEVEL"] = "INFO"
            print("[2/3] Генерация контента", flush=True)
            _run_stage(
                "content",
                content_arguments,
                expected_output=content_json,
                env=content_environment,
            )
            expected_slide_count = _read_content_slide_count(content_json)

            staged_output = _create_staged_output(output_path)
            print("[3/3] Сборка итогового PPTX", flush=True)
            _run_stage(
                "builder",
                [
                    "--template-pptx",
                    str(template_path),
                    "--template-json",
                    str(template_json),
                    "--content-json",
                    str(content_json),
                    "--output-pptx",
                    str(staged_output),
                ],
                expected_output=staged_output,
            )
            _validate_built_pptx(staged_output, expected_slide_count=expected_slide_count)

            try:
                if image_mode != "off":
                    print("[images] Подготовка изображений", flush=True)
                illustrate_presentation(
                    staged_output, template_json,
                    report_path=work_directory / "image_report.json", mode=image_mode,
                )
            except ImageGenerationError as error:
                raise PipelineError(str(error), stage="images") from error
            _validate_built_pptx(staged_output, expected_slide_count=expected_slide_count)

            _publish_staged_output(staged_output, output_path, force=force)
            staged_output = None
            return PipelineResult(
                output_path=output_path,
                artifacts_path=persisted_artifacts,
            )
    finally:
        if staged_output is not None:
            try:
                staged_output.unlink(missing_ok=True)
            except OSError:
                pass


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("значение должно быть положительным")
    return parsed


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m exposlides",
        description="Собрать PPTX из шаблона и текстового сценария через три этапа ExpoSlides.",
    )
    parser.add_argument("--template", required=True, type=Path, help="Исходный PPTX-шаблон")
    parser.add_argument("--script", required=True, type=Path, help="Сценарий в UTF-8 TXT")
    parser.add_argument("--output", required=True, type=Path, help="Итоговый PPTX")
    parser.add_argument(
        "--max-slides",
        type=_positive_int,
        help="Максимальное число выбранных слайдов",
    )
    parser.add_argument(
        "--generation-mode",
        choices=("standard", "fast"),
        default="standard",
        help="Режим текста: standard — по слайдам; fast — пакетная генерация",
    )
    parser.add_argument(
        "--image-mode", choices=("auto", "off"), default="auto",
        help="auto — иллюстрации через HF с LLM_API_KEY; off — сохранить картинки шаблона",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        help="Каталог, внутри которого сохранить отдельный набор промежуточных файлов запуска",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Атомарно заменить существующий итоговый PPTX после успешной проверки",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args(argv)
    try:
        result = run_pipeline(
            template=arguments.template,
            script=arguments.script,
            output=arguments.output,
            max_slides=arguments.max_slides,
            artifacts_dir=arguments.artifacts_dir,
            force=arguments.force,
            generation_mode=arguments.generation_mode,
            image_mode=arguments.image_mode,
        )
    except PipelineError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        if error.stage == "content":
            print(f"{CONTENT_ERROR_MARKER}{error.error_code}", file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print("Запуск прерван пользователем", file=sys.stderr)
        return 130

    print(f"Готово: {result.output_path}")
    if result.artifacts_path is not None:
        print(f"Промежуточные артефакты: {result.artifacts_path}")
    return 0
