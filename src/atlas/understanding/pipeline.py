# src/atlas/understanding/pipeline.py
"""Orchestrates the full Document Understanding pipeline for one document.

Execution order (mirrors ARCHITECTURE-DU-PIPELINE.md):

  build_document          segmentation/blocks.py

  Layer 1 — Measurement
    geometry              measure/geometry.py
    typography            measure/typography.py
    surface               measure/surface.py
    topology              measure/topology.py
    furniture             measure/furniture.py      (needs topology)
    spacing               measure/spacing.py        (needs geometry)
    context               measure/context.py        (needs geometry)
    semantic_micro        measure/semantic_micro.py

  Layer 2 — Aggregation
    signals               aggregate/signals.py

  Layer 3 — Interpretation
    roles                 interpret/roles.py
    consensus             interpret/consensus.py
    zones                 interpret/zones.py
    headings              interpret/headings.py     (needs zones)
    section_tree          interpret/section_tree.py (needs headings + zones)
"""
from __future__ import annotations

import sqlite3

from atlas.understanding.segmentation.blocks import build_document
from atlas.understanding.measure.geometry import compute_geometry
from atlas.understanding.measure.typography import compute_typography
from atlas.understanding.measure.surface import compute_surface
from atlas.understanding.measure.topology import compute_topology
from atlas.understanding.measure.furniture import compute_furniture
from atlas.understanding.measure.spacing import compute_spacing
from atlas.understanding.measure.context import compute_context
from atlas.understanding.measure.semantic_micro import compute_semantic_micro
from atlas.understanding.aggregate.signals import compute_signals
from atlas.understanding.interpret.roles import compute_roles
from atlas.understanding.interpret.consensus import compute_consensus
from atlas.understanding.interpret.zones import compute_zones
from atlas.understanding.interpret.headings import compute_headings
from atlas.understanding.interpret.section_tree import compute_section_tree
from atlas.understanding.interpret.document_type import compute_document_type


def run_du_pipeline(conn: sqlite3.Connection, document_id: str) -> bool:
    """Run the complete DU pipeline for one document.

    Assumes du_layout_lines and du_layout_spans are already populated
    by pipeline/extract/layout.py.

    Two-pass approach to resolve the chicken-and-egg problem between
    document type detection and role assignment:
      Pass 1: compute signals + roles without type adjustment
      Pass 2: detect document type, then recompute roles with adjustments

    Returns True if blocks were found and processing completed,
    False if the document has no layout data yet.
    """
    # Segmentation — must run first; all other steps read du_blocks
    if not build_document(conn, document_id):
        return False

    # Layer 1 — order matters: geometry before spacing/context,
    # topology before furniture
    compute_geometry(conn, document_id)
    compute_typography(conn, document_id)
    compute_surface(conn, document_id)
    compute_topology(conn, document_id)
    compute_furniture(conn, document_id)
    compute_spacing(conn, document_id)
    compute_context(conn, document_id)
    compute_semantic_micro(conn, document_id)

    # Layer 2
    compute_signals(conn, document_id)

    # Layer 3 — Pass 1: roles without document type adjustment
    compute_roles(conn, document_id)
    compute_consensus(conn, document_id)
    compute_zones(conn, document_id)
    compute_headings(conn, document_id)
    compute_section_tree(conn, document_id)

    # Document type detection — uses roles + section tree from Pass 1
    compute_document_type(conn, document_id)

    # Layer 3 — Pass 2: recompute roles with document type adjustments
    # This resolves the chicken-and-egg: type is now known, roles benefit
    # from type-specific signal adjustments.
    compute_roles(conn, document_id)
    compute_consensus(conn, document_id)
    compute_zones(conn, document_id)
    compute_headings(conn, document_id)
    compute_section_tree(conn, document_id)

    return True
