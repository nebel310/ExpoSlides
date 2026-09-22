"""Уникальные ключи слайдов в ответе LLM при прежней внутренней модели плана."""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from pydantic import BaseModel, model_validator


def _resolve(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    reference = node.get("$ref")
    if reference is None:
        return node
    if not isinstance(reference, str) or not reference.startswith("#/"):
        raise ValueError("План должен использовать локальные JSON Schema references")
    result = schema
    for component in reference[2:].split("/"):
        result = result[component.replace("~1", "/").replace("~0", "~")]
    return result


def _slides_schema(schema: dict[str, Any], combined: bool) -> dict[str, Any]:
    owner = _resolve(schema, schema["properties"]["plan"]) if combined else schema
    return owner["properties"]["slides"]


def unique_plan_model(
    base_model: type[BaseModel],
    allowed_indices: Sequence[int],
    required_indices: Sequence[int],
    slide_limit: int,
    combined: bool,
) -> type[BaseModel]:
    """Меняет только формат ответа LLM; model_dump сохраняет канонический список.

    Старый список принимается для совместимости и проходит обычные проверки
    pipeline. Для нового объекта индексы и количество проверяются до конверсии.
    """
    allowed = tuple(allowed_indices)
    required = tuple(required_indices)
    if (
        not allowed
        or any(type(index) is not int or index <= 0 for index in (*allowed, *required))
        or len(set(allowed)) != len(allowed)
        or len(set(required)) != len(required)
        or not set(required) <= set(allowed)
        or type(slide_limit) is not int or slide_limit <= 0
    ):
        raise ValueError("Некорректные допустимые индексы или лимит слайдов")
    allowed_keys = {str(index) for index in allowed}
    required_keys = {str(index) for index in required}
    base_schema = base_model.model_json_schema()
    original_slides = _slides_schema(base_schema, combined)
    if original_slides.get("type") != "array":
        raise ValueError("Канонический план должен содержать список slides")
    allowed_item_keys = set(_resolve(base_schema, original_slides["items"])["properties"]) - {
        "template_slide_index",
    }
    minimum = max(1, len(required), original_slides.get("minItems", 1))
    maximum = min(slide_limit, len(allowed), original_slides.get("maxItems", slide_limit))
    if minimum > maximum:
        raise ValueError("Обязательные слайды не помещаются в лимит плана")

    class UniquePlanModel(base_model):
        @model_validator(mode="before")
        @classmethod
        def convert_keyed_slides(cls, value: Any) -> Any:
            if not isinstance(value, Mapping):
                return value
            plan = value.get("plan") if combined else value
            if not isinstance(plan, Mapping) or not isinstance(plan.get("slides"), Mapping):
                return value
            keyed = plan["slides"]
            if any(not isinstance(key, str) or key not in allowed_keys for key in keyed):
                raise ValueError("План содержит неизвестные ключи слайдов")
            if not required_keys <= keyed.keys():
                raise ValueError("План пропустил обязательные ключи слайдов")
            if not minimum <= len(keyed) <= maximum:
                raise ValueError("Количество ключей slides не соответствует лимиту плана")
            slides = []
            for key, item in keyed.items():
                if not isinstance(item, Mapping):
                    raise ValueError("Значение каждого ключа slides должно быть объектом")
                if "template_slide_index" in item:
                    raise ValueError("Индекс слайда задаётся ключом, не полем template_slide_index")
                if set(item) - allowed_item_keys:
                    raise ValueError("Объект слайда содержит неизвестные поля")
                slides.append({**item, "template_slide_index": int(key)})
            converted = {**plan, "slides": slides}
            return {**value, "plan": converted} if combined else converted

        @classmethod
        def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
            schema = deepcopy(base_model.model_json_schema(*args, **kwargs))
            slides = _slides_schema(schema, combined)
            item = deepcopy(_resolve(schema, slides["items"]))
            item["properties"].pop("template_slide_index", None)
            item["required"] = [key for key in item.get("required", [])
                                if key != "template_slide_index"]
            item["additionalProperties"] = False
            definitions = schema.setdefault("$defs", {})
            definition = "UniqueSlidePlanEntry"
            while definition in definitions:
                definition += "_"
            definitions[definition] = item
            slides.clear()
            slides.update({
                "type": "object",
                "properties": {
                    str(index): {"$ref": f"#/$defs/{definition}"} for index in allowed
                },
                "required": [str(index) for index in required],
                "additionalProperties": False,
                "minProperties": minimum,
                "maxProperties": maximum,
            })
            return schema

    UniquePlanModel.__name__ = f"Unique{base_model.__name__}"
    UniquePlanModel.__qualname__ = UniquePlanModel.__name__
    return UniquePlanModel
