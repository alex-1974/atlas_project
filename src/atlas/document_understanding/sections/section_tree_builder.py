"""
atlas/du/sections/section_tree_builder.py

Build hierarchical section tree from extracted document lines.

Pipeline stage:
Document Understanding → Section Structure

Responsibilities
----------------
1. detect section numbers
2. merge split number + title lines
3. remove page numbers
4. build hierarchical section tree

Author: ATLAS
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------
# regex patterns
# ---------------------------------------------------------------------

SECTION_NUMBER_RE = re.compile(
    r"""
    ^
    (?P<num>
        \d+
        (\.\d+)*        # dotted sections
        [a-z]?          # optional letter
    )
    \.
    $
    """,
    re.VERBOSE,
)

SECTION_INLINE_RE = re.compile(
    r"""
    ^
    (?P<num>
        \d+
        (\.\d+)*[a-z]?
    )
    \.
    \s+
    (?P<title>.+)
    """,
    re.VERBOSE,
)

PAGE_NUMBER_RE = re.compile(r"^\d{1,4}$")


# ---------------------------------------------------------------------
# data model
# ---------------------------------------------------------------------

@dataclass
class SectionNode:

    number: str
    title: str
    level: int

    children: List["SectionNode"] = field(default_factory=list)

    def add_child(self, node: "SectionNode"):
        self.children.append(node)


# ---------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------

def section_level(num: str) -> int:
    return num.count(".")


def is_page_number(text: str) -> bool:
    return bool(PAGE_NUMBER_RE.match(text))


def is_section_number(text: str) -> Optional[str]:

    m = SECTION_NUMBER_RE.match(text)
    if m:
        return m.group("num")

    return None


# ---------------------------------------------------------------------
# merge number + title
# ---------------------------------------------------------------------

def merge_number_title(lines: List[str]) -> List[tuple[str, str]]:
    """
    Converts raw lines to (number,title) tuples.

    Handles:

        4.4.2.
        Holzverbindungen im Fachwerkbau
    """

    result = []

    i = 0
    n = len(lines)

    while i < n:

        line = lines[i].strip()

        # skip page numbers
        if is_page_number(line):
            i += 1
            continue

        # inline format
        m = SECTION_INLINE_RE.match(line)
        if m:

            num = m.group("num")
            title = m.group("title").strip()

            result.append((num, title))

            i += 1
            continue

        # number on its own line
        num = is_section_number(line)

        if num and i + 1 < n:

            title = lines[i + 1].strip()

            if not is_page_number(title) and len(title) > 1:

                result.append((num, title))
                i += 2
                continue

        i += 1

    return result


# ---------------------------------------------------------------------
# tree builder
# ---------------------------------------------------------------------

def build_section_tree(lines: List[str]) -> List[SectionNode]:

    pairs = merge_number_title(lines)

    root: List[SectionNode] = []

    stack: List[SectionNode] = []

    for num, title in pairs:

        level = section_level(num)

        node = SectionNode(
            number=num,
            title=title,
            level=level,
        )

        # unwind stack
        while stack and stack[-1].level >= level:
            stack.pop()

        if stack:
            stack[-1].add_child(node)
        else:
            root.append(node)

        stack.append(node)

    return root


# ---------------------------------------------------------------------
# debug printer
# ---------------------------------------------------------------------

def print_tree(nodes: List[SectionNode], indent: int = 0):

    for n in nodes:

        print("  " * indent + f"{n.number} {n.title}")

        if n.children:
            print_tree(n.children, indent + 1)
