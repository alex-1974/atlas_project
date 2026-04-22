#!/usr/bin/env bash
# test_all.sh — Testet alle fünf Dokumente gegen zones.py und vertical.py

SCRIPT="python scripts/test_geometry.py"
BASE="/home/alexander/Programmiersprachen/Blender/bvillage_project/research/literature"

PDFS=(
    "$BASE/reference_tools/INT_Timber_Construction_Manual.pdf"
    "$BASE/settlement/UK_urban_plots_edinburgh_Old_Edinburgh_Club_2008__Burgage_Plots_and_the_Foundation_of_the_Burgh_of_Edinburgh__875a8d72.pdf"
    "$BASE/case_studies/UK/UK_Medieval_Timber_Houses_East_Suffolk.pdf"
    "$BASE/buildings/building_typology/DE_hallenhaus_typology_Stiewe.pdf"
    "$BASE/conservation/UK_conservation_guidance_Historic_England_2016__maintenance-and-repair-of-traditional-farm-buildings.pdf"
    "$BASE/buildings/structural_systems/DE_LVR_Heft34_Fachwerkentwicklung.pdf"
)

for pdf in "${PDFS[@]}"; do
    $SCRIPT "$pdf"
    echo
done
