"""Публичные флаги готовности конфигурации, без ключей, URL и сетевых запросов."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from app.design_config import model_for_role


def capabilities(config: Any = None) -> dict[str, bool]:
    flags = {"generated_image": False, "contextual_audit": False, "story": False}
    try:
        if config is None:
            from app.config import settings

            config = settings
        base = urlsplit(config.llm_base_url)
        llm_ready = bool(
            config.llm_api_key.strip() and base.hostname and base.scheme in {"https", "http"}
        )
        if base.hostname == "router.huggingface.co":
            llm_ready = llm_ready and config.llm_api_key.startswith("hf_") and (
                len(config.llm_api_key) > 3
            )
        if llm_ready:
            for role, flag in (("story", "story"), ("contextual_auditor", "contextual_audit")):
                try:
                    model_for_role(role, config.llm_fast_model)
                except (KeyError, ValueError):
                    continue
                flags[flag] = True
        image_url = urlsplit(config.image_api_url)
        local = image_url.hostname in {"localhost", "127.0.0.1", "::1"}
        if config.image_api_key.strip() and image_url.hostname and (
            image_url.scheme == "https" or (local and image_url.scheme == "http")
        ) and not image_url.username and not image_url.password:
            try:
                model_for_role("image_illustrator", config.image_model)
            except (KeyError, ValueError):
                pass
            else:
                flags["generated_image"] = True
    except Exception:
        # Ошибки локальной конфигурации не раскрывают её содержимое публичному API.
        return {key: False for key in flags}
    return flags


def main() -> int:
    print(json.dumps(capabilities()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
