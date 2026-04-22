from __future__ import annotations

from atlas.parse.geometry import PageBlock
from atlas.parse.zones import (
    BodyRegion,
    FurnitureBand,
    _aggregate_band_candidates,
    _build_horizontal_band_candidate,
    _interval_coverage,
    _merge_x_intervals,
    _middle_page_indexes,
    detect_document_body_region_from_pages,
    detect_page_body_regions,
    detect_repeated_furniture_bands,
    filter_out_furniture,
    page_matches_band_candidate,
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


def test_merge_x_intervals_merges_overlaps():
    intervals = [(10, 50), (40, 90), (100, 120), (121, 130)]
    merged = _merge_x_intervals(intervals)
    assert merged == [(10, 90), (100, 120), (121, 130)]


def test_interval_coverage():
    intervals = [(0, 50), (60, 100)]
    coverage = _interval_coverage(intervals, page_width=200)
    assert coverage == 0.45


def test_middle_page_indexes_prefers_middle_third():
    assert _middle_page_indexes(3) == [0, 1, 2]
    assert _middle_page_indexes(9) == [3, 4, 5]
    assert _middle_page_indexes(12) == [4, 5, 6, 7]


def test_build_horizontal_header_band_candidate_from_split_header():
    page_width = 600.0
    page_height = 800.0

    blocks = [
        make_block(page_index=0, x0=40, y0=20, x1=260, y1=40, text="Kapitel 1"),
        make_block(page_index=0, x0=360, y0=20, x1=560, y1=40, text="12"),
        make_block(page_index=0, x0=60, y0=120, x1=260, y1=140, text="Body left"),
    ]

    band = _build_horizontal_band_candidate(
        page_blocks=blocks,
        page_width=page_width,
        page_height=page_height,
        side="top",
    )

    assert band is not None
    y0, y1, coverage = band
    assert y0 == 20
    assert y1 == 40
    assert coverage > 0.6


def test_build_horizontal_footer_band_candidate_from_split_footer():
    page_width = 600.0
    page_height = 800.0

    blocks = [
        make_block(page_index=0, x0=50, y0=760, x1=250, y1=780, text="Journal"),
        make_block(page_index=0, x0=380, y0=760, x1=550, y1=780, text="18"),
        make_block(page_index=0, x0=60, y0=140, x1=260, y1=160, text="Body"),
    ]

    band = _build_horizontal_band_candidate(
        page_blocks=blocks,
        page_width=page_width,
        page_height=page_height,
        side="bottom",
    )

    assert band is not None
    y0, y1, coverage = band
    assert y0 == 760
    assert y1 == 780
    assert coverage > 0.6


def test_aggregate_band_candidates_builds_stable_band():
    candidates = {
        3: (20.0, 40.0, 0.75),
        4: (21.0, 41.0, 0.76),
        5: (20.5, 40.5, 0.77),
        6: (20.0, 40.0, 0.74),
    }

    band = _aggregate_band_candidates(
        candidates=candidates,
        page_indexes=[3, 4, 5, 6],
        side="top",
        page_parity="all",
        page_height=800.0,
    )

    assert band is not None
    assert band.side == "top"
    assert 19.0 <= band.y0 <= 22.0
    assert 39.0 <= band.y1 <= 42.0


def test_filter_out_furniture_removes_blocks_in_header_and_footer_bands():
    blocks = [
        make_block(page_index=0, x0=40, y0=20, x1=560, y1=40, text="Header"),
        make_block(page_index=0, x0=50, y0=120, x1=550, y1=160, text="Body"),
        make_block(page_index=0, x0=40, y0=760, x1=560, y1=780, text="Footer"),
    ]

    filtered = filter_out_furniture(
        blocks=blocks,
        header_band=FurnitureBand(side="top", y0=20, y1=40, coverage_ratio=1.0, pages_present=1),
        footer_band=FurnitureBand(side="bottom", y0=760, y1=780, coverage_ratio=1.0, pages_present=1),
    )

    assert len(filtered) == 1
    assert filtered[0].text == "Body"


def test_detect_page_body_regions_excludes_empty_pages():
    blocks = [
        make_block(page_index=0, x0=50, y0=100, x1=550, y1=700, text="Body A"),
        make_block(page_index=1, x0=60, y0=110, x1=540, y1=690, text="Body B"),
    ]

    regions = detect_page_body_regions(
        blocks=blocks,
        page_count=3,
        page_width=600.0,
        page_height=800.0,
    )

    assert len(regions) == 3
    assert regions[0] is not None
    assert regions[1] is not None
    assert regions[2] is None


def test_detect_document_body_region_from_pages():
    regions = [
        BodyRegion(x0=50, y0=100, x1=550, y1=700),
        BodyRegion(x0=55, y0=110, x1=545, y1=690),
        None,
    ]

    doc_region = detect_document_body_region_from_pages(
        page_regions=regions,
        page_width=600.0,
        page_height=800.0,
    )

    assert doc_region is not None
    assert 49 <= doc_region.x0 <= 56
    assert 544 <= doc_region.x1 <= 551
    assert 99 <= doc_region.y0 <= 111
    assert 689 <= doc_region.y1 <= 701


def test_page_matches_band_candidate_positive():
    blocks = [
        make_block(page_index=0, x0=40, y0=20, x1=250, y1=40, text="Header left"),
        make_block(page_index=0, x0=360, y0=20, x1=560, y1=40, text="Header right"),
        make_block(page_index=0, x0=60, y0=120, x1=540, y1=700, text="Body"),
    ]

    band = FurnitureBand(
        side="top",
        y0=20,
        y1=40,
        coverage_ratio=1.0,
        pages_present=10,
    )

    assert page_matches_band_candidate(
        page_blocks=blocks,
        page_width=600.0,
        page_height=800.0,
        side="top",
        band=band,
    )


def test_page_matches_band_candidate_negative():
    blocks = [
        make_block(page_index=0, x0=60, y0=120, x1=540, y1=700, text="Body"),
    ]

    band = FurnitureBand(
        side="top",
        y0=20,
        y1=40,
        coverage_ratio=1.0,
        pages_present=10,
    )

    assert not page_matches_band_candidate(
        page_blocks=blocks,
        page_width=600.0,
        page_height=800.0,
        side="top",
        band=band,
    )


def test_detect_repeated_furniture_bands_finds_stable_middle_pattern():
    page_width = 600.0
    page_height = 800.0
    blocks: list[PageBlock] = []

    for page_index in range(9):
        blocks.append(
            make_block(
                page_index=page_index,
                x0=60,
                y0=120,
                x1=540,
                y1=700,
                text=f"Body {page_index}",
                block_index=10,
            )
        )

        if page_index in {3, 4, 5}:
            blocks.append(
                make_block(
                    page_index=page_index,
                    x0=40,
                    y0=20,
                    x1=260,
                    y1=40,
                    text="Header left",
                    block_index=0,
                )
            )
            blocks.append(
                make_block(
                    page_index=page_index,
                    x0=360,
                    y0=20,
                    x1=560,
                    y1=40,
                    text=str(page_index + 1),
                    block_index=1,
                )
            )
            blocks.append(
                make_block(
                    page_index=page_index,
                    x0=40,
                    y0=760,
                    x1=280,
                    y1=780,
                    text="Footer left",
                    block_index=2,
                )
            )
            blocks.append(
                make_block(
                    page_index=page_index,
                    x0=360,
                    y0=760,
                    x1=560,
                    y1=780,
                    text=str(page_index + 1),
                    block_index=3,
                )
            )

    (
        header_band,
        footer_band,
        header_band_odd,
        header_band_even,
        footer_band_odd,
        footer_band_even,
        diagnostics,
    ) = detect_repeated_furniture_bands(
        blocks=blocks,
        page_count=9,
        page_width=page_width,
        page_height=page_height,
    )

    assert header_band is not None
    assert footer_band is not None
    assert diagnostics["middle_pages"] == [4, 5, 6]
    assert 18 <= header_band.y0 <= 22
    assert 38 <= header_band.y1 <= 42
    assert 758 <= footer_band.y0 <= 762
    assert 778 <= footer_band.y1 <= 782
    assert header_band_odd is not None or header_band_even is not None
    assert footer_band_odd is not None or footer_band_even is not None
