#!/usr/bin/env python3
"""
inspect_pdf.py — erweitert mit Blockbreiten-Histogramm

Verwendung:
    python inspect_pdf.py <pdf> [--pages 1,2,3] [--widths]
"""
import argparse
import sys
from pathlib import Path
from collections import Counter

try:
    import pymupdf as fitz
except ImportError:
    import fitz


def inspect(pdf_path: Path, page_numbers: list[int], show_widths: bool = False) -> None:
    with fitz.open(pdf_path) as doc:
        total = len(doc)
        print(f"Datei:  {pdf_path.name}")
        print(f"Seiten: {total}")
        print(f"Breite: {doc[0].rect.width:.1f}pt  Höhe: {doc[0].rect.height:.1f}pt")
        print()

        all_widths: list[float] = []

        for page_num in page_numbers:
            page_index = page_num - 1
            if page_index < 0 or page_index >= total:
                print(f"Seite {page_num}: nicht vorhanden")
                continue

            page = doc.load_page(page_index)
            blocks = page.get_text("blocks")

            print(f"{'═'*70}")
            print(f"Seite {page_num} ({len(blocks)} Blöcke)")
            print(f"{'─'*70}")
            print(f"{'#':>3}  {'type':>4}  {'x0':>7}  {'y0':>7}  {'x1':>7}  {'y1':>7}  {'w':>7}  Text")
            print(f"{'─'*3}  {'─'*4}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*30}")

            for i, b in enumerate(blocks):
                x0, y0, x1, y1 = b[0], b[1], b[2], b[3]
                block_type = b[6]
                text = str(b[4]).strip().replace("\n", "↵")[:50] if block_type == 0 else "[IMAGE]"
                w = x1 - x0
                if block_type == 0 and str(b[4]).strip():
                    all_widths.append(round(w, 1))
                print(f"{i:>3}  {block_type:>4}  {x0:>7.1f}  {y0:>7.1f}  {x1:>7.1f}  {y1:>7.1f}  {w:>7.1f}  {text}")

            print()
            text_blocks = [b for b in blocks if b[6] == 0 and str(b[4]).strip()]
            if text_blocks:
                x0s = [b[0] for b in text_blocks]
                x1s = [b[2] for b in text_blocks]
                widths = sorted(set(round(b[2]-b[0], 1) for b in text_blocks))
                print(f"  Textblöcke: {len(text_blocks)}")
                print(f"  x0-Bereich: {min(x0s):.1f} – {max(x0s):.1f}")
                print(f"  x1-Bereich: {min(x1s):.1f} – {max(x1s):.1f}")
                print(f"  Breiten:    {widths}")
            print()

        if show_widths and all_widths:
            print(f"{'═'*70}")
            print(f"Blockbreiten über alle Seiten ({len(all_widths)} Blöcke)")
            print(f"{'─'*70}")
            counter = Counter(all_widths)
            for w, count in sorted(counter.items(), key=lambda x: -x[1])[:20]:
                bar = "█" * min(count, 40)
                print(f"  w={w:>7.1f}: {count:>4}  {bar}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--pages", default="4,5,6",
                        help="Kommagetrennte Seitenzahlen (1-basiert)")
    parser.add_argument("--widths", action="store_true",
                        help="Blockbreiten-Histogramm ausgeben")
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"Nicht gefunden: {args.pdf}")
        sys.exit(1)

    pages = [int(p.strip()) for p in args.pages.split(",")]
    inspect(args.pdf, pages, show_widths=args.widths)


if __name__ == "__main__":
    main()
