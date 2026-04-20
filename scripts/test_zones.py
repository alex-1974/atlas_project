#!/usr/bin/env python3
"""test_zones.py — Testet Zonen-Erkennung gegen alle Testdokumente."""
import sys
from pathlib import Path

SRC = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(SRC))

from atlas.parse.geometry import build_document_geometry_profile
from atlas.parse.typography import extract_body_text_profile
from atlas.parse.document_zones import detect_document_zones

CORPUS = [
    "/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/reference_tools/INT_Timber_Construction_Manual.pdf",
    "/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/settlement/UK_urban_plots_edinburgh_Old_Edinburgh_Club_2008__Burgage_Plots_and_the_Foundation_of_the_Burgh_of_Edinburgh__875a8d72.pdf",
    "/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/case_studies/UK/UK_Medieval_Timber_Houses_East_Suffolk.pdf",
    "/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/buildings/building_typology/DE_hallenhaus_typology_Stiewe.pdf",
    "/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/conservation/UK_conservation_guidance_Historic_England_2016__maintenance-and-repair-of-traditional-farm-buildings.pdf",
    "/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/buildings/structural_systems/DE_LVR_Heft34_Fachwerkentwicklung.pdf",
]


def analyze(pdf_path):
    sep = "=" * 70
    print(f"\n{sep}")
    print(f"  {pdf_path.name}")
    print(f"{sep}")

    profile, observations = build_document_geometry_profile(pdf_path)

    fp = profile.furniture_profile
    vp = profile.vertical_profile
    pfp = profile.page_format_profile

    col_width = vp.dominant_column_lanes[0].width if vp.dominant_column_lanes else 0.0
    tp = extract_body_text_profile(
        pdf_path=pdf_path,
        body_x0=profile.body_region.x0,
        body_y0=profile.body_region.y0,
        body_x1=profile.body_region.x1,
        body_y1=profile.body_region.y1,
        col_width=col_width,
        header_y1=fp.header_band.y1 if fp.header_band else None,
        footer_y0=fp.footer_band.y0 if fp.footer_band else None,
        profile_page_indexes=pfp.profile_page_indexes if pfp else None,
        page_count=profile.page_count,
    )

    zones = detect_document_zones(pdf_path, profile, observations, tp)

    ruler = "-" * 60
    print(f"\n  Zonen  ({profile.page_count} Seiten total)")
    print(f"  {ruler}")

    fm_count = len(zones.frontmatter_pages)
    body_count = len(zones.body_pages)
    bm_count = len(zones.backmatter_pages)

    print(f"  Frontmatter:  Seiten 1-{zones.body_start}  ({fm_count} Seiten)")

    b = zones.body_start_boundary
    conf_str = f"{b.confidence:.0%}"
    print(f"  Body:         ab Seite {zones.body_start + 1}  ({body_count} Seiten)")
    print(f"    Signal:     {b.signal}  [{conf_str}]  '{b.text_snippet}'")

    if zones.backmatter_start is not None:
        bb = zones.backmatter_boundary
        print(f"  Backmatter:   ab Seite {zones.backmatter_start + 1}  ({bm_count} Seiten)")
        print(f"    Signal:     {bb.signal}  [95%]  '{bb.text_snippet}'")
    else:
        print(f"  Backmatter:   nicht erkannt")

    print(f"  {ruler}")


def main():
    args = sys.argv[1:]
    pdfs = [Path(a) for a in args] if args else [Path(p) for p in CORPUS if Path(p).exists()]
    print(f"\nTeste {len(pdfs)} PDF(s)")
    for pdf in pdfs:
        analyze(pdf)
    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
