#!/usr/bin/env python3
"""test_metadata.py — Testet Metadaten-Extraktion gegen alle 6 Dokumente."""
import sys
from pathlib import Path
SRC = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(SRC))

from atlas.parse.geometry import build_document_geometry_profile
from atlas.parse.typography import extract_body_text_profile
from atlas.parse.document_zones import detect_document_zones
from atlas.parse.document_type_hints import infer_document_type_hint
from atlas.parse.metadata import extract_metadata

CORPUS = [
    "/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/reference_tools/INT_Timber_Construction_Manual.pdf",
    "/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/settlement/UK_urban_plots_edinburgh_Old_Edinburgh_Club_2008__Burgage_Plots_and_the_Foundation_of_the_Burgh_of_Edinburgh__875a8d72.pdf",
    "/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/case_studies/UK/UK_Medieval_Timber_Houses_East_Suffolk.pdf",
    "/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/buildings/building_typology/DE_hallenhaus_typology_Stiewe.pdf",
    "/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/conservation/UK_conservation_guidance_Historic_England_2016__maintenance-and-repair-of-traditional-farm-buildings.pdf",
    "/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature/buildings/structural_systems/DE_LVR_Heft34_Fachwerkentwicklung.pdf",
]

# Erwartete Werte zum Vergleich
EXPECTED = {
    "INT_Timber":    {"title": "TIMBER CONSTRUCTION MANUAL", "authors": ["AMERICAN INSTITUTE OF TIMBER CONSTRUCTION"]},
    "Edinburgh":     {"title": "Burgage Plots and the Foundation of the Burgh of Edinburgh", "authors": ["Robin Tait"], "issn": "2634-2618"},
    "Suffolk":       {"title": "MEDIEVAL TIMBER FRAMED HOUSES IN EAST SUFFOLK", "authors": ["P. J. HILL", "D. G. PENROSE"]},
    "Stiewe":        {"title": "Das Niederdeutsche Hallenhaus", "authors": ["Heinrich Stiewe"]},
    "HistoricEng":   {"title": "The Maintenance and Repair of Traditional Farm Buildings"},
    "LVR":           {"title": "Gebäude aus Fachwerk Konstruktion"},
}

def analyze(pdf_path):
    path = Path(pdf_path)
    print(f"\n{'='*70}")
    print(f"  {path.name}")
    print(f"{'='*70}")

    profile, observations = build_document_geometry_profile(path)
    fp = profile.furniture_profile
    vp = profile.vertical_profile
    pfp = profile.page_format_profile
    col_width = vp.dominant_column_lanes[0].width if vp.dominant_column_lanes else 0.0

    tp = extract_body_text_profile(
        pdf_path=path,
        body_x0=profile.body_region.x0, body_y0=profile.body_region.y0,
        body_x1=profile.body_region.x1, body_y1=profile.body_region.y1,
        col_width=col_width,
        header_y1=fp.header_band.y1 if fp.header_band else None,
        footer_y0=fp.footer_band.y0 if fp.footer_band else None,
        profile_page_indexes=pfp.profile_page_indexes if pfp else None,
        page_count=profile.page_count,
    )
    zones = detect_document_zones(path, profile, observations, tp)
    hint = infer_document_type_hint(profile, zones, observations, pdf_path=path)
    meta = extract_metadata(path, profile, zones, tp, observations=observations)

    ruler = "-" * 60
    depth_sym = ['○','▸','▸▸','▸▸▸'][hint.structure_depth]
    print(f"\n  Typ: {hint.doc_class}  {depth_sym}  "
          f"TOC={'✓' if hint.has_toc else '—'}  "
          f"BM-Richness={hint.backmatter_richness}  "
          f"Scan={'✓' if hint.scan_cover else '—'}  "
          f"conf={hint.confidence:.0%}")
    print(f"  {ruler}")
    t_conf = f"{meta.title_confidence:.0%}" if meta.title else "—"
    print(f"  Titel [{t_conf}]:  {meta.title or '—'}")
    if meta.title_page is not None:
        print(f"    Seite: {meta.title_page + 1}")

    a_conf = f"{meta.authors_confidence:.0%}" if meta.authors else "—"
    print(f"  Autoren [{a_conf}]: {', '.join(meta.authors) or '—'}")

    print(f"  Jahr:    {meta.year or '—'}")
    print(f"  DOI:     {meta.doi or '—'}")
    print(f"  ISBN:    {meta.isbn or '—'}")
    print(f"  ISSN:    {meta.issn or '—'}")
    if meta.abstract:
        print(f"  Abstract [{meta.abstract_confidence:.0%}]: {meta.abstract[:80]}...")
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
