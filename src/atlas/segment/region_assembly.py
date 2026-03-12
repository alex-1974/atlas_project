# src/atlas/segment/region_assembly.py
"""Assemble coarse document regions from scored blocks.

Design goals:
- cheap heuristic passes, no ML dependency
- deterministic and debuggable
- generic across scientific documents
- tolerant of imperfect OCR / extraction quality
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Region:
    region_type: str
    start_char: int
    end_char: int
    text: str
    confidence: float


EARLY_REGION_TYPES = {"title_page", "front_matter", "toc", "abstract_or_summary"}


def _clip(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))


def _ev(block, key: str, default: float = 0.0) -> float:
    value = block.evidence.get(key, default)
    return float(value) if isinstance(value, (int, float, bool)) else default


def _word_count(block) -> int:
    value = block.evidence.get("word_count", 0)
    return int(value or 0)


def _slice_region(region_type: str, blocks, start_idx: int, end_idx: int, confidence: float) -> Region | None:
    if start_idx < 0 or end_idx < start_idx or not blocks:
        return None
    chosen = blocks[start_idx : end_idx + 1]
    if not chosen:
        return None
    start_char = chosen[0].start_char
    end_char = chosen[-1].end_char
    text = "\n\n".join(block.text for block in chosen).strip()
    if not text:
        return None
    return Region(
        region_type=region_type,
        start_char=start_char,
        end_char=end_char,
        text=text,
        confidence=_clip(confidence),
    )


def _block_is_early_structural(block) -> bool:
    return (
        _ev(block, "title_like") >= 0.30
        or _ev(block, "author_like") >= 0.35
        or _ev(block, "affiliation_like") >= 0.35
        or _ev(block, "date_like") >= 0.35
        or _ev(block, "marker_like") >= 0.35
    )


def _block_is_running_body(block) -> bool:
    running = _ev(block, "running_text_like")
    references = _ev(block, "reference_like")
    bib = _ev(block, "bibliographic_entry_like")
    toc = _ev(block, "toc_like")
    list_like = _ev(block, "list_like")
    heading = _ev(block, "heading_like")
    words = _word_count(block)

    if words < 6:
        return False
    if running < 0.38:
        return False
    if references >= 0.45 or bib >= 0.45:
        return False
    if toc >= 0.45:
        return False
    if list_like >= 0.60 and heading < 0.45:
        return False
    return True


def _leading_title_span(blocks) -> tuple[int, int, float] | None:
    if not blocks:
        return None

    best_idx = -1
    best_score = 0.0
    search_window = min(len(blocks), 6)

    for idx in range(search_window):
        b = blocks[idx]
        score = 0.0
        score += _ev(b, "title_like") * 0.68
        score += _ev(b, "heading_like") * 0.18
        score += _ev(b, "marker_like") * 0.06
        score += 0.10 if idx == 0 else 0.05 if idx == 1 else 0.0
        score -= _ev(b, "reference_like") * 0.25
        score -= _ev(b, "bibliographic_entry_like") * 0.20
        score -= _ev(b, "toc_like") * 0.18
        score -= _ev(b, "list_like") * 0.10

        if score > best_score:
            best_idx = idx
            best_score = score

    if best_idx < 0 or best_score < 0.32:
        return None

    start = 0
    end = best_idx
    confidence = best_score

    for idx in range(best_idx + 1, min(len(blocks), best_idx + 4)):
        b = blocks[idx]
        words = _word_count(b)
        if words == 0:
            continue

        if (
            _ev(b, "title_like") >= 0.26
            or (_ev(b, "heading_like") >= 0.35 and words <= 18)
            or (_ev(b, "author_like") >= 0.45 and words <= 18)
        ):
            end = idx
            confidence = max(confidence, 0.66)
            continue
        break

    return start, end, _clip(confidence)


def _detect_toc_span(blocks) -> tuple[int, int, float] | None:
    if not blocks:
        return None

    best_start = -1
    best_end = -1
    best_score = 0.0
    early_limit = min(len(blocks), 14)

    idx = 0
    while idx < early_limit:
        if _ev(blocks[idx], "toc_like") < 0.45:
            idx += 1
            continue

        start = idx
        end = idx
        total = 0.0
        count = 0

        while end < early_limit:
            b = blocks[end]
            toc = _ev(b, "toc_like")
            list_like = _ev(b, "list_like")

            if toc >= 0.40 or (list_like >= 0.50 and _word_count(b) <= 20):
                total += max(toc, list_like * 0.8)
                count += 1
                end += 1
                continue
            break

        end -= 1
        if count >= 2:
            avg = total / count
            score = avg + min(0.2, 0.03 * count)
            if score > best_score:
                best_start, best_end, best_score = start, end, score

        idx = max(idx + 1, end + 2)

    if best_start < 0:
        return None
    return best_start, best_end, _clip(best_score)


def _detect_abstract_span(blocks) -> tuple[int, int, float] | None:
    if not blocks:
        return None

    search_limit = min(len(blocks), 12)

    for idx in range(search_limit):
        b = blocks[idx]
        marker = _ev(b, "marker_like")
        running = _ev(b, "running_text_like")
        words = _word_count(b)

        if marker >= 0.45 and running >= 0.20:
            start = idx
            end = idx
            total = running + marker
            count = 1

            for j in range(idx + 1, min(len(blocks), idx + 4)):
                bj = blocks[j]
                if _block_is_running_body(bj) and _ev(bj, "reference_like") < 0.25:
                    end = j
                    total += _ev(bj, "running_text_like")
                    count += 1
                else:
                    break

            return start, end, _clip((total / max(1, count)) * 0.75)

        if running >= 0.72 and words >= 50 and idx <= 4:
            return idx, idx, 0.58

    return None


def _detect_references_span(blocks) -> tuple[int, int, float] | None:
    if not blocks:
        return None

    start_search = max(0, len(blocks) // 2)
    best_start = -1
    best_end = -1
    best_score = 0.0

    idx = start_search
    while idx < len(blocks):
        b = blocks[idx]
        ref = max(_ev(b, "reference_like"), _ev(b, "bibliographic_entry_like"))

        if ref < 0.45:
            idx += 1
            continue

        start = idx
        end = idx
        total = ref
        count = 1

        for j in range(idx + 1, len(blocks)):
            bj = blocks[j]
            refj = max(_ev(bj, "reference_like"), _ev(bj, "bibliographic_entry_like"))
            runningj = _ev(bj, "running_text_like")

            if refj >= 0.38:
                end = j
                total += refj
                count += 1
                continue

            if runningj >= 0.50 and refj < 0.20:
                break

            if _word_count(bj) <= 8 and _ev(bj, "heading_like") >= 0.50:
                break

            end = j

        if count >= 2:
            avg = total / count
            score = avg + min(0.18, 0.025 * count)
            if score > best_score:
                best_start, best_end, best_score = start, end, score

        idx = max(idx + 1, end + 1)

    if best_start < 0:
        return None
    return best_start, best_end, _clip(best_score)


def _detect_front_matter_span(
    blocks,
    title_span: tuple[int, int, float] | None,
    toc_span: tuple[int, int, float] | None,
    abstract_span: tuple[int, int, float] | None,
) -> tuple[int, int, float] | None:
    if not blocks:
        return None

    start = title_span[1] + 1 if title_span else 0
    early_stop = min(len(blocks) - 1, 10)

    if toc_span and toc_span[0] <= early_stop:
        early_stop = min(early_stop, toc_span[0] - 1)
    if abstract_span and abstract_span[0] <= early_stop + 1:
        early_stop = min(early_stop, abstract_span[0] - 1)

    if early_stop < start:
        return None

    chosen: list[int] = []
    total = 0.0

    for idx in range(start, early_stop + 1):
        b = blocks[idx]
        score = 0.0
        score += _ev(b, "author_like") * 0.34
        score += _ev(b, "affiliation_like") * 0.24
        score += _ev(b, "date_like") * 0.16
        score += _ev(b, "marker_like") * 0.14
        score += _ev(b, "heading_like") * 0.08
        score += _ev(b, "title_like") * 0.08
        score -= _ev(b, "toc_like") * 0.25
        score -= _ev(b, "reference_like") * 0.35
        score -= _ev(b, "bibliographic_entry_like") * 0.30
        score -= _ev(b, "list_like") * 0.18 if _ev(b, "toc_like") < 0.35 else 0.0

        if score >= 0.18 or _block_is_early_structural(b):
            chosen.append(idx)
            total += max(score, 0.20)
            continue

        if chosen and _block_is_running_body(b):
            break

    if not chosen:
        return None

    start_idx = chosen[0]
    end_idx = chosen[-1]
    confidence = (total / len(chosen)) if chosen else 0.0
    return start_idx, end_idx, _clip(confidence)


def _overlaps(a: Region, b: Region) -> bool:
    return not (a.end_char <= b.start_char or b.end_char <= a.start_char)


def _priority(region_type: str) -> int:
    return {
        "title_page": 6,
        "toc": 5,
        "abstract_or_summary": 5,
        "references": 5,
        "front_matter": 4,
        "body": 1,
    }.get(region_type, 0)


def _merge_non_overlapping(regions: list[Region]) -> list[Region]:
    if not regions:
        return []

    ordered = sorted(
        regions,
        key=lambda r: (
            r.start_char,
            -(r.end_char - r.start_char),
            -_priority(r.region_type),
            -r.confidence,
        ),
    )

    kept: list[Region] = []
    for region in ordered:
        conflict = None
        for existing in kept:
            if _overlaps(region, existing):
                conflict = existing
                break

        if conflict is None:
            kept.append(region)
            continue

        new_len = region.end_char - region.start_char
        old_len = conflict.end_char - conflict.start_char
        new_key = (_priority(region.region_type), region.confidence, -new_len)
        old_key = (_priority(conflict.region_type), conflict.confidence, -old_len)

        if new_key > old_key:
            kept.remove(conflict)
            kept.append(region)

    return sorted(kept, key=lambda r: (r.start_char, r.end_char, r.region_type))


def _body_from_blocks(blocks, occupied: list[Region]) -> Region | None:
    if not blocks:
        return None

    occupied_ranges = [(r.start_char, r.end_char) for r in occupied]
    body_runs: list[tuple[int, int, float]] = []

    run_start = -1
    run_end = -1
    run_score = 0.0

    for idx, block in enumerate(blocks):
        blocked = any(block.start_char < end and start < block.end_char for start, end in occupied_ranges)
        if blocked:
            if run_start >= 0:
                body_runs.append((run_start, run_end, run_score))
                run_start = -1
                run_end = -1
                run_score = 0.0
            continue

        if _block_is_running_body(block):
            if run_start < 0:
                run_start = idx
                run_end = idx
                run_score = _ev(block, "running_text_like")
            else:
                run_end = idx
                run_score += _ev(block, "running_text_like")
        else:
            if run_start >= 0:
                body_runs.append((run_start, run_end, run_score))
                run_start = -1
                run_end = -1
                run_score = 0.0

    if run_start >= 0:
        body_runs.append((run_start, run_end, run_score))

    if not body_runs:
        return None

    best = max(
        body_runs,
        key=lambda item: (
            blocks[item[1]].end_char - blocks[item[0]].start_char,
            item[2],
        ),
    )
    start_idx, end_idx, total_score = best
    span_len = blocks[end_idx].end_char - blocks[start_idx].start_char
    confidence = 0.42
    if span_len > 1000:
        confidence = 0.62
    elif span_len > 300:
        confidence = 0.54
    confidence += min(0.12, total_score / max(1, (end_idx - start_idx + 1)) * 0.10)

    return _slice_region("body", blocks, start_idx, end_idx, confidence)


def _body_from_gaps(regions: list[Region], full_text: str) -> Region | None:
    if not full_text.strip():
        return None
    if not regions:
        return Region("body", 0, len(full_text), full_text.strip(), 0.45)

    ordered = sorted(regions, key=lambda r: r.start_char)
    gaps: list[tuple[int, int]] = []
    cursor = 0

    for region in ordered:
        if region.start_char > cursor:
            gaps.append((cursor, region.start_char))
        cursor = max(cursor, region.end_char)

    if cursor < len(full_text):
        gaps.append((cursor, len(full_text)))

    best_gap = None
    best_len = 0

    for start, end in gaps:
        snippet = full_text[start:end].strip()
        if not snippet:
            continue
        gap_len = len(snippet)
        if gap_len > best_len:
            best_gap = (start, end, snippet)
            best_len = gap_len

    if not best_gap:
        return None

    start, end, snippet = best_gap
    confidence = 0.55 if best_len > 500 else 0.40
    return Region("body", start, end, snippet, confidence)


def assemble_regions(blocks, full_text):
    """Return coarse document regions from scored blocks.

    Expected region types:
    - title_page
    - front_matter
    - abstract_or_summary
    - body
    - references
    - toc
    """
    if not blocks:
        text = (full_text or "").strip()
        return [Region("body", 0, len(text), text, 0.2)] if text else []

    regions: list[Region] = []

    title_span = _leading_title_span(blocks)
    toc_span = _detect_toc_span(blocks)
    abstract_span = _detect_abstract_span(blocks)
    references_span = _detect_references_span(blocks)
    front_matter_span = _detect_front_matter_span(blocks, title_span, toc_span, abstract_span)

    if title_span:
        region = _slice_region("title_page", blocks, title_span[0], title_span[1], title_span[2])
        if region:
            regions.append(region)

    if front_matter_span:
        region = _slice_region(
            "front_matter",
            blocks,
            front_matter_span[0],
            front_matter_span[1],
            front_matter_span[2],
        )
        if region:
            regions.append(region)

    if toc_span:
        region = _slice_region("toc", blocks, toc_span[0], toc_span[1], toc_span[2])
        if region:
            regions.append(region)

    if abstract_span:
        region = _slice_region("abstract_or_summary", blocks, abstract_span[0], abstract_span[1], abstract_span[2])
        if region:
            regions.append(region)

    if references_span:
        region = _slice_region("references", blocks, references_span[0], references_span[1], references_span[2])
        if region:
            regions.append(region)

    regions = _merge_non_overlapping(regions)

    body = _body_from_blocks(blocks, regions)
    if not body:
        body = _body_from_gaps(regions, full_text)
    if body:
        regions.append(body)

    ordered = sorted(regions, key=lambda r: (r.start_char, r.end_char, r.region_type))
    return ordered
