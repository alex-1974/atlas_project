from __future__ import annotations

from pathlib import Path

from atlas.models.records import DiscoveredPdf
from atlas.settings import load_settings


def get_literature_root() -> Path:
    settings = load_settings()
    raw = settings["paths"]["literature_root"]
    if not raw:
        raise ValueError("paths.literature_root is empty in Atlas config")
    return Path(raw).expanduser().resolve()


def discover_pdfs() -> list[DiscoveredPdf]:
    root = get_literature_root()
    found: list[DiscoveredPdf] = []

    for path in root.rglob("*.pdf"):
        rel = path.relative_to(root)
        top_category = rel.parts[0] if rel.parts else ""

        found.append(
            DiscoveredPdf(
                absolute_path=path,
                relative_path=rel,
                top_category=top_category,
                is_review_bucket=(top_category == "__review"),
                is_duplicate_bucket=(top_category == "__duplicates"),
            )
        )

    return found
