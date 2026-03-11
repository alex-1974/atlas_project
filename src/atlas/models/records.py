from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiscoveredPdf:
    absolute_path: Path
    relative_path: Path
    top_category: str
    is_review_bucket: bool
    is_duplicate_bucket: bool


@dataclass(frozen=True)
class SearchHit:
    score: float
    relative_path: str
    title: str
    segment_text: str


@dataclass(frozen=True)
class DocumentHit:
    score: float
    relative_path: str
    title: str
    best_snippet: str
