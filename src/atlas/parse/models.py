from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Identifier:
    kind: str
    value: str
    source: str | None = None
    confidence: float | None = None


@dataclass(slots=True)
class SectionNode:
    title: str
    level: int
    start_page: int | None = None
    end_page: int | None = None
    children: list["SectionNode"] = field(default_factory=list)


@dataclass(slots=True)
class TextSegment:
    text: str
    page: int | None = None
    kind: str = "paragraph"
    bbox: tuple[float, float, float, float] | None = None


@dataclass(slots=True)
class ReferenceEntry:
    raw: str
    doi: str | None = None
    title: str | None = None
    year: str | None = None
    authors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MetadataResult:
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: str | None = None
    abstract: str | None = None
    document_type: str | None = None


@dataclass(slots=True)
class ParseResult:
    source_path: str
    metadata: MetadataResult = field(default_factory=MetadataResult)
    identifiers: list[Identifier] = field(default_factory=list)
    sections: list[SectionNode] = field(default_factory=list)
    text_segments: list[TextSegment] = field(default_factory=list)
    references: list[ReferenceEntry] = field(default_factory=list)
    zones: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
