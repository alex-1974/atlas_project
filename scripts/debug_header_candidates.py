#!/usr/bin/env python3
from pathlib import Path
import argparse
import fitz  # PyMuPDF

from atlas.parse.geometry import PageBlock
from atlas.parse.zones import (
    _build_horizontal_bands_from_blocks,
    _page_band_search_blocks,
)


def extract_page_blocks(pdf_path: Path) -> tuple[list[PageBlock], float, float]:
    """Extrahiert Textblöcke aus einem PDF."""
    doc = fitz.open(pdf_path)
    blocks: list[PageBlock] = []

    page_width = 0.0
    page_height = 0.0

    for page_index, page in enumerate(doc):
        rect = page.rect
        page_width = rect.width
        page_height = rect.height

        for block_index, block in enumerate(page.get_text("blocks")):
            x0, y0, x1, y1, text, *_ = block
            text = text.strip()
            if not text:
                continue

            blocks.append(
                PageBlock(
                    page_index=page_index,
                    block_index=block_index,
                    block_type=0,
                    x0=float(x0),
                    y0=float(y0),
                    x1=float(x1),
                    y1=float(y1),
                    text=text,
                )
            )

    doc.close()
    return blocks, page_width, page_height


def debug_header_candidates(pdf_path: Path):
    blocks, page_width, page_height = extract_page_blocks(pdf_path)

    page_map = {}
    for block in blocks:
        page_map.setdefault(block.page_index, []).append(block)

    print(f"\n📄 Datei: {pdf_path}")
    print(f"Seitenhöhe: {page_height:.2f}, Seitenbreite: {page_width:.2f}\n")

    for page_index, page_blocks in sorted(page_map.items()):
        print(f"\n=== Seite {page_index + 1} ===")

        # Nur obere Blöcke als Header-Kandidaten betrachten
        header_search_blocks = _page_band_search_blocks(
            page_blocks, page_height, side="top"
        )

        bands = _build_horizontal_bands_from_blocks(
            header_search_blocks,
            page_height=page_height,
        )

        if not bands:
            print("Kein Header-Kandidat gefunden.")
            continue

        # Oberstes Band ist der Header-Kandidat
        x0, y0, x1, y1, count = bands[0]
        height = y1 - y0
        coverage = (x1 - x0) / page_width

        print(
            f"Header-Kandidat: "
            f"x0={x0:.2f}, y0={y0:.2f}, "
            f"x1={x1:.2f}, y1={y1:.2f}, "
            f"Höhe={height:.2f}, Coverage={coverage:.2f}"
        )

        print("Enthaltene Blöcke:")
        for block in header_search_blocks:
            if block.y0 >= y0 - 1 and block.y1 <= y1 + 1:
                print(
                    f"  - Block {block.block_index}: "
                    f"[{block.x0:.2f}, {block.y0:.2f}, "
                    f"{block.x1:.2f}, {block.y1:.2f}] "
                    f"→ {block.text[:120]!r}"
                )


def main():
    parser = argparse.ArgumentParser(
        description="Debug Header-Kandidaten in PDFs"
    )
    parser.add_argument("pdf", type=Path, help="Pfad zur PDF-Datei")
    args = parser.parse_args()

    debug_header_candidates(args.pdf)


if __name__ == "__main__":
    main()
