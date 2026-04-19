#!/usr/bin/env python3
"""
test_typography.py — Testet das Fließtextprofil gegen alle Testdokumente.

Nutzung:
    python scripts/test_typography.py <pdf> [<pdf> ...]
    python scripts/test_typography.py --all
"""

import sys
from pathlib import Path

# atlas.parse im Suchpfad
SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
    print(f"[setup] atlas.parse gefunden: {SRC}")

from atlas.parse.geometry import build_document_geometry_profile
from atlas.parse.typography import extract_body_text_profile

CORPUS = [
    Path("/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/reference_tools/INT_Timber_Construction_Manual.pdf"),
    Path("/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/settlement/UK_urban_plots_edinburgh_Old_Edinburgh_Club_2008__Burgage_Plots_and_the_Foundation_of_the_Burgh_of_Edinburgh__875a8d72.pdf"),
    Path("/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/case_studies/UK/UK_Medieval_Timber_Houses_East_Suffolk.pdf"),
    Path("/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/buildings/building_typology/DE_hallenhaus_typology_Stiewe.pdf"),
    Path("/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/conservation/UK_conservation_guidance_Historic_England_2016__maintenance-and-repair-of-traditional-farm-buildings.pdf"),
    Path("/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/buildings/structural_systems/DE_LVR_Heft34_Fachwerkentwicklung.pdf"),
]


def analyze(pdf_path: Path) -> None:
    name = pdf_path.name
    sep = "═" * 70
    print(f"\n{sep}")
    print(f"  {name}")
    print(f"{sep}")
    print(f"  {pdf_path}\n")

    try:
        profile, _ = build_document_geometry_profile(pdf_path)
    except Exception as e:
        print(f"  ✗  Geometry fehlgeschlagen: {e}")
        return

    body = profile.body_region
    fp = profile.furniture_profile
    vp = profile.vertical_profile

    col_width = vp.dominant_column_lanes[0].width if vp.dominant_column_lanes else 0.0
    header_y1 = fp.header_band.y1 if fp.header_band else None
    footer_y0 = fp.footer_band.y0 if fp.footer_band else None

    pfp = profile.page_format_profile
    profile_pages = pfp.profile_page_indexes if pfp else None

    try:
        tp = extract_body_text_profile(
            pdf_path=pdf_path,
            body_x0=body.x0,
            body_y0=body.y0,
            body_x1=body.x1,
            body_y1=body.y1,
            col_width=col_width,
            header_y1=header_y1,
            footer_y0=footer_y0,
            profile_page_indexes=profile_pages,
            page_count=profile.page_count,
        )
    except Exception as e:
        import traceback
        print(f"  ✗  Typography fehlgeschlagen: {e}")
        traceback.print_exc()
        return

    if tp is None:
        print("  ⚠  Zu wenige Samples — kein Profil erstellt")
        return

    ruler = "─" * 60

    print("  Fließtextprofil")
    print(f"  {ruler}")
    print(f"  Schriftgröße:   {tp.dominant_size:.1f}pt"
          f"  (MAD={tp.size_mad:.2f}  p10={tp.size_p10:.1f}  p90={tp.size_p90:.1f})")
    print(f"  Font:           {tp.dominant_font_family}"
          f"  [{tp.dominant_font}]")
    if tp.has_secondary_font:
        print(f"  Zweiter Font:   {tp.secondary_font_family}")
    print(f"  Bold-Anteil:    {tp.body_bold_ratio*100:.1f}%  "
          f"Italic-Anteil: {tp.body_italic_ratio*100:.1f}%")

    r = (tp.dominant_color >> 16) & 0xFF
    g = (tp.dominant_color >> 8) & 0xFF
    b = tp.dominant_color & 0xFF
    color_str = f"#{r:02X}{g:02X}{b:02X}"
    colored = " ⚠ farbiger Text" if tp.is_colored_text else ""
    print(f"  Farbe:          {color_str}{colored}")
    print(f"  Zeilenabstand:  {tp.dominant_line_height:.2f}pt"
          f"  (MAD={tp.line_height_mad:.2f})")
    print(f"  {ruler}")
    print(f"  Samples:  {tp.sample_span_count} Spans  "
          f"{tp.sample_block_count} Blöcke  "
          f"{tp.profile_page_count} Seiten")


def main() -> None:
    args = sys.argv[1:]

    if not args or "--all" in args:
        pdfs = [p for p in CORPUS if p.exists()]
        missing = [p for p in CORPUS if not p.exists()]
        if missing:
            print(f"[warn] {len(missing)} PDFs nicht gefunden")
    else:
        pdfs = [Path(a) for a in args]

    print(f"\nTeste {len(pdfs)} PDF(s)")

    for pdf in pdfs:
        analyze(pdf)

    print(f"\n{'═'*70}")
    print(f"  Zusammenfassung: {len(pdfs)} PDFs")
    print(f"{'═'*70}")


if __name__ == "__main__":
    main()
