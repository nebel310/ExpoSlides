"""Постоянный каталог веб-интерфейса; содержимое файлов находится в file-service."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from exposlides.file_storage import StorageError, StoredFile

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$")]


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SlideMetadata(CatalogModel):
    index: int = Field(ge=1)
    title: str
    texts: list[str]
    placeholder_count: int = Field(ge=0)


class PresentationMetadata(CatalogModel):
    id: Identifier
    name: str
    slide_count: int = Field(ge=1, le=250)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    slides: list[SlideMetadata]

    @model_validator(mode="after")
    def check_slides(self) -> PresentationMetadata:
        if [slide.index for slide in self.slides] != list(range(1, self.slide_count + 1)):
            raise ValueError("Нарушен порядок слайдов в каталоге")
        return self


class FileReference(CatalogModel):
    file_id: str = Field(min_length=1, max_length=256)
    version: int = Field(ge=1, le=2**31 - 1)

    def stored_file(self) -> StoredFile:
        return StoredFile(file_id=self.file_id, version=self.version)


class TemplateRecord(CatalogModel):
    metadata: PresentationMetadata
    file: FileReference


class ResultRecord(TemplateRecord):
    template_id: Identifier
    max_slides: int | None = Field(default=None, ge=1, le=250)


class Library(CatalogModel):
    version: Literal[1] = 1
    templates: dict[Identifier, TemplateRecord] = Field(default_factory=dict)
    jobs: dict[Identifier, ResultRecord] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_references(self) -> Library:
        for identifier, record in [*self.templates.items(), *self.jobs.items()]:
            if record.metadata.id != identifier:
                raise ValueError("Идентификаторы каталога не совпадают")
        if any(record.template_id not in self.templates for record in self.jobs.values()):
            raise ValueError("Не найден шаблон сохранённой презентации")
        return self


class WebCatalog:
    """Атомарная запись каталога и запрет одновременной работы двух веб-процессов."""

    def __init__(self, directory: Path) -> None:
        self._lock = None
        try:
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.path = directory / "library.json"
            self._lock = (directory / "library.lock").open("a", encoding="utf-8")
            fcntl.flock(self._lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.library = (
                Library.model_validate_json(self.path.read_text(encoding="utf-8"))
                if self.path.exists() else Library()
            )
        except BlockingIOError as error:
            self.close()
            raise StorageError("Каталог уже используется другим процессом ExpoSlides.") from error
        except (OSError, UnicodeError, ValidationError) as error:
            self.close()
            raise StorageError(
                "Не удалось открыть каталог хранилища. Проверьте каталог и права доступа."
            ) from error

    def save_template(self, identifier: str, metadata: dict, file: StoredFile) -> None:
        record = TemplateRecord(
            metadata=PresentationMetadata.model_validate(metadata),
            file=FileReference(file_id=file.file_id, version=file.version),
        )
        library = self.library.model_copy(deep=True)
        library.templates[identifier] = record
        self._save(library)

    def save_result(
        self, identifier: str, metadata: dict, file: StoredFile,
        *, template_id: str, max_slides: int | None,
    ) -> None:
        record = ResultRecord(
            metadata=PresentationMetadata.model_validate(metadata),
            file=FileReference(file_id=file.file_id, version=file.version),
            template_id=template_id, max_slides=max_slides,
        )
        library = self.library.model_copy(deep=True)
        library.jobs[identifier] = record
        self._save(library)

    def _save(self, library: Library) -> None:
        temporary: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(prefix=".library-", dir=self.path.parent)
            temporary = Path(name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(library.model_dump(), stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            self.library = library
        except OSError as error:
            raise StorageError("Не удалось сохранить каталог. Проверьте доступное место.") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def close(self) -> None:
        if self._lock is not None:
            self._lock.close()
            self._lock = None
