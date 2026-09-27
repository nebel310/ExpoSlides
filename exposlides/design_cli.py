"""Воспроизводимый запуск дизайнера с тремя вариантами без веб-интерфейса."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from exposlides.design_models import DesignRequest
from exposlides.design_pipeline import DesignPipeline, save_model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--request", type=Path, help="JSON DesignRequest, включая datasets")
    inputs.add_argument("--script", type=Path, help="Материалы UTF-8")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=["llm", "extractive"], default="llm")
    parser.add_argument("--slides", type=int, default=12)
    parser.add_argument("--contextual-audit", action="store_true")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args(argv)
    if not args.template.is_file():
        parser.error("Шаблон не найден")
    if not 1 <= args.timeout <= 300:
        parser.error("Лимит выполнения должен быть от 1 до 300 секунд")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("Укажите новый или пустой каталог результата")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pipeline = DesignPipeline(args.output_dir.resolve(), timeout=args.timeout,
                              progress=lambda stage: print(stage, flush=True))
    started = time.monotonic()
    try:
        request = (
            DesignRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
            if args.request else DesignRequest(
                script=args.script.read_text(encoding="utf-8"), mode=args.mode,
                slide_count=args.slides, contextual_audit=args.contextual_audit,
            )
        )
        profile, story = pipeline.plan(args.template.resolve(), request)
        variants = pipeline.build(args.template.resolve(), request, profile, story)
        result = {"status": "completed", "seconds": round(time.monotonic()-started, 3),
                  "variants": variants}
        save_model(args.output_dir / "result.json", result)
        print(json.dumps({"status": "completed", "output_dir": str(args.output_dir.resolve()),
                          "seconds": result["seconds"]}, ensure_ascii=False))
        return 0
    except (ValueError, RuntimeError, OSError) as error:
        save_model(args.output_dir / "result.json", {
            "status": "failed", "error": str(error),
            "seconds": round(time.monotonic()-started, 3),
        })
        print(str(error), file=sys.stderr)
        return 1
    finally:
        pipeline.close()


if __name__ == "__main__":
    raise SystemExit(main())
