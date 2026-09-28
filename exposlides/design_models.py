"""Версионируемый контракт содержания, верстки и аудита цифрового дизайнера."""

from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DESIGN_SCHEMA_VERSION = "1.0"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Box(Contract):
    left: int
    top: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class TextStyle(Contract):
    font: str = "Arial"
    size: float = Field(default=20, ge=6, le=160)
    color: str = Field(default="202124", pattern=r"^[0-9A-Fa-f]{6}$")
    bold: bool = False


class Slot(Contract):
    element_id: str
    shape_id: int
    box: Box
    role: Literal["title", "body", "protected", "page_number"]
    text: str = ""
    style: TextStyle = Field(default_factory=TextStyle)
    paragraph_font_sizes: list[float] = Field(default_factory=list)


class SlidePattern(Contract):
    source_slide_index: int = Field(ge=1)
    layout_index: int | None = None
    name: str
    slots: list[Slot]
    content_box: Box
    palette: list[str]
    font: str
    title_style: TextStyle
    body_style: TextStyle
    protected_shape_ids: list[int] = Field(default_factory=list)
    visual_shape_ids: dict[str, list[int]] = Field(default_factory=dict)
    mutable_shape_ids: list[int] = Field(default_factory=list)
    protected_regions: list[Box] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TemplateProfile(Contract):
    schema_version: Literal["1.0"] = DESIGN_SCHEMA_VERSION
    template_sha256: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    patterns: list[SlidePattern] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class SourceExcerpt(Contract):
    id: str
    text: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    required: bool = True


class Dataset(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    name: str
    columns: list[str] = Field(min_length=2, max_length=20)
    rows: list[list[str | float | int]] = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1)
    unit: str = ""

    @model_validator(mode="after")
    def rectangular(self):
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("Названия столбцов должны быть уникальны")
        for row in self.rows:
            if len(row) != len(self.columns):
                raise ValueError("Количество ячеек должно совпадать с числом столбцов")
            if any(isinstance(v, float) and not math.isfinite(v) for v in row):
                raise ValueError("Данные содержат нечисловое значение")
        return self


class VisualRequest(Contract):
    source_shape_id: int | None = Field(default=None, ge=1)
    icon: Literal["arrow", "check", "info"] = "arrow"
    kind: Literal["table", "bar", "line", "pie", "process", "comparison", "smartart", "icon"]
    dataset_id: str | None = None
    labels: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def data_required(self):
        if self.kind in {"table", "bar", "line", "pie"} and not self.dataset_id:
            raise ValueError("Таблица и график должны ссылаться на набор исходных данных")
        if self.kind in {"process", "comparison", "smartart"} and len(self.labels) < 2:
            raise ValueError("Схема должна содержать минимум два элемента")
        return self


class StorySlide(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    title: str = Field(min_length=1, max_length=180)
    paragraphs: list[str] = Field(min_length=1, max_length=12)
    source_ids: list[str] = Field(min_length=1)
    visual: VisualRequest | None = None
    notes: str = ""


class ContentPlan(Contract):
    schema_version: Literal["1.0"] = DESIGN_SCHEMA_VERSION
    title: str
    slides: list[StorySlide] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [slide.id for slide in self.slides]
        if len(ids) != len(set(ids)):
            raise ValueError("Идентификаторы выходных слайдов должны быть уникальны")
        return self


class ImageGenerationRequest(Contract):
    enabled: bool = False
    prompt: str = Field(default="", max_length=4000)
    seed: int = Field(default=0, ge=0, le=2147483647)
    width: int = Field(default=1024, ge=256, le=1536)
    height: int = Field(default=576, ge=256, le=1536)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    palette: list[str] = Field(default_factory=list, max_length=12)
    slide_id: str | None = None

    @model_validator(mode="after")
    def validate_enabled(self):
        if self.enabled and not self.prompt.strip():
            raise ValueError("Для иллюстрации нужно описание")
        if self.width % 16 or self.height % 16:
            raise ValueError("Размер иллюстрации должен быть кратен 16")
        if any(not re.fullmatch(r"[0-9A-Fa-f]{6}", color) for color in self.palette):
            raise ValueError("Палитра иллюстрации должна содержать цвета HEX без #")
        return self


class DesignRequest(Contract):
    script: str = Field(min_length=1, max_length=100_000)
    purpose: str = Field(default="Объяснить главное и предложить следующий шаг", max_length=1000)
    audience: str = Field(default="Коллеги", max_length=500)
    slide_count: int = Field(default=12, ge=1, le=50)
    count_mode: Literal["exact", "maximum"] = "exact"
    language: str = Field(default="ru", max_length=30)
    mode: Literal["llm", "extractive"] = "llm"
    contextual_audit: bool = False
    generated_image: ImageGenerationRequest = Field(default_factory=ImageGenerationRequest)
    required_messages: list[str] = Field(default_factory=list, max_length=50)
    datasets: list[Dataset] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def nonblank(self):
        if not self.script.strip():
            raise ValueError("Добавьте исходные материалы")
        if len({d.id for d in self.datasets}) != len(self.datasets):
            raise ValueError("Идентификаторы наборов данных должны быть уникальны")
        return self


class PlacedBlock(Contract):
    image_path: str | None = None
    source_shape_id: int | None = Field(default=None, ge=1)
    icon: Literal["arrow", "check", "info"] = "arrow"
    id: str
    kind: Literal["title", "text", "table", "chart", "process", "comparison", "page_number", "smartart", "icon", "image"]
    box: Box
    style: TextStyle
    text: str = ""
    items: list[str] = Field(default_factory=list)
    dataset_id: str | None = None
    chart_type: Literal["bar", "line", "pie"] | None = None
    fill: str | None = Field(default=None, pattern=r"^[0-9A-Fa-f]{6}$")
    source_ids: list[str] = Field(default_factory=list)


    @model_validator(mode="after")
    def image_reference(self):
        if self.kind == "image" and not self.image_path:
            raise ValueError("Изображение должно ссылаться на локальный файл")
        if self.kind != "image" and self.image_path is not None:
            raise ValueError("Путь изображения допустим только для блока image")
        return self


class SlideInstance(Contract):
    id: str
    story_slide_id: str
    source_slide_index: int = Field(ge=1)
    blocks: list[PlacedBlock] = Field(min_length=1)
    remove_shape_ids: list[int] = Field(default_factory=list)
    notes: str = ""


class DeckPlan(Contract):
    schema_version: Literal["1.0"] = DESIGN_SCHEMA_VERSION
    variant_id: Literal["story", "evidence", "cards"]
    name: str
    description: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    slides: list[SlideInstance] = Field(min_length=1, max_length=50)
    datasets: list[Dataset] = Field(default_factory=list)

    @model_validator(mode="after")
    def references(self):
        ids = [slide.id for slide in self.slides]
        if len(ids) != len(set(ids)):
            raise ValueError("Повторный идентификатор экземпляра слайда")
        datasets = {d.id for d in self.datasets}
        for slide in self.slides:
            block_ids = [b.id for b in slide.blocks]
            if len(block_ids) != len(set(block_ids)):
                raise ValueError("Повторный идентификатор объекта")
            for block in slide.blocks:
                if block.kind in {"table", "chart"} and block.dataset_id not in datasets:
                    raise ValueError("Неизвестный набор данных")
        return self


class AuditIssue(Contract):
    id: str
    rule: str
    rule_version: str = "1.0"
    check_type: Literal["deterministic", "contextual"] = "deterministic"
    severity: Literal["error", "warning", "info"]
    slide_id: str
    block_id: str | None = None
    box: Box | None = None
    message: str
    evidence: str = ""
    source_ids: list[str] = Field(default_factory=list)
    fix: Literal["fit_text", "move_inside", "palette", "none"] = "none"


class AuditReport(Contract):
    schema_version: Literal["1.0"] = DESIGN_SCHEMA_VERSION
    issues: list[AuditIssue] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)
    contextual_status: Literal["not_run", "completed", "failed"] = "not_run"
    limitations: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)
