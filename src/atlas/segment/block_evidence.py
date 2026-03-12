from __future__ import annotations

from dataclasses import dataclass
import time
import typer

from atlas.segment.block_segmentation import segment_blocks
from atlas.structure.evidence import compute_block_evidence_dict


@dataclass
class ScoredBlock:

    block_index: int
    text: str
    lines: list[str]
    start_char: int
    end_char: int
    evidence: dict


def build_scored_blocks(text: str) -> list[ScoredBlock]:
    started = time.time()

    t0 = time.time()
    blocks = segment_blocks(text or "")
    segmentation_elapsed = time.time() - t0

    t1 = time.time()
    scored_blocks = []

    for block in blocks:
        evidence = compute_block_evidence_dict(block.text)

        scored_blocks.append(
            ScoredBlock(
                block_index=block.block_index,
                text=block.text,
                lines=block.text.splitlines(),
                start_char=block.start_char,
                end_char=block.end_char,
                evidence=evidence,
            )
        )

    evidence_elapsed = time.time() - t1
    total_elapsed = time.time() - started

    if total_elapsed > 1.0:
        typer.echo(
            f"build_scored_blocks slow: "
            f"total={total_elapsed:.2f}s "
            f"segment={segmentation_elapsed:.2f}s "
            f"evidence={evidence_elapsed:.2f}s "
            f"blocks_n={len(blocks)} "
            f"text_len={len(text)}"
        )

    return scored_blocks
