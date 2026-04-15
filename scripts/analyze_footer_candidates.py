#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import statistics
import sys

import pymupdf as fitz

from atlas.parse.geometry import PageBlock
from atlas.parse.zones import _build_horizontal_band_candidate


def extract_page_blocks(pdf_path: Path) -> tuple[list[PageBlock], float, float]:
    blocks: list[PageBlock] = []

    with fitz.open(pdf_path) as doc:
        if len(doc) == 0:
            raise ValueError(f"Empty PDF: {pdf_path}")

        first_page = doc.load_page(0)
        page_width = float(first_page.rect.width)
        page_height = float(first_page.rect.height)

        for page_index in range(len(doc)):
            page = doc.load_page(page_index)
            raw_blocks = page.get_text("blocks")

            for block_index, raw in enumerate(raw_blocks):
                x0, y0, x1, y1, text, _block_no, block_type = raw[:7]

                text = str(text or "").strip()
                if not text:
                    continue

                blocks.append(
                    PageBlock(
                        page_index=int(page_index),
                        block_index=int(block_index),
                        block_type=int(block_type),
                        x0=float(x0),
                        y0=float(y0),
                        x1=float(x1),
                        y1=float(y1),
                        text=text,
                    )
                )

    return blocks, page_width, page_height


def analyze_footer_candidates(pdf_path: Path) -> None:
    blocks, page_width, page_height = extract_page_blocks(pdf_path)

    print(f"\n📄 Datei: {pdf_path}")
    print(f"Seitenbreite: {page_width:.2f}, Seitenhöhe: {page_height:.2f}\n")

    page_map: dict[int, list[PageBlock]] = {}
    for block in blocks:
        page_map.setdefault(block.page_index, []).append(block)

    footer_positions: list[tuple[float, float]] = []
    footer_heights: list[float] = []

    for page_index in range(max(page_map.keys(), default=-1) + 1):
        page_blocks = page_map.get(page_index, [])

        band = _build_horizontal_band_candidate(
            page_blocks=page_blocks,
            page_width=page_width,
            page_height=page_height,
            side="bottom",
        )

        if band is None:
            print(f"Seite {page_index + 1}: Kein Footer-Kandidat gefunden.")
            continue

        # Unterstützt Tuple oder FurnitureBand
        if hasattr(band, "y0"):
            y0 = float(band.y0)
            y1 = float(band.y1)
            coverage = float(getattr(band, "coverage_ratio", 0.0))
        else:
            y0, y1, coverage = map(float, band)

        height = y1 - y0

        footer_positions.append((y0, y1))
        footer_heights.append(height)

        print(
            f"Seite {page_index + 1}: "
            f"y0={y0:.2f}, y1={y1:.2f}, "
            f"Höhe={height:.2f}, Coverage={coverage:.2f}"
        )

        print("  Enthaltene Blöcke:")
        found = False
        for b in page_blocks:
            if b.y0 >= y0 and b.y1 <= y1:
                txt = b.text.replace("\n", " ")
                print(
                    f"    - [{b.x0:.2f}, {b.y0:.2f}, {b.x1:.2f}, {b.y1:.2f}] "
                    f"→ '{txt[:120]}'"
                )
                found = True
        if not found:
            print("    - Keine Blöcke vollständig innerhalb des Kandidatenbands.")

    if footer_positions:
        y0_vals = [p[0] for p in footer_positions]
        y1_vals = [p[1] for p in footer_positions]

        print("\n=== Statistik ===")
        print(f"Anzahl Footer-Kandidaten: {len(footer_positions)}")
        print(f"Ø y0: {statistics.mean(y0_vals):.2f}")
        print(f"Ø y1: {statistics.mean(y1_vals):.2f}")
        print(f"Ø Höhe: {statistics.mean(footer_heights):.2f}")

        if len(y0_vals) > 1:
            print(f"Std-Abweichung y0: {statistics.stdev(y0_vals):.2f}")
            print(f"Std-Abweichung y1: {statistics.stdev(y1_vals):.2f}")
            print(f"Std-Abweichung Höhe: {statistics.stdev(footer_heights):.2f}")
    else:
        print("\nKeine Footer-Kandidaten erkannt.")


def main() -> int:
    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1]).expanduser().resolve()
    else:
        pdf_input = input("PDF-Pfad: ").strip()
        pdf_path = Path(pdf_input).expanduser().resolve()

    if not pdf_path.exists():
        print(f"Datei nicht gefunden: {pdf_path}", file=sys.stderr)
        return 1

    analyze_footer_candidates(pdf_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
