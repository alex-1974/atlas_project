#!/usr/bin/env python3
"""
test_geometry.py

Testet zones.py und vertical.py gegen echte PDFs.

Verwendung:
    python test_geometry.py <pdf1> [<pdf2> ...]
    python test_geometry.py --catalog <katalog_root>

Beispiel:
    python test_geometry.py ~/Literatur/paper.pdf
    python test_geometry.py --catalog ~/Programmiersprachen/Blender/bvillage_project/research/literature/

Ausgabe:
    Pro PDF: FurnitureProfile + VerticalProfile + seitenweise Abweichungen
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Pfad-Setup: atlas.parse aus src/ laden
# ---------------------------------------------------------------------------

def _setup_path() -> None:
    """Sucht src/atlas/parse/ relativ zum Skript oder im CWD."""
    candidates = [
        Path(__file__).parent / "src",
        Path.cwd() / "src",
        Path.home() / "Programmiersprachen/Python/atlas_project/src",
    ]
    for candidate in candidates:
        if (candidate / "atlas" / "parse").exists():
            sys.path.insert(0, str(candidate))
            print(f"[setup] atlas.parse gefunden: {candidate}")
            return
    print("[setup] WARNUNG: src/atlas/parse nicht gefunden — verwende installiertes Paket")

_setup_path()


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

try:
    from atlas.parse.geometry import build_document_geometry_profile
    from atlas.parse.zones import (
        FurnitureBand,
        FurnitureProfile,
        match_page_to_furniture_profile,
    )
    from atlas.parse.vertical import (
        VerticalProfile,
        match_page_to_vertical_profile,
    )
except ImportError as e:
    print(f"[FEHLER] Import fehlgeschlagen: {e}")
    print("Stelle sicher dass atlas.parse installiert ist: pip install -e .[parse]")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Ausgabe-Hilfsfunktionen
# ---------------------------------------------------------------------------

RESET  = "\033[0m"
BOLD   = "\033[1m"
RED    = "\033[31m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
DIM    = "\033[2m"


def _h1(text: str) -> None:
    print(f"\n{BOLD}{CYAN}{'═' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  {text}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 70}{RESET}")


def _h2(text: str) -> None:
    print(f"\n{BOLD}  {text}{RESET}")
    print(f"  {'─' * 60}")


def _ok(text: str) -> None:
    print(f"  {GREEN}✓{RESET}  {text}")


def _warn(text: str) -> None:
    print(f"  {YELLOW}⚠{RESET}  {text}")


def _err(text: str) -> None:
    print(f"  {RED}✗{RESET}  {text}")


def _info(text: str) -> None:
    print(f"  {DIM}·{RESET}  {text}")


def _band_str(band: FurnitureBand | None, page_height: float) -> str:
    if band is None:
        return "None"
    y0_rel = band.y0 / page_height
    y1_rel = band.y1 / page_height
    return (
        f"y0={band.y0:.1f} ({y0_rel:.3f})  "
        f"y1={band.y1:.1f} ({y1_rel:.3f})  "
        f"h={band.height:.1f}  "
        f"coverage={band.coverage_ratio:.2f}  "
        f"parity={band.page_parity}"
    )


# ---------------------------------------------------------------------------
# Hilfsfunktion: nativen Text prüfen
# ---------------------------------------------------------------------------

def _count_text_blocks(pdf_path: Path, page_indexes: list[int]) -> int:
    """Zählt Textblöcke auf den angegebenen Seiten."""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    count = 0
    with fitz.open(pdf_path) as doc:
        for pi in page_indexes:
            if pi < len(doc):
                for b in doc[pi].get_text("blocks"):
                    if b[6] == 0 and str(b[4]).strip():
                        count += 1
    return count


# ---------------------------------------------------------------------------
# Kern-Analyse
# ---------------------------------------------------------------------------

def analyze_pdf(pdf_path: Path) -> None:
    _h1(pdf_path.name)
    print(f"  {DIM}{pdf_path}{RESET}\n")

    try:
        profile, observations = build_document_geometry_profile(pdf_path)
    except Exception as e:
        _err(f"build_document_geometry_profile fehlgeschlagen: {e}")
        import traceback
        traceback.print_exc()
        return

    page_height = profile.paper_height
    page_width  = profile.paper_width
    page_count  = profile.page_count

    _info(f"Seiten: {page_count}  |  "
          f"Breite: {page_width:.1f}pt  |  "
          f"Höhe: {page_height:.1f}pt  |  "
          f"Format: {profile.page_format_profile.canonical_orientation if profile.page_format_profile else '?'}")

    fp: FurnitureProfile = profile.furniture_profile
    vp: VerticalProfile  = profile.vertical_profile

    # --- Nativen Text prüfen ---
    profile_pages = fp.profile_pages or list(range(min(5, page_count)))
    text_block_count = _count_text_blocks(pdf_path, profile_pages[:5])
    is_ocr_doc = text_block_count == 0

    if is_ocr_doc:
        _warn("OCR-Dokument: kein nativer Text — Geometrie-Analyse nicht anwendbar")
        _info("Seiten enthalten nur Bildblöcke (gescannt oder verzerrter Scan)")
        print()
        return

    # -----------------------------------------------------------------------
    # Furniture
    # -----------------------------------------------------------------------

    _h2("Furniture-Profil")

    # Header
    if fp.header_band:
        _ok(f"Header:  {_band_str(fp.header_band, page_height)}")
    else:
        _warn("Header:  nicht erkannt")

    if fp.header_band_odd:
        _info(f"  odd:   {_band_str(fp.header_band_odd, page_height)}")
    if fp.header_band_even:
        _info(f"  even:  {_band_str(fp.header_band_even, page_height)}")

    # Footer
    if fp.footer_band:
        _ok(f"Footer:  {_band_str(fp.footer_band, page_height)}")
    else:
        _warn("Footer:  nicht erkannt")

    if fp.footer_band_odd:
        _info(f"  odd:   {_band_str(fp.footer_band_odd, page_height)}")
    if fp.footer_band_even:
        _info(f"  even:  {_band_str(fp.footer_band_even, page_height)}")

    print()
    _info(f"Header presence: {fp.header_presence_ratio:.2f}  "
          f"({int(fp.header_presence_ratio * page_count)}/{page_count} Seiten)")
    _info(f"Footer presence: {fp.footer_presence_ratio:.2f}  "
          f"({int(fp.footer_presence_ratio * page_count)}/{page_count} Seiten)")
    _info(f"Profilseiten: {fp.profile_pages[:5]}{'...' if len(fp.profile_pages) > 5 else ''}")

    # Seitenweise Furniture-Abweichungen
    furniture_deviations = []
    for obs in observations:
        match = match_page_to_furniture_profile(fp, obs.furniture)
        if not match.header_match or not match.footer_match:
            furniture_deviations.append((obs.page_index + 1, match))

    if furniture_deviations:
        print()
        _warn(f"Furniture-Abweichungen auf {len(furniture_deviations)} Seiten:")
        shown = furniture_deviations[:10]
        for page_num, match in shown:
            types_str = ", ".join(match.deviation_types)
            print(f"    Seite {page_num:4d}: {types_str}")
        if len(furniture_deviations) > 10:
            _info(f"  ... und {len(furniture_deviations) - 10} weitere")
    else:
        _ok("Keine Furniture-Abweichungen")

    # -----------------------------------------------------------------------
    # Vertikal / Spalten
    # -----------------------------------------------------------------------

    _h2("Vertikales Profil (Spalten)")

    _info(f"Dominante Spaltenanzahl: {vp.dominant_column_count}")
    _info(f"Confidence: {vp.confidence:.3f}")

    if vp.dominant_column_lanes:
        for lane in vp.dominant_column_lanes:
            x0_rel = (lane.x0 - profile.body_region.x0) / profile.body_region.width if profile.body_region else 0.0
            x1_rel = (lane.x1 - profile.body_region.x0) / profile.body_region.width if profile.body_region else 0.0
            _ok(
                f"Spalte {lane.index}: "
                f"x0={lane.x0:.1f} ({x0_rel:.3f})  "
                f"x1={lane.x1:.1f} ({x1_rel:.3f})  "
                f"w={lane.width:.1f}  "
                f"blocks={lane.block_count}  "
                f"coverage={lane.coverage_ratio:.2f}"
            )
    else:
        _warn("Keine Spalten erkannt — einspaltig angenommen")

    if vp.dominant_gap is not None:
        _info(f"Spaltenabstand: {vp.dominant_gap:.1f}pt")

    if vp.marginalia_candidates:
        print()
        _warn(f"Marginalien erkannt ({len(vp.marginalia_candidates)}):")
        for lane in vp.marginalia_candidates:
            print(f"    x0={lane.x0:.1f}  x1={lane.x1:.1f}  "
                  f"w={lane.width:.1f}  blocks={lane.block_count}")

    # Seitenweise Spalten-Abweichungen
    vertical_deviations = []
    for obs in observations:
        if obs.vertical is None:
            continue
        page_body = profile.page_body_regions[obs.page_index] if obs.page_index < len(profile.page_body_regions) else None
        match = match_page_to_vertical_profile(vp, obs.vertical, page_body)
        if not match.column_match:
            vertical_deviations.append((obs.page_index + 1, match))

    if vertical_deviations:
        print()
        _warn(f"Spalten-Abweichungen auf {len(vertical_deviations)} Seiten:")
        shown = vertical_deviations[:10]
        for page_num, match in shown:
            types_str = ", ".join(match.deviation_types)
            print(f"    Seite {page_num:4d}: erwartet={match.expected_column_count} "
                  f"beobachtet={match.observed_column_count}  [{types_str}]")
        if len(vertical_deviations) > 10:
            _info(f"  ... und {len(vertical_deviations) - 10} weitere")
    else:
        _ok("Keine Spalten-Abweichungen")

    # -----------------------------------------------------------------------
    # Body-Region
    # -----------------------------------------------------------------------

    _h2("Body-Region")

    body = profile.body_region
    if body:
        _ok(
            f"x0={body.x0:.1f}  y0={body.y0:.1f}  "
            f"x1={body.x1:.1f}  y1={body.y1:.1f}  "
            f"w={body.width:.1f}  h={body.height:.1f}"
        )
        margin_left  = body.x0
        margin_right = page_width - body.x1
        margin_top   = body.y0
        margin_bottom = page_height - body.y1
        _info(f"Ränder: L={margin_left:.1f}  R={margin_right:.1f}  "
              f"T={margin_top:.1f}  B={margin_bottom:.1f}")
    else:
        _err("Body-Region nicht erkannt")

    # -----------------------------------------------------------------------
    # Diagnostik-Zusammenfassung
    # -----------------------------------------------------------------------

    _h2("Diagnostik")

    diag = vp.diagnostics
    _info(f"Cluster gefunden: {diag.get('cluster_count', '?')}")
    clusters = diag.get("clusters", [])
    if clusters:
        print(f"\n  {'x0_med':>8}  {'x1_med':>8}  {'blocks':>8}")
        print(f"  {'─'*8}  {'─'*8}  {'─'*8}")
        for c in clusters:
            print(f"  {c['x0_med']:>8.1f}  {c['x1_med']:>8.1f}  {c['block_count']:>8d}")

    print()


# ---------------------------------------------------------------------------
# PDF-Sammlung aus Katalog
# ---------------------------------------------------------------------------

def _pdfs_from_catalog(catalog_root: Path, limit: int = 20) -> list[Path]:
    """Findet alle PDFs in einem Atlas-Katalog."""
    pdfs = sorted(catalog_root.rglob("*.pdf"))[:limit]
    if not pdfs:
        print(f"[WARNUNG] Keine PDFs gefunden in {catalog_root}")
    return pdfs


# ---------------------------------------------------------------------------
# Bekannte Testdokumente
# ---------------------------------------------------------------------------

KNOWN_TEST_DOCS = [
    "INT_Timber_Construction_Manual",
    "UK_Historic_England",
    "UK_Medieval_Suffolk",
    "UK_urban_edinburgh",
    "DE_hallenhaus_Stiewe",
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Testet zones.py und vertical.py gegen echte PDFs."
    )
    parser.add_argument(
        "pdfs",
        nargs="*",
        type=Path,
        help="PDF-Dateien zum Testen",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Atlas-Katalogordner — alle PDFs darin werden getestet",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximale Anzahl PDFs bei --catalog (Standard: 20)",
    )
    args = parser.parse_args()

    pdfs: list[Path] = list(args.pdfs)

    if args.catalog:
        pdfs += _pdfs_from_catalog(args.catalog, limit=args.limit)

    if not pdfs:
        print("Keine PDFs angegeben. Verwendung:")
        print("  python test_geometry.py <pdf1> [<pdf2> ...]")
        print("  python test_geometry.py --catalog <katalog_root>")
        sys.exit(1)

    # Existenz prüfen
    valid = []
    for p in pdfs:
        if p.exists():
            valid.append(p)
        else:
            print(f"[WARNUNG] Nicht gefunden: {p}")

    if not valid:
        print("[FEHLER] Keine gültigen PDFs gefunden.")
        sys.exit(1)

    print(f"\n{BOLD}Teste {len(valid)} PDF(s){RESET}")

    errors = []
    for pdf in valid:
        try:
            analyze_pdf(pdf)
        except Exception as e:
            errors.append((pdf.name, str(e)))
            _err(f"Unerwarteter Fehler bei {pdf.name}: {e}")

    # Zusammenfassung
    _h1(f"Zusammenfassung: {len(valid)} PDFs")
    if errors:
        _err(f"{len(errors)} Fehler:")
        for name, msg in errors:
            print(f"    {name}: {msg}")
    else:
        _ok(f"Alle {len(valid)} PDFs erfolgreich analysiert")


if __name__ == "__main__":
    main()
