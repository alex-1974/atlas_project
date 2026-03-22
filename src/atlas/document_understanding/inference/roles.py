from __future__ import annotations

from atlas.document_understanding.inference.early_meta import detect_early_meta_signals

ROLE_TITLE = "title"
ROLE_AUTHOR = "author"
ROLE_HEADING = "heading"
ROLE_BODY = "body"
ROLE_REFERENCE = "reference"
ROLE_CAPTION = "caption"
ROLE_NOISE = "noise"
ROLE_PAGE_FURNITURE = "page_furniture"
ROLE_FRONT_MATTER = "front_matter"


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def _caps_ratio(text: str) -> float:
    if not text:
        return 0.0
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    uppers = sum(1 for c in letters if c.isupper())
    return uppers / len(letters)


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.split()).strip()


def _looks_sentence_like(text: str) -> bool:
    value = _normalize(text)
    if not value:
        return False
    if _word_count(value) < 6:
        return False
    return value.endswith(".") or value.endswith(";") or value.endswith(":")


def _looks_like_author_line(text: str) -> bool:
    value = _normalize(text)
    if not value:
        return False

    wc = _word_count(value)
    if wc < 2 or wc > 8:
        return False

    low = value.lower()
    bad_markers = (
        "university",
        "universität",
        "faculty",
        "department",
        "institute",
        "journal",
        "vol.",
        "volume",
        "issue",
        "no.",
        "abstract",
        "summary",
        "eingereicht",
        "submitted",
        "accepted",
        "doi",
        "@",
        "copyright",
        "creative commons",
    )
    if any(marker in low for marker in bad_markers):
        return False

    alpha_words = []
    for w in value.split():
        w = w.strip(",;:.()[]")
        if any(ch.isalpha() for ch in w):
            alpha_words.append(w)

    if len(alpha_words) < 2:
        return False

    uppercase_initials = 0
    for w in alpha_words:
        if w and w[0].isupper():
            uppercase_initials += 1

    return uppercase_initials >= max(2, len(alpha_words) - 1)


def _looks_journal_header(text: str) -> bool:
    low = _normalize(text).lower()
    if not low:
        return False
    markers = (
        "journal",
        "review",
        "vol.",
        "volume",
        "issue",
        "no.",
        "issn",
        "doi",
        "copyright",
        "published by",
        "vernacular architecture",
    )
    return any(marker in low for marker in markers)


def _looks_strong_title_line(text: str) -> bool:
    value = _normalize(text)
    if not value:
        return False

    wc = _word_count(value)
    if wc < 2 or wc > 18:
        return False

    if _looks_sentence_like(value):
        return False

    if value.endswith("."):
        return False

    caps = _caps_ratio(value)
    if value.istitle():
        return True
    if 0.15 <= caps <= 0.95 and wc <= 12:
        return True
    return False


def _looks_heading_text(text: str) -> bool:
    value = _normalize(text)
    if not value:
        return False

    wc = _word_count(value)
    if wc == 0 or wc > 14:
        return False

    if _looks_sentence_like(value):
        return False

    if value.endswith("."):
        return False

    low = value.lower()
    if low in {"abstract", "references", "bibliography", "appendix", "contents"}:
        return True

    if value.istitle() and wc <= 8:
        return True

    caps = _caps_ratio(value)
    if caps > 0.55 and wc <= 10:
        return True

    return wc <= 4


def _looks_caption(text: str) -> bool:
    low = _normalize(text).lower()
    if not low:
        return False
    return (
        low.startswith("figure ")
        or low.startswith("fig. ")
        or low.startswith("fig ")
        or low.startswith("table ")
        or low.startswith("tab. ")
        or low.startswith("abb. ")
        or low.startswith("abbildung ")
        or low.startswith("tabelle ")
    )


def _is_referenceish_text(text: str) -> bool:
    low = _normalize(text).lower()
    markers = (
        "vol.",
        "volume",
        "issue",
        "pp.",
        "doi",
        "editor",
        "editors",
        "journal",
        "publisher",
        "isbn",
        "issn",
    )
    return any(marker in low for marker in markers)


def _clamp_non_negative(value: float) -> float:
    return max(0.0, float(value))


def _fetch_page_furniture_map(repo, document_id: str) -> dict[str, dict]:
    cur = repo.conn.cursor()
    cur.execute(
        """
        select
            b.block_id,
            coalesce(p.page_number_like, false) as page_number_like,
            coalesce(p.running_header_like, false) as running_header_like,
            coalesce(p.running_footer_like, false) as running_footer_like,
            coalesce(p.first_page_meta_like, false) as first_page_meta_like
        from du_blocks b
        left join du_block_page_furniture_signals p
            on p.block_id = b.block_id
        where b.document_id = %s
        """,
        (document_id,),
    )
    rows = cur.fetchall()

    out: dict[str, dict] = {}
    for (
        block_id,
        page_number_like,
        running_header_like,
        running_footer_like,
        first_page_meta_like,
    ) in rows:
        out[str(block_id)] = {
            "page_number_like": bool(page_number_like),
            "running_header_like": bool(running_header_like),
            "running_footer_like": bool(running_footer_like),
            "first_page_meta_like": bool(first_page_meta_like),
        }
    return out


def _resolve_role(
    *,
    text: str,
    title_score: float,
    heading_score: float,
    body_score: float,
    reference_score: float,
    caption_score: float,
    noise_score: float,
    furniture: dict | None,
) -> str:
    furniture = furniture or {}
    text_n = _normalize(text)
    wc = _word_count(text_n)

    if furniture.get("running_header_like"):
        return ROLE_PAGE_FURNITURE
    if furniture.get("running_footer_like"):
        return ROLE_PAGE_FURNITURE
    if furniture.get("page_number_like"):
        return ROLE_PAGE_FURNITURE

    if not text_n:
        return ROLE_NOISE

    if noise_score >= max(body_score, heading_score, title_score, 0.85):
        return ROLE_NOISE

    if caption_score >= max(reference_score, heading_score, body_score, title_score, noise_score):
        return ROLE_CAPTION

    if reference_score >= max(heading_score, body_score, title_score, noise_score):
        return ROLE_REFERENCE

    if furniture.get("first_page_meta_like"):
        if _looks_like_author_line(text_n):
            return ROLE_AUTHOR

        if (
            title_score >= max(heading_score + 0.10, body_score + 0.25, 0.75)
            and _looks_strong_title_line(text_n)
            and wc <= 14
        ):
            return ROLE_TITLE

        if _looks_journal_header(text_n):
            return ROLE_FRONT_MATTER

    if (
        title_score >= max(heading_score + 0.20, body_score + 0.35, 0.90)
        and _looks_strong_title_line(text_n)
        and wc <= 14
    ):
        return ROLE_TITLE

    if (
        heading_score >= max(body_score + 0.05, title_score - 0.10, noise_score)
        and _looks_heading_text(text_n)
    ):
        return ROLE_HEADING

    return ROLE_BODY


def compute_roles(repo, document_id: str) -> None:
    blocks = repo.fetch_blocks(document_id)
    signals = repo.fetch_block_signals(document_id)
    furniture_map = _fetch_page_furniture_map(repo, document_id)
    early_meta = detect_early_meta_signals(blocks, limit=10)

    signal_map = signals or {}
    rows = []

    for block in blocks:
        block_id = str(block.get("block_id"))
        text = _normalize(block.get("text"))
        low = text.lower()
        sig = signal_map.get(block_id) or {}
        furniture = furniture_map.get(block_id) or {}

        title_score = _safe_float(sig.get("title_like"))
        heading_score = _safe_float(sig.get("heading_like"))
        body_score = _safe_float(sig.get("body_like"))
        reference_score = _safe_float(sig.get("reference_like"))
        caption_score = _safe_float(sig.get("caption_like"))
        noise_score = _safe_float(sig.get("noise_like"))

        wc = _word_count(text)
        char_count = len(text)
        sentence_like = _looks_sentence_like(text)

        if furniture.get("first_page_meta_like"):
            title_score += 0.10
            heading_score += 0.05
            body_score *= 0.85

        if furniture.get("running_header_like") or furniture.get("running_footer_like") or furniture.get("page_number_like"):
            noise_score = max(noise_score, 0.90)
            title_score *= 0.10
            heading_score *= 0.10
            body_score *= 0.10
            reference_score *= 0.10
            caption_score *= 0.10

        if early_meta.get("has_journal_meta") and _looks_journal_header(text):
            if furniture.get("first_page_meta_like"):
                title_score += 0.03
            else:
                reference_score += 0.05

        if _looks_like_author_line(text):
            title_score *= 0.55
            heading_score *= 0.65
            body_score *= 0.70

        if _looks_caption(text):
            caption_score += 0.25
            title_score *= 0.25
            heading_score *= 0.60
            body_score *= 0.90

        if _is_referenceish_text(text):
            reference_score += 0.12
            title_score *= 0.40

        if low in {"references", "bibliography", "literatur", "literaturverzeichnis", "appendix"}:
            heading_score += 0.20
            reference_score += 0.20
            title_score *= 0.30

        if wc >= 15:
            title_score *= 0.35
        if wc >= 30:
            title_score *= 0.10
            heading_score *= 0.75
        if char_count >= 120:
            title_score *= 0.30
        if char_count >= 250:
            title_score *= 0.08
            heading_score *= 0.70
        if sentence_like:
            title_score *= 0.20
            heading_score *= 0.75
            body_score += 0.15
        if text.endswith("."):
            title_score *= 0.20
        if wc >= 20 and not furniture.get("first_page_meta_like"):
            body_score += 0.20

        if _looks_heading_text(text):
            heading_score += 0.12
            if wc <= 5:
                heading_score += 0.08

        if wc >= 25:
            body_score += 0.18
        if wc >= 40:
            body_score += 0.20

        title_score = _clamp_non_negative(title_score)
        heading_score = _clamp_non_negative(heading_score)
        body_score = _clamp_non_negative(body_score)
        reference_score = _clamp_non_negative(reference_score)
        caption_score = _clamp_non_negative(caption_score)
        noise_score = _clamp_non_negative(noise_score)

        role = _resolve_role(
            text=text,
            title_score=title_score,
            heading_score=heading_score,
            body_score=body_score,
            reference_score=reference_score,
            caption_score=caption_score,
            noise_score=noise_score,
            furniture=furniture,
        )

        rows.append(
            {
                "block_id": block_id,
                "role": role,
                "title_score": title_score,
                "heading_score": heading_score,
                "body_score": body_score,
                "reference_score": reference_score,
                "caption_score": caption_score,
                "noise_score": noise_score,
            }
        )

    repo.store_block_roles(document_id, rows)
