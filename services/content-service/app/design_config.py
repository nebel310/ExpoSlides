"""Версии ролей, внешние промпты и разрешённые модели нового workflow."""

from __future__ import annotations

import hashlib
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def _configs() -> tuple[dict[str, Any], dict[str, Any]]:
    workflow = tomllib.loads((ROOT / "agents/designer.toml").read_text(encoding="utf-8"))
    registry = tomllib.loads((ROOT / "config/models.toml").read_text(encoding="utf-8"))
    if workflow.get("schema_version") != "1.0" or registry.get("schema_version") != "1.0":
        raise ValueError("Неподдерживаемая версия конфигурации дизайнера")
    return workflow, registry


def role_config(role: str) -> dict[str, Any]:
    workflow, _ = _configs()
    config = dict(workflow["roles"][role])
    maximum_timeout = 240 if role == "story" else 180
    if not 1 <= config["attempts"] <= 3 or not 0 < config["timeout_seconds"] <= maximum_timeout:
        raise ValueError("Недопустимые ограничения роли дизайнера")
    return config


def model_for_role(role: str, configured_id: str | None = None) -> dict[str, Any]:
    """Проверить декларацию модели; содержимое удалённого endpoint не аттестуется."""
    _, registry = _configs()
    config = role_config(role)
    model = dict(registry["models"][config["model"]])
    if model["license"] not in registry["allowed_licenses"]:
        raise ValueError("Лицензия модели не разрешена конфигурацией соревнования")
    limit = registry[
        "max_image_parameters_billions" if config["task"] == "text-to-image"
        else "max_language_parameters_billions"
    ]
    if model["parameters_billions"] > limit or config["task"] not in model["tasks"]:
        raise ValueError("Модель не соответствует задаче или ограничению размера")
    if configured_id is not None and configured_id not in model["endpoint_aliases"]:
        raise ValueError("Модель endpoint отсутствует в проверенном реестре роли")
    return model


def role_prompt(role: str, name: str | None = None) -> str:
    config = role_config(role)
    relative = config["prompt"] if name is None else config["prompts"][name]
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Промпт должен находиться внутри репозитория")
    return path.read_text(encoding="utf-8")


def role_metadata(role: str, configured_id: str | None = None) -> dict[str, Any]:
    workflow, registry = _configs()
    model = model_for_role(role, configured_id)
    return {
        "workflow_id": workflow["id"], "workflow_version": workflow["version"],
        "role": role, "model": model["id"],
        "endpoint_model": configured_id or model["id"],
        "license": model["license"], "parameters_billions": model["parameters_billions"],
        "registry_version": registry["registry_version"],
        "prompt_sha256": hashlib.sha256(role_prompt(role).encode("utf-8")).hexdigest(),
    }
