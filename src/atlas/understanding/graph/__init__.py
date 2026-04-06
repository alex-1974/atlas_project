# src/atlas/understanding/graph/__init__.py
"""Neighbourhood graph for Layer 2.5 score corrections.

Architecture
------------
Layer 2 (Aggregate) produces per-block scores: title_like, heading_like, ...
Layer 2.5 (Graph)   builds a neighbourhood graph over blocks, then applies
                    correction rules that use adjacent-block context.
Layer 3 (Interpret) reads COALESCE(graph_*, original_*) from du_block_signals.

The graph itself lives only in memory during pipeline execution.
Only the corrected scores and the list of fired rules are persisted
(in du_block_signals.graph_* columns).

Public API
----------
    from atlas.understanding.graph import run_graph_corrections
    run_graph_corrections(conn, document_id)
"""
from atlas.understanding.graph.corrections import run_graph_corrections

__all__ = ["run_graph_corrections"]
