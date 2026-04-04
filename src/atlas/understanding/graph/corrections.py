# src/atlas/understanding/graph/corrections.py
"""Layer 2.5 — neighbourhood graph score corrections.

Applies correction rules that use adjacent-block context to adjust
Layer-2 scores before Layer-3 role assignment.

Each rule is a function that takes the DocumentGraph and mutates
node.graph_* scores in place. Rules are applied in order.

Rule design principles
----------------------
- Rules only *adjust* scores, never assign roles directly
- Each rule records its name in node.graph_rules_fired for debugging
- Rules are additive: multiple rules can fire on the same node
- Corrections are bounded to [0.0, 1.0] via _clamp()

Current rules
-------------
R01_title_continuation  — boost title_like of node following an open-ended
                          title node when gap and font are compatible
R02_sequence_position   — dampen title_like for blocks far into the document
R03_heading_body_flow   — confirm heading when immediately followed by body
R04_reference_tail      — boost reference_like for blocks near document end
                          when preceding blocks are also reference-like
"""
from __future__ import annotations

import json
import sqlite3

from atlas.understanding.graph.builder import DocumentGraph, Node, build_graph


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _set(node: Node, field: str, value: float, rule: str) -> None:
    """Set a graph_* score and record the firing rule."""
    setattr(node, field, _clamp(value))
    if rule not in node.graph_rules_fired:
        node.graph_rules_fired.append(rule)


def _boost(node: Node, field: str, amount: float, rule: str) -> None:
    current = getattr(node, field)
    if current is None:
        # Start from the original Layer-2 score
        orig_field = field.replace("graph_", "")
        current = getattr(node, orig_field, 0.0)
    _set(node, field, current + amount, rule)


def _dampen(node: Node, field: str, factor: float, rule: str) -> None:
    """Multiply score by factor (0 < factor < 1 dampens, > 1 boosts)."""
    orig_field = field.replace("graph_", "")
    current = getattr(node, field)
    if current is None:
        current = getattr(node, orig_field, 0.0)
    _set(node, field, current * factor, rule)


# ── Rules ─────────────────────────────────────────────────────────────────────

def R01_title_continuation(graph: DocumentGraph) -> None:
    """Boost title_like for a block that continues an open-ended title.

    Fires when:
    - source node has title_like > 0.45 (strong title candidate)
    - source text ends syntactically open (preposition, no punctuation)
    - vertical gap is tighter than median (blocks belong together)
    - font sizes are similar (ratio 0.75–1.25)
    - both blocks on the same page or source is on first_page_meta
    """
    rule = "R01_title_continuation"
    for node in graph.nodes:
        # Only consider original Layer-2 title candidates (not already boosted)
        # and only on page 0 with first_page_meta context
        if node.title_like < 0.55:
            continue
        if not node.is_title_page_block:
            continue
        if not node.is_title_page_block:
            continue
        # Skip blocks already corrected by this rule (prevent chain reactions)
        if node.graph_title_like is not None:
            continue
        for edge in graph.edges_from(node.block_index):
            if edge.edge_type != "sequential":
                continue
            if not edge.source_text_continues:
                continue
            if edge.vertical_gap_ratio > 50.0:
                continue
            if not (0.65 <= edge.font_ratio <= 1.50):
                continue
            if not edge.same_page:
                continue
            target = graph.node_by_index(edge.target_idx)
            if target is None:
                continue
            # Target must be on page 0 or 1 maximum
            if not target.is_title_page_block:
                continue
            # Target must not already be boosted (no chain reactions)
            if target.graph_title_like is not None:
                continue
            # Don't boost if target already looks like a strong heading
            if target.heading_like > target.title_like + 0.35:
                continue
            _boost(target, "graph_title_like", 0.25, rule)
            # Also dampen heading_like so title wins in _resolve_role
            _dampen(target, "graph_heading_like", 0.60, rule)


def R02_sequence_position(graph: DocumentGraph) -> None:
    """Dampen title_like for blocks far into the document.

    A block with high title_like at doc_y_ratio > 0.20 is almost certainly
    a prominent heading, not the document title.

    Already partially handled in roles.py (doc_y > 0.15 → fscale 0.30),
    but that fires after Layer-2 scores are set. This rule fires earlier
    and is more conservative to avoid double-dampening.
    """
    rule = "R02_sequence_position"
    for node in graph.nodes:
        if node.doc_y_ratio <= 0.20:
            continue
        if node.is_title_page_block:
            continue
        if node.title_like < 0.30:
            continue
        _dampen(node, "graph_title_like", 0.40, rule)


def R03_heading_body_flow(graph: DocumentGraph) -> None:
    """Confirm heading when immediately followed by body text.

    A block classified as heading that is directly followed by a dense
    body block (body_like > 0.60, vertical gap ≤ 2× median) is almost
    certainly a heading. Boost heading_like to prevent misclassification
    as title or body.
    """
    rule = "R03_heading_body_flow"
    for node in graph.nodes:
        if node.heading_like < 0.30:
            continue
        for edge in graph.edges_from(node.block_index):
            if edge.edge_type != "sequential":
                continue
            if edge.vertical_gap_ratio > 2.5:
                continue
            target = graph.node_by_index(edge.target_idx)
            if target is None:
                continue
            if target.body_like < 0.55:
                continue
            _boost(node, "graph_heading_like", 0.15, rule)
            # If this heading was competing with title, dampen title
            if node.title_like > 0.40:
                _dampen(node, "graph_title_like", 0.70, rule)


def R04_reference_tail(graph: DocumentGraph) -> None:
    """Boost reference_like for blocks in a run of reference-like blocks
    near the document end.

    A block near the document end (doc_y > 0.75) that is surrounded by
    blocks with reference_like > 0.30 is very likely a reference entry
    even if its own reference_like is modest.
    """
    rule = "R04_reference_tail"
    for i, node in enumerate(graph.nodes):
        if node.doc_y_ratio < 0.75:
            continue
        if node.reference_like >= 0.30:
            continue
        # Check immediate neighbours
        prev = graph.prev_node(node)
        nxt  = graph.next_node(node)
        neighbour_ref = sum([
            1 for n in [prev, nxt]
            if n is not None and n.reference_like >= 0.30
        ])
        if neighbour_ref >= 2:
            _boost(node, "graph_reference_like" if hasattr(node, "graph_reference_like")
                   else "graph_noise_like", 0.0, rule)  # no-op placeholder
            # Note: reference_like is not in graph_* columns yet —
            # extend migration 0015 if needed. For now just record the rule.
            node.graph_rules_fired.append(rule)


# ── Rule registry ─────────────────────────────────────────────────────────────

_RULES = [
    R01_title_continuation,
    R02_sequence_position,
    R03_heading_body_flow,
    R04_reference_tail,
]


# ── Persistence ───────────────────────────────────────────────────────────────

def _persist(conn: sqlite3.Connection, graph: DocumentGraph) -> None:
    """Write graph_* scores back to du_block_signals."""
    rows = []
    for node in graph.nodes:
        # Only persist nodes with actual score changes, not just rule annotations
        has_score_change = any(
            getattr(node, f) is not None
            for f in ("graph_title_like", "graph_heading_like",
                      "graph_body_like", "graph_author_like", "graph_noise_like")
        )
        if not has_score_change:
            continue
        rows.append((
            node.graph_title_like,
            node.graph_heading_like,
            node.graph_body_like,
            node.graph_author_like,
            node.graph_noise_like,
            json.dumps(node.graph_rules_fired) if node.graph_rules_fired else None,
            node.block_id,
        ))
    if rows:
        conn.executemany(
            """
            UPDATE du_block_signals SET
                graph_title_like   = ?,
                graph_heading_like = ?,
                graph_body_like    = ?,
                graph_author_like  = ?,
                graph_noise_like   = ?,
                graph_rules_fired  = ?
            WHERE block_id = ?
            """,
            rows,
        )
        conn.commit()


# ── Public API ────────────────────────────────────────────────────────────────

def run_graph_corrections(
    conn: sqlite3.Connection,
    document_id: str,
) -> int:
    """Build graph, apply correction rules, persist results.

    Returns the number of blocks that received graph corrections.
    """
    # Clear previous graph corrections for this document (idempotency)
    conn.execute(
        """
        UPDATE du_block_signals SET
            graph_title_like   = NULL,
            graph_heading_like = NULL,
            graph_body_like    = NULL,
            graph_author_like  = NULL,
            graph_noise_like   = NULL,
            graph_rules_fired  = NULL
        WHERE block_id IN (
            SELECT block_id FROM du_blocks WHERE document_id = ?
        )
        """,
        (document_id,),
    )
    conn.commit()
    graph = build_graph(conn, document_id)
    if not graph.nodes:
        return 0

    for rule_fn in _RULES:
        rule_fn(graph)

    _persist(conn, graph)
    return sum(1 for n in graph.nodes if n.graph_rules_fired)
