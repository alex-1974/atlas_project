# src/atlas/understanding/core/vocab.py
"""Single source of truth for all Atlas DU vocabulary.

Every role name, zone name, and signal name used anywhere in the
understanding pipeline must come from here. No module defines its
own string constants.
"""
from __future__ import annotations


class Role:
    """Discrete semantic roles assigned to blocks in Layer 3."""

    TITLE          = "title"
    AUTHOR         = "author"
    HEADING        = "heading"
    BODY           = "body"
    REFERENCE      = "reference"
    CAPTION        = "caption"
    NOISE          = "noise"
    PAGE_FURNITURE = "page_furniture"
    FRONT_MATTER   = "front_matter"

    # Priority order used by roles._resolve_role — highest first.
    RESOLUTION_ORDER = (
        PAGE_FURNITURE,
        NOISE,
        CAPTION,
        REFERENCE,
        AUTHOR,
        TITLE,
        HEADING,
        BODY,
    )

    ALL = frozenset(RESOLUTION_ORDER)

    # Roles that consensus.py must never overwrite.
    CONSENSUS_PROTECTED = frozenset({AUTHOR, PAGE_FURNITURE, FRONT_MATTER})


class Zone:
    """Semantic document zones assigned to blocks in Layer 3."""

    TITLE_PAGE   = "title_page"
    ABSTRACT     = "abstract"
    TOC          = "toc"
    BODY         = "body"
    REFERENCES   = "references"
    APPENDIX     = "appendix"
    FRONT_MATTER = "front_matter"
    BACK_MATTER  = "back_matter"

    ALL = frozenset({
        TITLE_PAGE, ABSTRACT, TOC, BODY,
        REFERENCES, APPENDIX, FRONT_MATTER, BACK_MATTER,
    })

    # Zones whose headings are always Level 1 in section_tree.py.
    BACK_ANCHORS = frozenset({REFERENCES, APPENDIX})


class Signal:
    """Score column names written by aggregate/signals.py into du_block_signals."""

    TITLE_LIKE     = "title_like"
    HEADING_LIKE   = "heading_like"
    BODY_LIKE      = "body_like"       # was running_text_like in old system (Bug 1)
    AUTHOR_LIKE    = "author_like"
    REFERENCE_LIKE = "reference_like"
    CAPTION_LIKE   = "caption_like"
    NOISE_LIKE     = "noise_like"

    ALL = frozenset({
        TITLE_LIKE, HEADING_LIKE, BODY_LIKE, AUTHOR_LIKE,
        REFERENCE_LIKE, CAPTION_LIKE, NOISE_LIKE,
    })
