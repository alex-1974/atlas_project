from atlas.segment.block_evidence import build_scored_blocks
from atlas.segment.region_assembly import assemble_regions


def _types(regions):
    return [r.region_type for r in regions]


def test_region_assembly_detects_front_matter_toc_abstract_body_references():
    text = """A History of Timber Construction

Jane Doe, John Smith

Department of Architecture
University of Vienna
jane@example.org
March 2024

Contents
1 Introduction ........ 3
2 Methods ........ 8
3 References ........ 44

Abstract
This article studies timber structures in late medieval Central Europe. It summarizes methods, corpus selection, and the main findings in a compact way.

1 Introduction
This is the main body text. It contains running prose and a citation (Smith 1999).

References
Doe, J. (2020). Timber Houses. Vienna Press.
Smith, A. (1999). Historic Roofs. https://example.org/ref
"""
    blocks = build_scored_blocks(text)
    regions = assemble_regions(blocks, text)
    kinds = _types(regions)
    assert "title_page" in kinds
    assert "front_matter" in kinds
    assert "toc" in kinds
    assert "abstract_or_summary" in kinds
    assert "body" in kinds
    assert "references" in kinds


def test_region_assembly_handles_simple_body_and_references_tail():
    text = """Introduction
This is a normal paragraph with enough running text to count as body. It includes discussion of prior work (Müller 2004).

References
Müller, K. (2004). Study of Houses. Berlin.
Schmidt, A. (2011). More Results. doi:10.1234/example
"""
    blocks = build_scored_blocks(text)
    regions = assemble_regions(blocks, text)
    kinds = _types(regions)
    assert "body" in kinds
    assert "references" in kinds
