# src/atlas/understanding/graph/builder.py
"""Build the in-memory neighbourhood graph from the database.

Reads block data (signals, typography, geometry, spacing) and constructs
Node objects connected by Edge objects. The graph is consumed by
corrections.py and discarded after Layer 2.5 completes.
"""
from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass, field

from atlas.understanding.graph.edges import Edge, build_sequential_edges


@dataclass
class Node:
    """Block with its Layer-2 scores and typographic context."""

    # ── Identity ──────────────────────────────────────────────────────────────
    block_id: str
    block_index: int
    page_index: int
    text: str
    doc_y_ratio: float

    # ── Layer-2 scores (read from du_block_signals) ───────────────────────────
    title_like: float
    heading_like: float
    body_like: float
    author_like: float
    reference_like: float
    caption_like: float
    noise_like: float

    # ── Typographic context ───────────────────────────────────────────────────
    font_size: float
    font_family_normalized: str
    bold: bool
    is_letter_spaced: bool

    # ── Geometric context ─────────────────────────────────────────────────────
    whitespace_after: float      # vertical gap below this block (raw pixels)

    # ── Furniture flags ───────────────────────────────────────────────────────
    first_page_meta_like: bool

    # ── Derived title-page signal ─────────────────────────────────────────────
    # True if this block is on a page that looks like a title page:
    # page 0 or 1, few blocks, no running text.
    # More robust than first_page_meta_like which only fires for journals.
    is_title_page_block: bool = False

    # ── Graph-corrected scores (None = not yet corrected) ─────────────────────
    graph_title_like:   float | None = None
    graph_heading_like: float | None = None
    graph_body_like:    float | None = None
    graph_author_like:  float | None = None
    graph_noise_like:   float | None = None
    graph_rules_fired:  list[str] = field(default_factory=list)

    def effective_title_like(self) -> float:
        return self.graph_title_like   if self.graph_title_like   is not None else self.title_like

    def effective_heading_like(self) -> float:
        return self.graph_heading_like if self.graph_heading_like is not None else self.heading_like

    def effective_body_like(self) -> float:
        return self.graph_body_like    if self.graph_body_like    is not None else self.body_like


@dataclass
class DocumentGraph:
    """In-memory graph for one document."""
    document_id: str
    nodes: list[Node]
    edges: list[Edge]
    median_gap: float

    def node_by_index(self, idx: int) -> Node | None:
        # Linear scan is fine for typical document sizes (< 5000 blocks)
        for n in self.nodes:
            if n.block_index == idx:
                return n
        return None

    def edges_from(self, idx: int) -> list[Edge]:
        return [e for e in self.edges if e.source_idx == idx]

    def edges_to(self, idx: int) -> list[Edge]:
        return [e for e in self.edges if e.target_idx == idx]

    def next_node(self, node: Node) -> Node | None:
        """Return the immediately following block in reading order."""
        edges = self.edges_from(node.block_index)
        seq = [e for e in edges if e.edge_type == "sequential"]
        if not seq:
            return None
        return self.node_by_index(seq[0].target_idx)

    def prev_node(self, node: Node) -> Node | None:
        """Return the immediately preceding block in reading order."""
        edges = self.edges_to(node.block_index)
        seq = [e for e in edges if e.edge_type == "sequential"]
        if not seq:
            return None
        return self.node_by_index(seq[0].source_idx)


def build_graph(conn: sqlite3.Connection, document_id: str) -> DocumentGraph:
    """Read block data from DB and construct the DocumentGraph.

    Fetches signals, typography, geometry, spacing and furniture in a
    single JOIN query to avoid N+1 patterns.
    """
    rows = conn.execute(
        """
        SELECT
            b.block_id, b.block_index, b.page_index, b.text,
            COALESCE(geo.doc_y_ratio, 0.0)          AS doc_y_ratio,
            -- Layer-2 scores
            COALESCE(s.title_like,     0.0)          AS title_like,
            COALESCE(s.heading_like,   0.0)          AS heading_like,
            COALESCE(s.body_like,      0.0)          AS body_like,
            COALESCE(s.author_like,    0.0)          AS author_like,
            COALESCE(s.reference_like, 0.0)          AS reference_like,
            COALESCE(s.caption_like,   0.0)          AS caption_like,
            COALESCE(s.noise_like,     0.0)          AS noise_like,
            -- Typography
            COALESCE(t.font_size,      0.0)          AS font_size,
            COALESCE(t.font_family_normalized, '')   AS font_family_normalized,
            COALESCE(t.bold,           0)            AS bold,
            COALESCE(t.is_letter_spaced, 0)          AS is_letter_spaced,
            -- Geometry: whitespace below block
            COALESCE(sp.paragraph_gap_after, 0.0)    AS whitespace_after,
            -- Furniture
            COALESCE(f.first_page_meta_like, 0)      AS first_page_meta_like
        FROM du_blocks b
        LEFT JOIN du_block_signals   s   ON s.block_id  = b.block_id
        LEFT JOIN du_block_typography t   ON t.block_id  = b.block_id
        LEFT JOIN du_block_geometry  geo  ON geo.block_id = b.block_id
        LEFT JOIN du_block_spacing   sp   ON sp.block_id  = b.block_id
        LEFT JOIN du_block_furniture f   ON f.block_id  = b.block_id
        WHERE b.document_id = ?
        ORDER BY b.block_index
        """,
        (document_id,),
    ).fetchall()

    if not rows:
        return DocumentGraph(
            document_id=document_id,
            nodes=[],
            edges=[],
            median_gap=1.0,
        )

    # Compute median inter-block gap for normalisation
    gaps = [float(r["whitespace_after"]) for r in rows if r["whitespace_after"]]
    median_gap = statistics.median(gaps) if gaps else 1.0

    # Compute per-page statistics for title-page detection
    from collections import defaultdict
    page_blocks: dict[int, list] = defaultdict(list)
    for r in rows:
        page_blocks[r["page_index"]].append(r)

    def _is_title_page(page_idx: int) -> bool:
        blocks = page_blocks.get(page_idx, [])
        if page_idx > 1:
            return False
        if len(blocks) > 15:
            return False
        avg_body = (
            sum(float(b["body_like"]) for b in blocks) / len(blocks)
            if blocks else 1.0
        )
        return avg_body < 0.25

    title_pages = {
        page_idx
        for page_idx in page_blocks
        if _is_title_page(page_idx)
    }

    nodes: list[Node] = []
    for r in rows:
        node = Node(
            block_id=r["block_id"],
            block_index=r["block_index"],
            page_index=r["page_index"],
            text=(r["text"] or "").strip(),
            doc_y_ratio=float(r["doc_y_ratio"]),
            title_like=float(r["title_like"]),
            heading_like=float(r["heading_like"]),
            body_like=float(r["body_like"]),
            author_like=float(r["author_like"]),
            reference_like=float(r["reference_like"]),
            caption_like=float(r["caption_like"]),
            noise_like=float(r["noise_like"]),
            font_size=float(r["font_size"]),
            font_family_normalized=r["font_family_normalized"],
            bold=bool(r["bold"]),
            is_letter_spaced=bool(r["is_letter_spaced"]),
            whitespace_after=float(r["whitespace_after"]),
            first_page_meta_like=bool(r["first_page_meta_like"]),
            is_title_page_block=(r["page_index"] in title_pages),
        )
        nodes.append(node)

    # Build edges — Phase 1: sequential only
    block_dicts = [
        {
            "block_index": n.block_index,
            "page_index":  n.page_index,
            "text":        n.text,
            "font_size":   n.font_size,
            "font_family_normalized": n.font_family_normalized,
            "whitespace_after": n.whitespace_after,
        }
        for n in nodes
    ]
    edges = build_sequential_edges(block_dicts, median_gap)

    return DocumentGraph(
        document_id=document_id,
        nodes=nodes,
        edges=edges,
        median_gap=median_gap,
    )
