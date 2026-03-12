from __future__ import annotations


def split_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if current:
                blocks.append(current)
                current = []
            continue

        current.append(stripped)

    if current:
        blocks.append(current)

    return blocks
