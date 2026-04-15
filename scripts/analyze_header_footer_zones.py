#!/usr/bin/env python3
"""
Analyse von Header- und Footerzonen in langen PDFs.

Untersucht das mittlere Drittel eines Dokuments und extrahiert
die Bounding Boxes potenzieller Header- und Footerbereiche.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from statistics import median
from typing import List, Tuple

import fitz  # PyMuPDF


def extract_text_blocks(page: fitz.Page):
    """Extrahiert Textblöcke aus einer Seite."""
    blocks = []
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text, *_ = block
        if text.strip():
            blocks.append((x0, y0, x1, y1, text.strip()))
    return blocks


def merge_horizontally(blocks: List[Tuple[float, float, float, float, str]],
                       tolerance: float = 5.0):
    """
    Verschmilzt horizontal überlappende Blöcke zu Bändern.
    """
    if not blocks:
        return []

    blocks = sorted(blocks, key=lambda b: b[0])
    merged = []
    current = list(blocks[0][:4])

    for x0, y0, x1, y1, _ in blocks[1:]:
        if x0 <= current[2] + tolerance:
            current[2] = max(current[2], x1)
            current[1] = min(current[1], y0)
            current[3] = max(current[3], y1)
        else:
            merged.append(tuple(current))
            current = [x0, y0, x1, y1]

    merged.append(tuple(current))
    return merged


def find_header_footer_candidates(page: fitz.Page):
    """Ermittelt Header- und Footer-Kandidaten einer Seite."""
    width = page.rect.width
    height = page.rect.height

    blocks = extract_text_blocks(page)

    top_blocks = [b for b in blocks if b[1] < height * 0.15]
    bottom_blocks = [b for b in blocks if b[3] > height * 0.85]

    header_bands = merge_horizontally(top_blocks)
    footer_bands = merge_horizontally(bottom_blocks)

    return header_bands, footer_bands


def analyze_pdf(pdf_path: Path):
    """Analysiert ein einzelnes PDF."""
    doc = fitz.open(pdf_path)
    page_count = len(doc)

    if page_count < 9:
        print(f"Übersprungen (zu kurz): {pdf_path}")
        return

    start = page_count // 3
    end = (page_count * 2) // 3

    headers = []
    footers = []

    print(f"\n📄 {pdf_path.name}")
    print(f"Seiten: {page_count} (Analyse: {start + 1}–{end})")

    for page_index in range(start, end):
        page = doc[page_index]
        header_bands, footer_bands = find_header_footer_candidates(page)

        headers.extend(header_bands)
        footers.extend(footer_bands)

    def summarize(bands):
        if not bands:
            return None
        y0 = median(b[1] for b in bands)
        y1 = median(b[3] for b in bands)
        return y0, y1

    header_summary = summarize(headers)
    footer_summary = summarize(footers)

    if header_summary:
        print(f"  Header-Zone: y0={header_summary[0]:.2f}, "
              f"y1={header_summary[1]:.2f}")
    else:
        print("  Kein stabiler Header erkannt")

    if footer_summary:
        print(f"  Footer-Zone: y0={footer_summary[0]:.2f}, "
              f"y1={footer_summary[1]:.2f}")
    else:
        print("  Kein stabiler Footer erkannt")

    doc.close()


def main():
    parser = argparse.ArgumentParser(
        description="Analyse von Header- und Footerzonen"
    )
    parser.add_argument(
        "pdf_root",
        type=Path,
        help="Verzeichnis mit PDFs"
    )
    parser.add_argument(
        "--min-pages",
        type=int,
        default=50,
        help="Minimale Seitenzahl für die Analyse"
    )
    args = parser.parse_args()

    pdf_files = sorted(args.pdf_root.rglob("*.pdf"))

    for pdf in pdf_files:
        try:
            doc = fitz.open(pdf)
            if len(doc) >= args.min_pages:
                doc.close()
                analyze_pdf(pdf)
            else:
                doc.close()
        except Exception as e:
            print(f"Fehler bei {pdf}: {e}")


if __name__ == "__main__":
    main()
