from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Block:
    block_index: int
    start_char: int
    end_char: int
    text: str
    page_index: int | None = None


@dataclass(frozen=True, slots=True)
class Region:
    region_index: int
    region_type: str
    start_char: int
    end_char: int
    text: str
    confidence: float
    page_start: int | None = None
    page_end: int | None = None
