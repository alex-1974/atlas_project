from __future__ import annotations

from dataclasses import dataclass

from atlas.structure.header_parse import parse_header


@dataclass(slots=True)
class HeaderCandidates:
    lines: list[str]
    title_lines: list[str]
    author_lines: list[str]
    affiliation_lines: list[str]
    date_lines: list[str]
    journal_lines: list[str]


def extract_header_candidates(text: str) -> HeaderCandidates:
    parsed = parse_header(text)

    lines = [x.text for x in parsed.lines]

    affiliation_idx = {x.line_index for x in parsed.affiliation_lines}
    journal_idx = {x.line_index for x in parsed.journal_lines}
    date_idx = {x.line_index for x in parsed.date_lines}

    title_lines: list[str] = []
    author_lines: list[str] = []

    for item in parsed.lines:
        idx = item.line_index
        line = item.text

        if idx not in affiliation_idx and idx not in journal_idx:
            title_lines.append(line)

        if idx not in affiliation_idx and idx not in journal_idx:
            author_lines.append(line)

    return HeaderCandidates(
        lines=lines,
        title_lines=title_lines,
        author_lines=author_lines,
        affiliation_lines=[x.text for x in parsed.affiliation_lines],
        date_lines=[x.text for x in parsed.date_lines],
        journal_lines=[x.text for x in parsed.journal_lines],
    )
