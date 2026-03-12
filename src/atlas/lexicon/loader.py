from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LexiconEntry:
    term: str
    lang: str
    category: str
    weight: float
    match: str
    scope: str


def _lexicon_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "lexicons"


def _normalize_text(text: str) -> str:
    return " ".join((text or "").casefold().split())


def _load_csv(path: Path) -> list[LexiconEntry]:
    entries: list[LexiconEntry] = []

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)

        required = {"term", "lang", "category", "weight", "match", "scope"}
        missing = required.difference(reader.fieldnames or set())
        if missing:
            raise ValueError(f"{path.name}: missing columns: {sorted(missing)}")

        for row in reader:
            term = _normalize_text(row["term"])
            if not term:
                continue

            entries.append(
                LexiconEntry(
                    term=term,
                    lang=_normalize_text(row["lang"]),
                    category=_normalize_text(row["category"]),
                    weight=float(row["weight"]),
                    match=_normalize_text(row["match"]),
                    scope=_normalize_text(row["scope"]),
                )
            )

    return entries


@lru_cache(maxsize=1)
def load_all_lexicon_entries() -> tuple[LexiconEntry, ...]:
    base = _lexicon_dir()
    if not base.exists():
        return ()

    entries: list[LexiconEntry] = []
    for path in sorted(base.glob("*.csv")):
        entries.extend(_load_csv(path))

    return tuple(entries)


def get_lexicon_entries(scope: str | None = None) -> list[LexiconEntry]:
    entries = list(load_all_lexicon_entries())

    if scope is None:
        return entries

    scope_norm = _normalize_text(scope)
    return [
        entry
        for entry in entries
        if entry.scope == "all" or entry.scope == scope_norm
    ]


def score_lexicon_hits(text: str, scope: str) -> tuple[float, list[LexiconEntry]]:
    """
    Return:
        (total_weight, matched_entries)

    Matching behavior:
    - token: exact token hit in normalized whitespace-tokenized text
    - substring: term appears anywhere in normalized text
    - phrase: normalized phrase appears anywhere in normalized text
    """
    norm = _normalize_text(text)
    if not norm:
        return 0.0, []

    tokens = set(norm.split())
    total = 0.0
    matched: list[LexiconEntry] = []

    for entry in get_lexicon_entries(scope=scope):
        hit = False

        if entry.match == "token":
            hit = entry.term in tokens
        elif entry.match == "substring":
            hit = entry.term in norm
        elif entry.match == "phrase":
            hit = entry.term in norm
        else:
            continue

        if hit:
            total += entry.weight
            matched.append(entry)

    return total, matched


def summarize_matches(matches: list[LexiconEntry]) -> dict[str, float]:
    out: dict[str, float] = {}

    for entry in matches:
        out[entry.category] = out.get(entry.category, 0.0) + entry.weight

    return out
