from __future__ import annotations

from atlas.parse.geometry import (
    PageBlock,
    build_page_layout_signatures,
    build_page_column_hypotheses,
)


def make_block(
    *,
    page_index: int,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    text: str = "txt",
    block_index: int = 0,
    block_type: int = 0,
) -> PageBlock:
    return PageBlock(
        page_index=page_index,
        block_index=block_index,
        block_type=block_type,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        text=text,
    )


def test_build_page_column_hypotheses_frontmatter_guard():
    from atlas.parse.zones import BodyRegion
    from atlas.parse.geometry import ColumnBox

    page_body_regions = [
        BodyRegion(x0=50, y0=100, x1=550, y1=700),
        BodyRegion(x0=50, y0=100, x1=550, y1=700),
        BodyRegion(x0=50, y0=100, x1=550, y1=700),
    ]

    line_boxes = [
        # page 0: very few lines, should be forced to 1-column by frontmatter guard
        ColumnBox(page_index=0, parity="odd", x0=80, y0=120, x1=250, y1=135),
        ColumnBox(page_index=0, parity="odd", x0=300, y0=150, x1=470, y1=165),
        # page 2: proper two-column body
        ColumnBox(page_index=2, parity="odd", x0=70, y0=120, x1=230, y1=135),
        ColumnBox(page_index=2, parity="odd", x0=320, y0=120, x1=500, y1=135),
        ColumnBox(page_index=2, parity="odd", x0=72, y0=150, x1=228, y1=165),
        ColumnBox(page_index=2, parity="odd", x0=318, y0=150, x1=498, y1=165),
        ColumnBox(page_index=2, parity="odd", x0=74, y0=180, x1=226, y1=195),
        ColumnBox(page_index=2, parity="odd", x0=316, y0=180, x1=496, y1=195),
    ]

    hypotheses = build_page_column_hypotheses(
        line_boxes=line_boxes,
        page_body_regions=page_body_regions,
        page_count=3,
    )

    assert hypotheses[0].column_count == 1
    assert hypotheses[2].column_count in {1, 2}


def test_build_page_layout_signatures_uses_pagewise_band_matching():
    from atlas.parse.zones import BodyRegion, FurnitureBand
    from atlas.parse.geometry import ColumnBox, PageColumnHypothesis

    blocks = [
        # page 0: header present
        make_block(page_index=0, x0=40, y0=20, x1=250, y1=40, text="Header L"),
        make_block(page_index=0, x0=360, y0=20, x1=560, y1=40, text="1"),
        make_block(page_index=0, x0=60, y0=120, x1=540, y1=700, text="Body 1"),
        # page 1: no header
        make_block(page_index=1, x0=60, y0=120, x1=540, y1=700, text="Body 2"),
    ]

    page_body_regions = [
        BodyRegion(x0=50, y0=100, x1=550, y1=700),
        BodyRegion(x0=50, y0=100, x1=550, y1=700),
    ]

    header_band = FurnitureBand(
        side="top",
        y0=20,
        y1=40,
        coverage_ratio=1.0,
        pages_present=1,
    )

    page_column_hypotheses = [
        PageColumnHypothesis(page_index=0, column_count=1, lane_ranges_rel=[], score=0.5),
        PageColumnHypothesis(page_index=1, column_count=1, lane_ranges_rel=[], score=0.5),
    ]

    signatures = build_page_layout_signatures(
        blocks=blocks,
        page_body_regions=page_body_regions,
        header_band=header_band,
        footer_band=None,
        header_band_odd=header_band,
        header_band_even=None,
        footer_band_odd=None,
        footer_band_even=None,
        column_boxes=[],
        page_column_hypotheses=page_column_hypotheses,
        page_count=2,
        page_width=600.0,
        page_height=800.0,
    )

    assert len(signatures) == 2
    assert signatures[0].has_header is True
    assert signatures[1].has_header is False
