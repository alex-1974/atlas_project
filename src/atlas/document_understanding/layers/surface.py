from __future__ import annotations

import re


URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b\S+@\S+\.\S+\b")
DOI_RE = re.compile(r"\b10\.\d{4,9}/\S+\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(?:1[5-9]\d{2}|20\d{2})\b")


def _sentence_count(text: str) -> int:
    if not text:
        return 0
    parts = re.split(r"[.!?]+", text)
    return len([p for p in parts if p.strip()])


def _density(text: str, predicate) -> float:
    if not text:
        return 0.0
    count = sum(1 for ch in text if predicate(ch))
    return count / max(1, len(text))


def compute_surface(repo, document_id: str) -> None:
    blocks = repo.fetch_blocks(document_id)
    rows: list[dict] = []

    for block in blocks:
        text = block.get("text") or ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        inline = " ".join(lines)
        words = inline.split()

        rows.append(
            {
                "block_id": block["block_id"],
                "char_count": len(inline),
                "word_count": len(words),
                "sentence_count": _sentence_count(inline),
                "line_count": len(lines),
                "mean_line_length": (sum(len(ln) for ln in lines) / len(lines)) if lines else 0.0,
                "line_width_ratio": None,
                "capitalization_ratio": _density(inline, str.isupper),
                "punctuation_density": _density(inline, lambda c: c in ".,;:!?()[]{}'\"-"),
                "digit_density": _density(inline, str.isdigit),
                "ends_with_period": inline.rstrip().endswith("."),
                "ends_with_colon": inline.rstrip().endswith(":"),
                "starts_with_number": bool(inline[:1].isdigit()),
                "starts_with_bullet": bool(inline[:1] in {"-", "*", "•"}),
                "contains_parentheses": "(" in inline or ")" in inline,
                "contains_brackets": "[" in inline or "]" in inline,
                "contains_url": bool(URL_RE.search(inline)),
                "contains_email": bool(EMAIL_RE.search(inline)),
                "contains_doi": bool(DOI_RE.search(inline)),
                "contains_year": bool(YEAR_RE.search(inline)),
                "is_all_caps": inline.isupper() if inline else False,
                "is_short_line": len(words) <= 6,
            }
        )

    repo.store_surface_features(document_id, rows)
